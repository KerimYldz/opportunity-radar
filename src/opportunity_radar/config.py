"""Configuration loading. Settings live in YAML; secrets come only from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "settings.yaml"
DEFAULT_DB = PROJECT_ROOT / "data" / "radar.db"


@dataclass
class Secrets:
    telegram_token: str | None
    telegram_chat_id: str | None

    @property
    def telegram_configured(self) -> bool:
        return bool(self.telegram_token and self.telegram_chat_id)


def load_settings(path: str | os.PathLike | None = None) -> dict[str, Any]:
    load_dotenv(PROJECT_ROOT / ".env")
    path = Path(path or os.getenv("RADAR_CONFIG") or DEFAULT_CONFIG)
    with open(path, encoding="utf-8") as fh:
        settings = yaml.safe_load(fh) or {}
    weights = settings.get("priority_weights", {})
    total = sum(weights.values())
    if weights and abs(total - 1.0) > 0.01:
        raise ValueError(f"priority_weights must sum to 1.0 (got {total:.2f})")
    return settings


def load_secrets() -> Secrets:
    load_dotenv(PROJECT_ROOT / ".env")
    return Secrets(
        telegram_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID") or None,
    )


def db_path() -> Path:
    return Path(os.getenv("RADAR_DB_PATH") or DEFAULT_DB)
