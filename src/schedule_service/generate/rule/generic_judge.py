"""LLM-assisted resolver for `rule_generic` validation-rule matches.

When an MDL document matches a *generic* (equipment-less) validation rule, the
deterministic gate cannot confirm the rule's timeline applies to the document's
equipment, so the row is forced to ``needs_review`` (see
``schedule_generator._has_rule_ambiguity_reasons``). Measurement on Fadhili showed
~68% of these matches are correct because **no** equipment-specific rule exists — the
author intentionally wrote one generic rule covering all equipment. Only a minority have
a competing equipment-specific rule whose VT formula differs; those are the genuinely
ambiguous ones.

This module separates the two cases:

  1. **Deterministic bucketing (no LLM)** — for every ``rule_generic`` row:

       ``G_SAFE``  no competing equipment-specific rule exists      -> promote
       ``G_AMBIG`` a competing specific rule with a *different* VT   -> ask the LLM judge
       ``G_WEAK``  deliverable family/subtype not confirmed          -> keep in review

  2. **LLM judge (G_AMBIG only, cached + batched)** — adjudicates whether the generic
     rule's timeline genuinely applies, choosing only from a closed set of verdicts.

**Phase 1 is verify-only**: a verdict changes the review status / confidence flag, it
never changes the computed dates. Reassigning a row to a competing specific rule
(``use_specific``) is recorded for review but deferred to Phase 2.

The LLM judge is injected via the :class:`JudgeProvider` protocol so the bucketing and
verdict-application logic are fully testable offline without Azure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from schedule_service.generate.rule.matcher import RuleMatchQuality, _scope_keys
from schedule_service.generate.rule.models import ValidationRule

# --- buckets ---------------------------------------------------------------
BUCKET_NA = ""           # not a rule_generic row
BUCKET_SAFE = "g_safe"   # no competing specific rule -> generic is the only/best rule
BUCKET_AMBIG = "g_ambig" # competing specific rule with a different VT exists
BUCKET_WEAK = "g_weak"   # deliverable identity not confirmed -> not worth judging

# --- verdicts (closed set the LLM must choose from) ------------------------
VERDICT_NONE = ""                 # not judged (safe / weak / judge disabled)
VERDICT_GENERIC_OK = "generic_ok" # generic rule's timeline applies to this equipment
VERDICT_USE_SPECIFIC = "use_specific"  # a competing specific rule applies instead
VERDICT_UNCERTAIN = "uncertain"   # judge could not decide -> stay in review

# Minimum judge confidence required to act on a verdict.
_PROMOTE_CONFIDENCE = 0.6


@dataclass(frozen=True)
class GenericVerdict:
    """Outcome of resolving one ``rule_generic`` row."""

    bucket: str
    verdict: str = VERDICT_NONE
    chosen_rule_keyword: str = ""
    confidence: float = 0.0
    rationale: str = ""
    competing_count: int = 0

    @property
    def promotes(self) -> bool:
        """True when this verdict clears the generic ambiguity (row may become usable)."""
        if self.bucket == BUCKET_SAFE:
            return True
        return (
            self.bucket == BUCKET_AMBIG
            and self.verdict == VERDICT_GENERIC_OK
            and self.confidence >= _PROMOTE_CONFIDENCE
        )

    @property
    def flags_wrong(self) -> bool:
        """True when the judge says a competing specific rule should be used instead."""
        return self.bucket == BUCKET_AMBIG and self.verdict == VERDICT_USE_SPECIFIC

    def output_fields(self) -> dict[str, str]:
        """Stable string fields for generated schedule outputs (audit trail)."""
        return {
            "rule_generic_judge_bucket": self.bucket,
            "rule_generic_judge_verdict": self.verdict,
            "rule_generic_judge_confidence": f"{self.confidence:.2f}" if self.confidence else "",
            "rule_generic_judge_chosen_rule": self.chosen_rule_keyword,
            "rule_generic_judge_competing": str(self.competing_count) if self.competing_count else "",
            "rule_generic_judge_rationale": self.rationale,
        }


@dataclass(frozen=True)
class JudgePayload:
    """One G_AMBIG case handed to the LLM judge."""

    signature: str
    title: str
    deliverable: str
    equipment: str
    generic_keyword: str
    generic_submission: str
    generic_vt: str
    competing: list[dict[str, str]] = field(default_factory=list)

    def as_prompt_item(self) -> dict[str, object]:
        """Closed JSON object sent to the model."""
        return {
            "id": self.signature,
            "document": {
                "title": self.title,
                "deliverable": self.deliverable,
                "equipment": self.equipment,
            },
            "matched_generic_rule": {
                "keyword": self.generic_keyword,
                "submission_type": self.generic_submission,
                "vt": self.generic_vt,
            },
            "competing_specific_rules": self.competing,
        }


class JudgeProvider(Protocol):
    """Adjudicates a batch of G_AMBIG payloads -> verdict dict keyed by signature."""

    def judge(self, payloads: list[JudgePayload]) -> dict[str, GenericVerdict]:
        ...


# --- VT signature ----------------------------------------------------------

def _vt_signature(rule: ValidationRule) -> tuple:
    """Hashable signature of a rule's submission timeline (sub_type + parsed offsets)."""
    parsed = rule.vt_parsed or {}
    offsets = tuple(
        sorted(
            (k, v)
            for k, v in parsed.items()
            if isinstance(v, (int, float, bool)) and not isinstance(v, str)
        )
    )
    return (rule.sub_type, offsets)


