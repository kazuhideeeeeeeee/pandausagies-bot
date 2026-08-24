import json
import random
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pandausagies_v2.content import load_content
from pandausagies_v2.generator import build_candidate


class V2FoundationTests(unittest.TestCase):
    def test_content_files_load(self):
        content = load_content(Path(__file__).resolve().parent.parent / "content")
        self.assertIn("weeks.json", content)
        self.assertIsInstance(content["songs.json"], list)
        self.assertEqual(len(content["songs.json"]), 10)

    def test_current_song_references_registered_song_as_preview(self):
        content = load_content(Path(__file__).resolve().parent.parent / "content")
        song_ids = {song["id"] for song in content["songs.json"]}
        self.assertIn(content["current.json"]["currentSong"], song_ids)
        self.assertTrue(content["current.json"]["preview"])

    def test_site_keeps_canonical_and_download_urls(self):
        html = (Path(__file__).resolve().parent.parent / "site" / "index.html").read_text(encoding="utf-8")
        self.assertIn('rel="canonical" href="https://pandausa.dwmdog.com/"', html)
        self.assertIn("https://big-up.style/uviwifz2tO", html)

    def test_site_online_current_has_static_fallback(self):
        script = (Path(__file__).resolve().parent.parent / "site" / "app.js").read_text(encoding="utf-8")
        self.assertIn("PANDAUSAGIES_CURRENT_ENDPOINT", script)
        self.assertIn("PANDAUSAGIES_PUBLISHABLE_KEY", script)
        self.assertIn("normalizePublicState", script)
        self.assertIn('await loadJson("current.json")', script)
        self.assertIn("runtime.weeks", script)

    def test_candidate_is_short_and_structured(self):
        content = load_content(Path(__file__).resolve().parent.parent / "content")
        candidate = build_candidate(
            datetime(2026, 8, 24, 12, tzinfo=ZoneInfo("Asia/Tokyo")),
            content,
            Path(__file__).resolve().parent.parent / "media" / "weeks",
            random.Random(4),
        )
        self.assertLessEqual(len(candidate.text.splitlines()), 2)
        self.assertTrue(candidate.should_post)
        self.assertIn(candidate.category, {"life", "offbeat"})

    def test_missing_current_week_does_not_invent_media(self):
        content = {
            "songs.json": [],
            "weeks.json": [],
            "current.json": {"currentWeek": None, "currentSong": None},
        }
        candidate = build_candidate(
            datetime(2026, 8, 24, tzinfo=ZoneInfo("Asia/Tokyo")),
            content,
            Path("media/weeks"),
            random.Random(1),
        )
        self.assertIsNone(candidate.media_path)
        self.assertIsNone(candidate.song_id)


if __name__ == "__main__":
    unittest.main()
