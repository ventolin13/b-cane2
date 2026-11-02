"""Настройки из окружения и .env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"


@dataclass(frozen=True)
class Config:
    token: str
    allowed_user_ids: frozenset[int]
    ollama_base_url: str
    default_model: str | None


def load_config() -> Config:
    load_dotenv(ROOT / ".env")
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN не задан")

    allowed = _parse_user_ids(os.getenv("ALLOWED_USER_IDS", ""))
    base_url = os.getenv("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL).strip()
    if not base_url:
        base_url = DEFAULT_OLLAMA_BASE_URL
    base_url = base_url.rstrip("/")

    default_model = os.getenv("DEFAULT_MODEL", "").strip() or None
    return Config(
        token=token,
        allowed_user_ids=allowed,
        ollama_base_url=base_url,
        default_model=default_model,
    )


def _parse_user_ids(raw: str) -> frozenset[int]:
    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.add(int(part))
        except ValueError:
            raise SystemExit(f"ALLOWED_USER_IDS: «{part}» не число") from None
    return frozenset(ids)
