from __future__ import annotations

import json
import os
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "dist"


def main() -> None:
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    OUTPUT.mkdir()

    for name in ("index.html", "styles.css", "player-core.js", "app.js"):
        shutil.copy2(ROOT / "site" / name, OUTPUT / name)

    supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    publishable_key = os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
    runtime = {
        "endpoint": f"{supabase_url}/rest/v1/public_state_snapshots?select=payload&published=eq.true&order=created_at.desc&limit=1" if supabase_url else "",
        "publishableKey": publishable_key,
    }
    (OUTPUT / "runtime-config.js").write_text(
        "globalThis.PANDAUSAGIES_CURRENT_ENDPOINT = " + json.dumps(runtime["endpoint"]) + ";\n"
        "globalThis.PANDAUSAGIES_PUBLISHABLE_KEY = " + json.dumps(runtime["publishableKey"]) + ";\n",
        encoding="utf-8",
    )

    shutil.copytree(ROOT / "content", OUTPUT / "content")
    shutil.copytree(ROOT / "media", OUTPUT / "media")

    index = OUTPUT / "index.html"
    html = index.read_text(encoding="utf-8")
    html = html.replace('href="./styles.css"', 'href="./styles.css"')
    html = html.replace('src="./app.js"', 'src="./app.js"')
    html = html.replace('src="../media/', 'src="./media/')
    html = html.replace('<script src="./app.js"', '<script src="./runtime-config.js"></script>\n  <script src="./app.js"')
    index.write_text(html, encoding="utf-8")

    app = OUTPUT / "app.js"
    javascript = app.read_text(encoding="utf-8")
    javascript = javascript.replace('const CONTENT_ROOT = "../content";', 'const CONTENT_ROOT = "./content";')
    javascript = javascript.replace('return path ? `../${path.replace', 'return path ? `./${path.replace')
    app.write_text(javascript, encoding="utf-8")
    print(f"site built: {OUTPUT}")


if __name__ == "__main__":
    main()
