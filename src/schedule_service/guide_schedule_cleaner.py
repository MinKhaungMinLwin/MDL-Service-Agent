"""Backward-compatible CLI wrapper for guide schedule cleaning."""

from __future__ import annotations

from schedule_service.schedule_cleaner import *  # noqa: F403
from schedule_service.schedule_cleaner import main

if __name__ == "__main__":
    main()
