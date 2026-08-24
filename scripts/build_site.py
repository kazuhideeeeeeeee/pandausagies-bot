from __future__ import annotations

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

    shutil.copytree(ROOT / "content", OUTPUT / "content")
    shutil.copytree(ROOT / "media", OUTPUT / "media")

    index = OUTPUT / "index.html"
    html = index.read_text(encoding="utf-8")
    html = html.replace('href="./styles.css"', 'href="./styles.css"')
    html = html.replace('src="./app.js"', 'src="./app.js"')
    html = html.replace('src="../media/', 'src="./media/')
    index.write_text(html, encoding="utf-8")

    app = OUTPUT / "app.js"
    javascript = app.read_text(encoding="utf-8")
    javascript = javascript.replace('const CONTENT_ROOT = "../content";', 'const CONTENT_ROOT = "./content";')
    javascript = javascript.replace('return path ? `../${path.replace', 'return path ? `./${path.replace')
    app.write_text(javascript, encoding="utf-8")
    print(f"site built: {OUTPUT}")


if __name__ == "__main__":
    main()
