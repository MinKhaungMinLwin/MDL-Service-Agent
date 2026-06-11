"""Structured activity lookup helpers for system x phase anchoring."""

from __future__ import annotations

from dataclasses import dataclass

from schedule_service.generate.activity.models import ScheduleActivity


@dataclass(frozen=True)
class StructuredActivityIndex:
    """Lookup index over schedule activities keyed by (scope key, activity phase)."""

    cell_to_indexes: dict[tuple[str, str], tuple[int, ...]]
    systems: frozenset[str]

    def indexes_for(self, systems: list[str], phases: list[str]) -> list[int]:
        indexes: set[int] = set()
        for system in systems:
            for phase in phases:
                indexes.update(self.cell_to_indexes.get((system, phase), ()))
        return sorted(indexes)


def build_structured_activity_index(
    activities: list[ScheduleActivity],
    *,
    activity_phase,
    scope_keys,
) -> StructuredActivityIndex:
    """Build a reusable structured index for schedule activities."""
    cells: dict[tuple[str, str], list[int]] = {}
    systems: set[str] = set()
    for index, activity in enumerate(activities):
        text = " ".join([activity.activity_name_clean, activity.activity_name, activity.wbs_path])
        phase = activity_phase(text)
        keys = scope_keys(text)
        for key in keys:
            systems.add(key)
            if not phase:
                continue
            cells.setdefault((key, phase), []).append(index)
    return StructuredActivityIndex(
        cell_to_indexes={key: tuple(value) for key, value in cells.items()},
        systems=frozenset(systems),
    )
