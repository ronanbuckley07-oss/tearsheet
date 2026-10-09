"""Settings loaded from .env. Secrets never live in code."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "data" / "cache"

load_dotenv(ROOT / ".env")


def sec_user_name() -> str | None:
    return os.getenv("SEC_USER_NAME")


def sec_contact_email() -> str | None:
    return os.getenv("SEC_CONTACT_EMAIL")


def anthropic_api_key() -> str | None:
    return os.getenv("ANTHROPIC_API_KEY")
