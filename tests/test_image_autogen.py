import random
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from pandausagies_v2.autonomous import build_director
from pandausagies_v2.director import Decision
from pandausagies_v2.image_autogen import (
    FAKE_PNG,
    FakeImageProvider,
    GeneratedImage,
    ImageAutogenConfig,
    ImageAutogenError,
    ImagePlan,
    ImagePlanBuilder,
    ImagePromptBuilder,
    ImageSafetyValidator,
    InMemoryImageObjectStore,
    InMemoryImageRepository,
    OpenAIImageProvider,
    StagingImagePipeline,
    media_fingerprint,
    plan_fingerprint,
)
from pandausagies_v2.memory import Memory


JST = ZoneInfo("Asia/Tokyo")
NOW = datetime(2026, 8, 27, 12, 0, tzinfo=JST)


def phase_a_config(**overrides):
    values = dict(
        app_env="staging",
        provider="fake",
        enabled=True,
        post_ratio=0.20,
        daily_limit=2,
        monthly_limit=20,
        prompt_version="v1",
        storage_bucket="generated-media",
        require_glasses_default=True,
        blur_style_default=True,
        max_retries=0,
        timeout_seconds=30,
        allow_external_send=False,
        autonomous_enabled=False,
        kill_switch=True,
        x_write_enabled=False,
    )
    values.update(overrides)
    return ImageAutogenConfig(**values)


def image_decision(run_suffix="1"):
    return Decision(
        NOW.isoformat(),
        "post",
        "ordinary",
        "glasses",
        None,
        "none",
        None,
        None,
        False,
        "メガネを拭いた\n右だけ二回拭いた",
        "daily autonomous trace",
        post_type="image_single",
    )


def fixed_plan(glasses=True):
    return ImagePlan(
        run_id="run-1",
        post_type="image_single",
        category="ordinary",
        motif="train",
        scene="local train at dusk",
        mood="quiet, slightly odd, gently cheerful",
        outfit="casual cardigan in a muted color",
        glasses=glasses,
        blur_style="soft_out_of_focus",
        framing="portrait_vertical",
        caption="電車を一本見送った\n次の電車に乗った",
        prompt_version="v1",
        safety_flags={
            "adult_subject": True,
            "sexual_context": False,
            "violence": False,
            "self_harm": False,
            "celebrity": False,
            "politics_or_religion": False,
            "dominant_brand_logo": False,
        },
    )


