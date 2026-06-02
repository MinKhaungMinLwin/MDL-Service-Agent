"""Shared Azure OpenAI client factory."""

from __future__ import annotations

import os

from openai import AzureOpenAI

from common.config import azure_endpoint, load_env_file, required_env


def build_azure_openai_client(api_version_env: str, default_api_version: str, **client_options):
    """Create an Azure OpenAI client using shared project configuration."""
    load_env_file()
    return AzureOpenAI(
        api_key=required_env("AZURE_OPENAI_API_KEY"),
        azure_endpoint=azure_endpoint(),
        api_version=os.getenv(api_version_env, default_api_version),
        **client_options,
    )
