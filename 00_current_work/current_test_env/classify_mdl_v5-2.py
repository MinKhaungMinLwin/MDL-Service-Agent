"""Classify MDL Excel document titles from the current test environment."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from standalone_config import DATA_DIR, OUTPUT_DIR, REPO_ROOT

sys.path.append(str(REPO_ROOT / "src"))

from common.config import required_env
from common.openai_client import build_azure_openai_client
from mdl_service.classification import MDLClassifier, load_system_prompt
from mdl_service.loader import list_excel_files
from mdl_service.service import MDLClassificationService

PROMPT_FILE = Path(
    os.getenv(
        "PROMPT_FILE",
        Path(__file__).resolve().parent / "ccpp_document_classification_prompt_260423.md",
    )
)


def main() -> None:
    """Classify requested or discoverable MDL workbooks."""
    system_prompt = load_system_prompt(PROMPT_FILE)
    client = build_azure_openai_client(
        api_version_env="AZURE_OPENAI_CHAT_API_VERSION",
        default_api_version="2024-12-01-preview",
        timeout=1200.0,
    )
    service = MDLClassificationService(
        classifier=MDLClassifier(
            client=client,
            model=required_env("AZURE_OPENAI_CHAT_DEPLOYMENT"),
            system_prompt=system_prompt,
        )
    )

    requested_file = sys.argv[1] if len(sys.argv) > 1 else None
    for input_path in list_excel_files(DATA_DIR, requested_file):
        if not input_path.exists():
            print(f"[ERROR] File not found: {input_path}")
            continue
        output_path = Path(OUTPUT_DIR) / f"{input_path.stem}_classified.csv"
        count = service.classify_file(input_path, output_path)
        print(f"[SAVED] {output_path} ({count} rows)")


if __name__ == "__main__":
    main()
