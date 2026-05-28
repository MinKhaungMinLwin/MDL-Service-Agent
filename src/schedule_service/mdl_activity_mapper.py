"""Backward-compatible CLI wrapper for schedule activity mapping."""

from __future__ import annotations

from schedule_service.activity_mapper import *  # noqa: F403
from schedule_service.activity_mapper import main

if __name__ == "__main__":
    main()