# --- specific-rule index ---------------------------------------------------

@dataclass(frozen=True)
class _ScopedRule:
    rule: ValidationRule
    scope_keys: frozenset[str]
    vt_sig: tuple


def build_specific_rule_index(rules: list[ValidationRule]) -> dict[str, list[_ScopedRule]]:
    """Index equipment-scoped rules by canonical deliverable subtype (computed once).

    Only rules that carry an equipment scope are kept — those are the ones that can
    compete with a generic rule. Generic rules (no scope keys) are skipped.
    """
    index: dict[str, list[_ScopedRule]] = {}
    for rule in rules:
        keys = _scope_keys(
            f"{rule.item_name} {rule.doc_keyword}",
            set(rule._item_tokens) | set(rule._doc_kw_tokens),
        )
        if not keys:
            continue
        key = rule.canonical_deliverable_subtype or rule.canonical_deliverable_family
        index.setdefault(key, []).append(
            _ScopedRule(rule=rule, scope_keys=frozenset(keys), vt_sig=_vt_signature(rule))
        )
    return index


def _query_scope_tokens(quality: RuleMatchQuality) -> set[str]:
    return {t for t in (quality.query_scope or "").split("|") if t}


def find_competing_specific_rules(
    quality: RuleMatchQuality,
    generic_rule: ValidationRule,
    index: dict[str, list[_ScopedRule]],
) -> list[ValidationRule]:
    """Specific rules of the same deliverable subtype whose scope overlaps the document
    and whose timeline (sub_type + VT) differs from the matched generic rule."""
    subtype_key = quality.query_subtype or quality.query_family
    candidates = index.get(subtype_key, [])
    if not candidates:
        return []
    doc_scope = _query_scope_tokens(quality)
    if not doc_scope:
        return []
    generic_sig = _vt_signature(generic_rule)
    out: list[ValidationRule] = []
    for scoped in candidates:
        if not (scoped.scope_keys & doc_scope):
            continue
        if scoped.vt_sig == generic_sig:
            continue  # same timeline -> generic is harmless, not a real competitor
        out.append(scoped.rule)
    return out


# --- bucketing -------------------------------------------------------------

