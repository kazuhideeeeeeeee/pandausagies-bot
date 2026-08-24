from __future__ import annotations

import importlib.metadata
import json
import platform
import sys
from pathlib import Path

from pandausagies_v2.config import ROOT, load_settings
from pandausagies_v2.content import REQUIRED_FILES, read_json


PACKAGES = ("tweepy", "openai", "python-dotenv")


def status(value: bool) -> str:
    return "configured" if value else "missing"


def main() -> int:
    settings = load_settings()
    fatal = False
    print("pandausagies V2 diagnostics (no network calls, no posts)")
    print(f"Python: {platform.python_version()}")
    if sys.version_info[:2] != (3, 12):
        print("Python compatibility: warning (expected 3.12.x)")

    for package in PACKAGES:
        try:
            print(f"package {package}: {importlib.metadata.version(package)}")
        except importlib.metadata.PackageNotFoundError:
            fatal = True
            print(f"package {package}: missing")

    variables = {
        "API_KEY": bool(settings.api_key),
        "API_SECRET": bool(settings.api_secret),
        "ACCESS_TOKEN": bool(settings.access_token),
        "ACCESS_TOKEN_SECRET": bool(settings.access_token_secret),
        "OPENAI_API_KEY": bool(settings.openai_api_key),
        "SUPABASE_URL": bool(settings.supabase_url),
        "SUPABASE_SERVICE_ROLE_KEY": bool(settings.supabase_service_role_key),
    }
    for name, present in variables.items():
        print(f"{name}: {status(present)}")

    bot_media = ROOT / "BOTimg"
    media_count = len([path for path in bot_media.glob("*") if path.is_file()])
    print(f"BOTimg: {'readable' if bot_media.is_dir() else 'missing'} ({media_count} files)")
    if not bot_media.is_dir():
        fatal = True

    for name in REQUIRED_FILES:
        path = settings.content_dir / name
        try:
            read_json(path)
            print(f"content/{name}: readable")
        except (OSError, json.JSONDecodeError) as exc:
            fatal = True
            print(f"content/{name}: invalid ({type(exc).__name__})")

    print(f"X credential set: {status(settings.x_configured)}")
    print(f"OpenAI setting: {status(bool(settings.openai_api_key))}")
    print(f"DB setting: {status(settings.db_configured)}")
    print(f"result: {'FAIL' if fatal else 'PASS'}")
    return 1 if fatal else 0


if __name__ == "__main__":
    raise SystemExit(main())
