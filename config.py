"""Configuration defaults, optionally overridden by environment variables."""

import math
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    output_dir: str = "downloads"
    visited_file: str = "visited.txt"
    queue_file: str = "queue.txt"
    log_file: str = "scraper.log"
    extensions: tuple[str, ...] = (".pdf", ".docx", ".doc", ".odt")
    workers: int = 5
    page_timeout: float = 15.0
    download_timeout: float = 30.0
    retries: int = 3
    backoff: float = 1.0
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )


def load_settings() -> Settings:
    """Load the repo's .env; existing environment variables take precedence."""
    load_dotenv(Path(__file__).with_name(".env"), override=False)
    values = {}
    for name, default in vars(Settings()).items():
        key = f"DOCRAWLER_{name.upper()}"
        raw = os.environ.get(key)
        if raw is None:
            continue
        raw = raw.strip()
        if not raw:
            raise ValueError(f"{key} must not be empty")
        if name == "extensions":
            values[name] = tuple(raw.split())
        elif isinstance(default, (int, float)):
            try:
                number = type(default)(raw)
            except ValueError:
                raise ValueError(f"{key} must be a number") from None
            minimum = 1 if name == "workers" else 0
            if not math.isfinite(number) or number < minimum:
                raise ValueError(f"{key} must be finite and at least {minimum}")
            if name in ("page_timeout", "download_timeout") and number == 0:
                raise ValueError(f"{key} must be greater than zero")
            values[name] = number
        else:
            values[name] = raw
    return Settings(**values)