def classify_bucket(
    quality: RuleMatchQuality | None,
    generic_rule: ValidationRule | None,
    index: dict[str, list[_ScopedRule]],
) -> tuple[str, list[ValidationRule]]:
    """Return ``(bucket, competing_rules)`` for one row (deterministic, no LLM)."""
    if quality is None or generic_rule is None:
        return BUCKET_NA, []
    if quality.scope_status != "rule_generic":
        return BUCKET_NA, []
    # The deliverable type must be confirmed before we trust the generic rule at all.
    subtype_ok = getattr(quality, "subtype_status", "") in {"match", "not_applicable", ""}
    if quality.family_status != "match" or not subtype_ok:
        return BUCKET_WEAK, []
    competing = find_competing_specific_rules(quality, generic_rule, index)
    if not competing:
        return BUCKET_SAFE, []
    return BUCKET_AMBIG, competing


def _signature(row: dict[str, str], generic_rule: ValidationRule, competing: list[ValidationRule]) -> str:
    """Cache key: stable across rows that pose the identical judgement."""
    deliv = (row.get("Deliverable") or "").strip().upper()
    equip = (row.get("Equipment") or row.get("System") or "").strip().upper()
    comp = "|".join(sorted(r.doc_keyword for r in competing))
    return f"{deliv}>>{equip}>>{generic_rule.doc_keyword}>>{comp}"


def _build_payload(
    row: dict[str, str], generic_rule: ValidationRule, competing: list[ValidationRule]
) -> JudgePayload:
    return JudgePayload(
        signature=_signature(row, generic_rule, competing),
        title=(row.get("Title") or "").strip(),
        deliverable=(row.get("Deliverable") or "").strip(),
        equipment=(row.get("Equipment") or row.get("System") or "").strip(),
        generic_keyword=generic_rule.doc_keyword,
        generic_submission=generic_rule.sub_type,
        generic_vt=generic_rule.describe(),
        competing=[
            {
                "keyword": r.doc_keyword,
                "submission_type": r.sub_type,
                "vt": r.describe(),
            }
            for r in competing
        ],
    )


# --- orchestration ---------------------------------------------------------

def resolve_generic_verdicts(
    rows: list[dict[str, str]],
    rules: list[ValidationRule | None],
    qualities: list[RuleMatchQuality | None],
    all_rules: list[ValidationRule],
    provider: JudgeProvider | None = None,
) -> list[GenericVerdict | None]:
    """Resolve a verdict for every ``rule_generic`` row (``None`` for all others).

    Deterministic buckets (G_SAFE / G_WEAK) are decided locally. G_AMBIG rows are sent
    to ``provider`` in a single de-duplicated batch; without a provider they stay
    ``uncertain`` (safe default).
    """
    index = build_specific_rule_index(all_rules)
    verdicts: list[GenericVerdict | None] = [None] * len(rows)

    ambig_positions: list[int] = []
    ambig_payloads: dict[str, JudgePayload] = {}  # signature -> payload (dedup)
    ambig_sig: dict[int, str] = {}

    for i, (row, rule, quality) in enumerate(zip(rows, rules, qualities, strict=True)):
        bucket, competing = classify_bucket(quality, rule, index)
        if bucket == BUCKET_NA:
            continue
        if bucket == BUCKET_SAFE:
            verdicts[i] = GenericVerdict(bucket=BUCKET_SAFE)
        elif bucket == BUCKET_WEAK:
            verdicts[i] = GenericVerdict(bucket=BUCKET_WEAK)
        else:  # BUCKET_AMBIG
            payload = _build_payload(row, rule, competing)
            ambig_positions.append(i)
            ambig_sig[i] = payload.signature
            ambig_payloads.setdefault(payload.signature, payload)
            verdicts[i] = GenericVerdict(
                bucket=BUCKET_AMBIG, verdict=VERDICT_UNCERTAIN, competing_count=len(competing)
            )

    if provider and ambig_payloads:
        judged = provider.judge(list(ambig_payloads.values()))
        for i in ambig_positions:
            v = judged.get(ambig_sig[i])
            if v is not None:
                verdicts[i] = v
    return verdicts
