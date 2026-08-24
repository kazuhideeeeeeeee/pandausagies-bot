from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
PROJECT_NAME = "pandausagies-v2-staging"
PNPM = "/Users/theberich/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback/pnpm"
NODE_BIN = "/Users/theberich/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin"


class SafeFailure(RuntimeError):
    pass


def cli(*args: str):
    environment = os.environ.copy()
    environment["PATH"] = f"{NODE_BIN}:{environment.get('PATH', '')}"
    completed = subprocess.run(
        [PNPM, "dlx", "supabase@latest", *args, "--agent", "no", "--output", "json"],
        cwd=ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode:
        raise SafeFailure("Supabase CLI command failed; authentication or project permission is insufficient")
    try:
        return json.loads(completed.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SafeFailure("Supabase CLI did not return parseable structured output") from exc


def project_ref(project: dict) -> str | None:
    return project.get("id") or project.get("ref") or project.get("project_ref")


def key_value(record: dict) -> str | None:
    return record.get("api_key") or record.get("key") or record.get("value")


def key_kind(record: dict) -> str:
    return str(record.get("type") or record.get("name") or "").lower()


def main() -> int:
    try:
        projects = cli("projects", "list")
        if isinstance(projects, dict):
            projects = projects.get("projects") or projects.get("data") or []
        matches = [item for item in projects if item.get("name") == PROJECT_NAME]
        if len(matches) != 1:
            raise SafeFailure("Exactly one accessible staging project with the expected name is required")
        reference = project_ref(matches[0])
        if not reference:
            raise SafeFailure("The staging project reference is unavailable")

        records = cli("projects", "api-keys", "--project-ref", reference, "--reveal")
        if isinstance(records, dict):
            records = records.get("api_keys") or records.get("keys") or records.get("data") or []
        publishable = next((key_value(item) for item in records if "publishable" in key_kind(item)), None)
        secret = next((key_value(item) for item in records if key_kind(item) == "secret" or "secret" in key_kind(item)), None)
        if not publishable or not secret:
            raise SafeFailure("Existing CLI authorization cannot reveal both publishable and secret keys; API key read permission or a reveal-capable official flow is required")
        if not str(publishable).startswith("sb_publishable_") or not str(secret).startswith("sb_secret_"):
            raise SafeFailure("The returned keys are not the expected publishable/secret key formats")

        content = "\n".join(
            (
                "APP_ENV=staging",
                "STORAGE_PROVIDER=supabase",
                "",
                f"SUPABASE_URL=https://{reference}.supabase.co",
                f"SUPABASE_PUBLISHABLE_KEY={publishable}",
                f"SUPABASE_SECRET_KEY={secret}",
                "",
                "X_PROVIDER=fake",
                "ALLOW_EXTERNAL_SEND=false",
                "AUTONOMOUS_ENABLED=false",
                "KILL_SWITCH=true",
                "FAKE_EXTERNALS=true",
                "",
            )
        )
        descriptor = os.open(ENV_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
        try:
            os.write(descriptor, content.encode("utf-8"))
        finally:
            os.close(descriptor)
        os.chmod(ENV_PATH, stat.S_IRUSR | stat.S_IWUSR)
        print("configuration: completed")
        return 0
    except SafeFailure as exc:
        print(f"configuration: stopped\nreason: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
