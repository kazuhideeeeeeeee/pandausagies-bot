from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    timezone: str
    openai_model: str
    api_key: str
    api_secret: str
    access_token: str
    access_token_secret: str
    openai_api_key: str
    supabase_url: str
    supabase_publishable_key: str
    supabase_secret_key: str
    content_dir: Path
    media_dir: Path

    @property
    def x_configured(self) -> bool:
        return all(
            (
                self.api_key,
                self.api_secret,
                self.access_token,
                self.access_token_secret,
            )
        )

    @property
    def db_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_secret_key)

    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


def load_settings() -> Settings:
    load_dotenv(ROOT / ".env")
    return Settings(
        timezone=os.getenv("TIMEZONE", "Asia/Tokyo"),
        openai_model=os.getenv("OPENAI_MODEL_TEXT", "gpt-4o-mini"),
        api_key=os.getenv("API_KEY", ""),
        api_secret=os.getenv("API_SECRET", ""),
        access_token=os.getenv("ACCESS_TOKEN", ""),
        access_token_secret=os.getenv("ACCESS_TOKEN_SECRET", ""),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        supabase_url=os.getenv("SUPABASE_URL", ""),
        supabase_publishable_key=os.getenv("SUPABASE_PUBLISHABLE_KEY", ""),
        supabase_secret_key=os.getenv("SUPABASE_SECRET_KEY", os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")),
        content_dir=ROOT / "content",
        media_dir=ROOT / "media" / "weeks",
    )
