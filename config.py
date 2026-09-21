"""Configuration loading for the Telegram -> Discord mirror bot.

All secrets/config live in a local .env file (never in source control,
never printed to logs).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Load .env from this file's own directory, not the process's current
# working directory - keeps config loading correct no matter where/how
# the process is launched (e.g. a launchd agent with a different CWD).
load_dotenv(Path(__file__).resolve().parent / ".env")


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class Config:
    telegram_api_id: int
    telegram_api_hash: str
    telegram_channel: str
    discord_webhook_url: str
    session_name: str = "telegram_bridge"
    log_file: str = "tg_to_discord.log"
    # Skip downloading Telegram media larger than this (bytes). Avoids
    # wasting bandwidth/disk on files that are almost certainly bigger
    # than any Discord webhook will accept anyway.
    max_media_download_bytes: int = 100 * 1024 * 1024


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"Missing required environment variable: {name}")
    return value


def load_config() -> Config:
    api_id_raw = _require("TELEGRAM_API_ID")
    try:
        api_id = int(api_id_raw)
    except ValueError as exc:
        raise ConfigError("TELEGRAM_API_ID must be an integer") from exc

    return Config(
        telegram_api_id=api_id,
        telegram_api_hash=_require("TELEGRAM_API_HASH"),
        telegram_channel=_require("TELEGRAM_CHANNEL"),
        discord_webhook_url=_require("DISCORD_WEBHOOK_URL"),
    )