class ImageAutogenTests(unittest.TestCase):
    def test_director_can_select_image_single_without_changing_default(self):
        normal = build_director(1).decide(NOW, Memory(), weekly_due=True)
        self.assertEqual(normal.post_type, "text_only")
        memory = Memory()
        memory.posts.append({"at": (NOW - timedelta(days=1)).isoformat(), "category": "promo", "motif": "bread", "text": "", "song_id": None, "media_id": None})
        selected = build_director(1, image_autogen_enabled=True, image_post_ratio=1.0).decide(NOW, memory, weekly_due=True)
        self.assertEqual(selected.action, "post")
        self.assertEqual(selected.post_type, "image_single")

    def test_enabled_post_type_policy_is_close_to_seventy_twenty_ten(self):
        director = build_director(2708, image_autogen_enabled=True, image_post_ratio=0.20, image_skip_ratio=0.10)
        counts = {"text_only": 0, "image_single": 0, "skip": 0}
        for _ in range(10000):
            counts[director._post_type("ordinary")] += 1
        self.assertTrue(6800 <= counts["text_only"] <= 7200)
        self.assertTrue(1800 <= counts["image_single"] <= 2200)
        self.assertTrue(800 <= counts["skip"] <= 1200)
        self.assertEqual(director._post_type("promo"), "text_only")

    def test_plan_and_prompt_preserve_character_and_safety(self):
        plan = ImagePlanBuilder(phase_a_config(), random.Random(4)).build(image_decision(), "run-1")
        prompt = ImagePromptBuilder().build(plan)
        self.assertEqual(plan.post_type, "image_single")
        self.assertIn(plan.motif, ("glasses",))
        self.assertIn("24-year-old Japanese woman", prompt)
        self.assertIn("pink bob haircut", prompt)
        self.assertIn("compact digital camera", prompt)
        self.assertIn("no sexualized pose", prompt)
        self.assertNotIn("brand campaign", prompt)
        self.assertEqual(len(plan.reference_media_ids), 5)

    def test_plan_avoids_recent_scene_and_outfit(self):
        recent = [{"scene": "adjusting glasses beside a notebook computer", "outfit": "soft gray hoodie"}]
        plan = ImagePlanBuilder(phase_a_config(), random.Random(2)).build(image_decision(), "run-2", recent)
        self.assertNotEqual(plan.scene, recent[0]["scene"])
        self.assertNotEqual(plan.outfit, recent[0]["outfit"])

    def test_glasses_are_present_in_roughly_eighty_percent_of_plans(self):
        builder = ImagePlanBuilder(phase_a_config(), random.Random(2708))
        count = sum(builder.build(image_decision(), f"ratio-{index}").glasses for index in range(1000))
        self.assertGreaterEqual(count, 750)
        self.assertLessEqual(count, 850)

    def test_empty_env_mapping_does_not_read_process_environment(self):
        config = ImageAutogenConfig.from_env({})
        self.assertEqual(config.app_env, "staging")
        self.assertEqual(config.provider, "fake")
        self.assertFalse(config.enabled)

    def test_fake_provider_is_deterministic_and_has_no_external_adapter(self):
        provider = FakeImageProvider()
        generated = provider.generate(fixed_plan(), ImagePromptBuilder().build(fixed_plan()))
        self.assertEqual(generated.content, FAKE_PNG)
        self.assertEqual(provider.calls, 1)
        self.assertEqual(generated.provider, "fake")

    def test_safety_rejects_missing_glasses_and_minor_appearance(self):
        signals = dict(FakeImageProvider().signals)
        signals.update(glasses=False, minor_appearance=True)
        image = GeneratedImage(FAKE_PNG, "image/png", 1, 1, "fake", signals)
        validation = ImageSafetyValidator().validate(fixed_plan(glasses=True), image)
        self.assertFalse(validation.approved)
        self.assertIn("glasses", validation.reasons)
        self.assertIn("minor_appearance", validation.reasons)

    def test_safety_rejects_bad_hands_background_outfit_and_ai_beauty(self):
        signals = dict(FakeImageProvider().signals)
        signals.update(outfit_natural=False, hands_integrity="bad", background_integrity="bad", ai_beauty_heavy=True)
        image = GeneratedImage(FAKE_PNG, "image/png", 1, 1, "fake", signals)
        validation = ImageSafetyValidator().validate(fixed_plan(), image)
        self.assertFalse(validation.approved)
        self.assertEqual(set(validation.reasons), {"outfit", "hands", "background", "ai_beauty"})

    def test_fingerprints_ignore_run_id_but_include_image_content(self):
        first = fixed_plan()
        second = ImagePlan(**{**first.to_dict(), "run_id": "run-2"})
        image = FakeImageProvider().generate(first, "prompt")
        self.assertEqual(plan_fingerprint(first), plan_fingerprint(second))
        self.assertEqual(media_fingerprint(first, image), media_fingerprint(second, image))

    def test_pipeline_fake_end_to_end_stores_private_candidate(self):
        provider = FakeImageProvider()
        repository = InMemoryImageRepository()
        objects = InMemoryImageObjectStore()
        result = StagingImagePipeline(phase_a_config(), provider, repository, objects, random.Random(1)).run(
            image_decision(), "run-success", NOW
        )
        self.assertEqual(result.status, "approved_candidate")
        self.assertEqual(result.post_type, "image_single")
        self.assertEqual(result.x_write, 0)
        self.assertEqual(len(repository.jobs), 1)
        self.assertEqual(len(repository.media), 1)
        self.assertEqual(len(objects.objects), 1)
        self.assertFalse(next(iter(repository.media.values()))["selected_for_post"])

    def test_provider_failure_falls_back_to_text_and_records_failure(self):
        provider = FakeImageProvider(fail=True)
        repository = InMemoryImageRepository()
        result = StagingImagePipeline(phase_a_config(), provider, repository, InMemoryImageObjectStore(), random.Random(1)).run(
            image_decision(), "run-fail", NOW
        )
        self.assertEqual(result.status, "fallback_text")
        self.assertEqual(result.post_type, "text_only")
        self.assertEqual(result.x_write, 0)
        self.assertEqual(next(iter(repository.jobs.values()))["status"], "failed")
        self.assertEqual(repository.get_setting("image_consecutive_failures"), 1)

    def test_image_circuit_breaker_blocks_provider_and_success_resets_it(self):
        blocked_repository = InMemoryImageRepository()
        blocked_repository.set_setting("image_circuit_open", True)
        blocked_provider = FakeImageProvider()
        blocked = StagingImagePipeline(
            phase_a_config(), blocked_provider, blocked_repository, InMemoryImageObjectStore(), random.Random(1)
        ).run(image_decision(), "run-circuit-open", NOW)
        self.assertEqual(blocked.reason, "image circuit breaker open")
        self.assertEqual(blocked_provider.calls, 0)

        recovering_repository = InMemoryImageRepository()
        recovering_repository.set_setting("image_consecutive_failures", 2)
        recovering_repository.set_setting("image_circuit_open", False)
        recovered = StagingImagePipeline(
            phase_a_config(), FakeImageProvider(), recovering_repository, InMemoryImageObjectStore(), random.Random(1)
        ).run(image_decision(), "run-circuit-recovered", NOW)
        self.assertEqual(recovered.status, "approved_candidate")
        self.assertEqual(recovering_repository.get_setting("image_consecutive_failures"), 0)
        self.assertFalse(recovering_repository.get_setting("image_circuit_open"))

    def test_invalid_caption_skips_when_text_fallback_is_not_safe(self):
        decision = replace(image_decision(), text="")
        result = StagingImagePipeline(
            phase_a_config(), FakeImageProvider(), InMemoryImageRepository(), InMemoryImageObjectStore(), random.Random(1)
        ).run(decision, "run-invalid-caption", NOW)
        self.assertEqual(result.status, "skipped")
        self.assertEqual(result.post_type, "skip")

    def test_duplicate_plan_falls_back_without_second_generation(self):
        class NoHistoryRepository(InMemoryImageRepository):
            def recent_generated(self, limit=5):
                return []

        repository = NoHistoryRepository()
        first_provider = FakeImageProvider()
        first = StagingImagePipeline(phase_a_config(), first_provider, repository, InMemoryImageObjectStore(), random.Random(5))
        self.assertEqual(first.run(image_decision(), "run-first", NOW).status, "approved_candidate")
        second_provider = FakeImageProvider()
        second = StagingImagePipeline(phase_a_config(), second_provider, repository, InMemoryImageObjectStore(), random.Random(5))
        result = second.run(image_decision(), "run-second", NOW + timedelta(minutes=1))
        self.assertEqual(result.status, "fallback_text")
        self.assertEqual(result.reason, "duplicate image plan")
        self.assertEqual(second_provider.calls, 0)

    def test_daily_limit_falls_back_before_provider(self):
        repository = InMemoryImageRepository()
        repository.jobs["old"] = {"created_at": NOW.isoformat(), "status": "failed", "run_id": "old"}
        provider = FakeImageProvider()
        result = StagingImagePipeline(
            phase_a_config(daily_limit=1), provider, repository, InMemoryImageObjectStore(), random.Random(1)
        ).run(image_decision(), "run-limit", NOW)
        self.assertEqual(result.reason, "image daily limit reached")
        self.assertEqual(provider.calls, 0)

    def test_phase_a_rejects_production_or_open_send_gates(self):
        for config in (
            phase_a_config(app_env="production"),
            phase_a_config(provider="openai"),
            phase_a_config(allow_external_send=True),
            phase_a_config(autonomous_enabled=True),
            phase_a_config(kill_switch=False),
            phase_a_config(x_write_enabled=True),
        ):
            with self.subTest(config=config):
                with self.assertRaises(ImageAutogenError):
                    config.require_phase_a()

    def test_real_provider_is_injectable_but_not_active_in_phase_a(self):
        provider = OpenAIImageProvider(lambda plan, prompt: FakeImageProvider().generate(plan, prompt))
        generated = provider.generate(fixed_plan(), "prompt")
        self.assertEqual(generated.mime_type, "image/png")
        self.assertEqual(provider.calls, 1)


if __name__ == "__main__":
    unittest.main()
