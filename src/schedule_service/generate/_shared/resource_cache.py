"""Process-level memoized resources for the generate workflow.

The CCPP guide schedule, validation rules, BM25 index and semantic embedding indexes
are derived from static data files that do not change between requests. Rebuilding them
per request costs ~13s; this module caches them by file (path, mtime) — or by the
identity of an already-cached object — so a long-running server pays the build cost once.

All cached objects are read-only after construction (RuleMatcher's internal match cache
is safe and beneficial to share across requests), so sharing them between concurrent
requests is safe. A lock guards cache population only.
"""

from __future__ import annotations

from pathlib import Path
from threading import Lock

from loguru import logger

from schedule_service.generate.activity.lexical import BM25Index
from schedule_service.generate.activity.loader import load_schedule_activities
from schedule_service.generate.activity.models import ScheduleActivity
from schedule_service.generate.activity.semantic import SemanticIndex
from schedule_service.generate.rule.lexical import RuleLexicalIndex
from schedule_service.generate.rule.loader import load_rules
from schedule_service.generate.rule.matcher import RuleMatcher
from schedule_service.generate.rule.semantic import RuleSemanticIndex

_lock = Lock()
_activities: dict[tuple[str, float], list[ScheduleActivity]] = {}
_bm25: dict[int, BM25Index] = {}
_rule_matchers: dict[tuple[str, float], RuleMatcher | None] = {}
_activity_semantic: dict[int, SemanticIndex] = {}
_rule_semantic: dict[int, RuleSemanticIndex] = {}


def _file_key(path: Path) -> tuple[str, float]:
    """Cache key that invalidates automatically when the file is modified."""
    return (str(path.resolve()), path.stat().st_mtime)


def get_schedule_activities(schedule_path: Path) -> list[ScheduleActivity]:
    """Load (memoized) the CCPP guide schedule activities.

    The returned list is held for the process lifetime, so callers can safely key
    derived resources (BM25, semantic index) on its object identity.
    """
    key = _file_key(schedule_path)
    with _lock:
        cached = _activities.get(key)
        if cached is None:
            logger.info("Resource cache MISS — loading schedule activities: {}", schedule_path)
            cached = load_schedule_activities(schedule_path)
            _activities[key] = cached
        return cached


def get_bm25_index(activities: list[ScheduleActivity]) -> BM25Index:
    """Build (memoized) the BM25 index over *activities*, keyed by list identity."""
    key = id(activities)
    with _lock:
        cached = _bm25.get(key)
        if cached is None:
            logger.info("Resource cache MISS — building BM25 index ({} activities)", len(activities))
            cached = BM25Index([a.target_text for a in activities])
            _bm25[key] = cached
        return cached


def get_rule_matcher(rule_path: Path) -> RuleMatcher | None:
    """Load (memoized) the validation rule matcher; None when the file is missing."""
    if not rule_path.exists():
        logger.info("Validation rule file not found: {} — date ranges will be skipped", rule_path)
        return None
    key = _file_key(rule_path)
    with _lock:
        if key not in _rule_matchers:
            logger.info("Resource cache MISS — loading rules + matcher: {}", rule_path)
            rules = load_rules(rule_path)
            logger.info("Loaded {} validation rules from {}", len(rules), rule_path)
            _rule_matchers[key] = RuleMatcher(RuleLexicalIndex(rules))
        return _rule_matchers[key]


def get_activity_semantic_index(activities: list[ScheduleActivity], cache_dir: Path) -> SemanticIndex:
    """Build (memoized) the activity semantic embedding index, keyed by list identity."""
    key = id(activities)
    with _lock:
        cached = _activity_semantic.get(key)
        if cached is None:
            logger.info("Resource cache MISS — building activity semantic index")
            cached = SemanticIndex.build(activities, cache_dir)
            _activity_semantic[key] = cached
        return cached


def get_rule_semantic_index(matcher: RuleMatcher, cache_dir: Path) -> RuleSemanticIndex:
    """Build (memoized) the rule semantic embedding index, keyed by matcher identity.

    The index aligns with this matcher's rule list (same objects), so
    match_with_embedding's rule → row mapping stays valid across requests.
    """
    key = id(matcher)
    with _lock:
        cached = _rule_semantic.get(key)
        if cached is None:
            logger.info("Resource cache MISS — building rule semantic index")
            cached = RuleSemanticIndex.build(matcher.rules, cache_dir)
            _rule_semantic[key] = cached
        return cached


def clear() -> None:
    """Clear all memoized resources (test/maintenance use)."""
    with _lock:
        _activities.clear()
        _bm25.clear()
        _rule_matchers.clear()
        _activity_semantic.clear()
        _rule_semantic.clear()
