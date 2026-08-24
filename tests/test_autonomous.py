import json
import random
import tempfile
import unittest
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pandausagies_v2.autonomous import ROOT, build_director, observe
from pandausagies_v2.content import read_json
from pandausagies_v2.director import BANNED, AutonomousDirector, apply_decision
from pandausagies_v2.media import ExistingMediaProvider
from pandausagies_v2.memory import JsonMemoryStore, Memory
from pandausagies_v2.simulation import simulate
from pandausagies_v2.songs import choose_song
from pandausagies_v2.expression import ExpressionValidator


JST = ZoneInfo("Asia/Tokyo")
START = datetime(2026, 8, 24, tzinfo=JST)


class AutonomousCoreTests(unittest.TestCase):
    def test_observe_is_read_only_and_never_sends(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.json"
            before = path.exists()
            report = observe(START, path, seed=2)
            self.assertEqual(before, path.exists())
            self.assertFalse(report["sent"])
            self.assertEqual(report["external_calls"], 0)
            self.assertEqual(report["next_week"], "not finalized in OBSERVE")

    def test_corrupt_state_falls_back(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.json"
            path.write_text("{broken", encoding="utf-8")
            memory = JsonMemoryStore(path).load(Memory())
            self.assertEqual(memory.posts, [])

    def test_hard_daily_limit(self):
        memory = Memory(posts=[{"at": "2026-08-24T08:00:00+09:00"}, {"at": "2026-08-24T09:00:00+09:00"}])
        decision = build_director(1).decide(START.replace(hour=10), memory)
        self.assertEqual(decision.action, "skip")
        self.assertEqual(decision.reason, "daily hard limit")

    def test_song_and_media_avoid_recent_three(self):
        songs = read_json(ROOT / "content" / "songs.json")
        recent_songs = [song["id"] for song in songs[:3]]
        selected = choose_song(songs, recent_songs, random.Random(1))
        self.assertNotIn(selected["id"], recent_songs)
        provider = ExistingMediaProvider(ROOT, read_json(ROOT / "content" / "media.json"))
        recent_media = [item["id"] for item in provider.available()[:3]]
        self.assertNotIn(provider.choose(recent_media, random.Random(1))["id"], recent_media)

    def test_60_days_obeys_safety_and_week_rules(self):
        memory, report = simulate(60, 1234, START)
        self.assertLessEqual(report["max_posts_per_day"], 2)
        self.assertGreater(report["zero_post_days"], 0)
        self.assertEqual(report["weeks"], 9)
        self.assertEqual(report["week_ids"], [f"week-{n:02d}" for n in range(1, 10)])
        self.assertLessEqual(report["promo_rate"], 0.25)
        self.assertLessEqual(report["duplicate_rate"], 0.25)
        for post in memory.posts:
            self.assertLessEqual(len(post["text"].splitlines()), 2)
            self.assertNotIn("#", post["text"])
            self.assertFalse(any(word in post["text"] for word in BANNED))
            self.assertFalse(any(char in post["text"] for char in "😀😃😄😁😂🥲❤️🎸🌸"))
        weekly = [post for post in memory.posts if post.get("week_id")]
        self.assertEqual(len(weekly), len(memory.weeks))
        self.assertTrue(all(week["status"] == "simulated" for week in memory.weeks))
        self.assertTrue(all(week["immutable"] for week in memory.weeks))
        self.assertGreater(report["event_starts"], 0)
        self.assertGreater(report["event_completed"], 0)

    def test_distribution_does_not_collapse(self):
        _, report = simulate(60, 1234, START)
        self.assertEqual(set(report["category_distribution"]), {"ordinary", "offbeat", "promo"})
        self.assertEqual(set(report["motif_distribution"]), {"pot", "table", "bread", "guitar", "glasses", "crown", "flowers", "train", "room", "lunch"})
        self.assertNotIn("weather", report["motif_distribution"])
        self.assertLessEqual(report["category_distribution"]["offbeat"] / report["posts"], 0.25)
        self.assertLessEqual(max(report["motif_distribution"].values()) / report["posts"], 0.35)
        self.assertLessEqual(max(report["song_usage"].values()), 2)
        self.assertLessEqual(max(report["media_usage"].values()), 2)

    def test_poetic_recovery_is_rejected_and_concrete_action_passes(self):
        validator = ExpressionValidator()
        self.assertFalse(validator.validate("花が少し開いた\n音はしない").valid)
        self.assertFalse(validator.validate("今日は少し明るい\n特に理由はない").valid)
        self.assertTrue(validator.validate("お弁当のすき間\nパンで埋めた").valid)

    def test_simulation_rejects_unbounded_ranges(self):
        with self.assertRaises(ValueError):
            simulate(2, 1, START)


if __name__ == "__main__":
    unittest.main()
