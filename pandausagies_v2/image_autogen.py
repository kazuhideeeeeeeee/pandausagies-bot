from __future__ import annotations

import base64
import hashlib
import json
import os
import random
import re
import socket
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Protocol
from urllib import error, parse, request

from .director import Decision
from .write_preflight import validate_post_candidate


MOTIF_SCENES = {
    "pot": ("small kitchen with an old enamel pot", "old room table beside a cooking pot", "rainy kitchen after grocery shopping"),
    "table": ("quiet meal at an old dining table", "notebook and glasses on a lived-in table", "night cafe table", "old neighborhood coffee shop"),
    "bread": ("neighborhood bakery on the way home", "bread on a small kitchen table", "park bench with a paper bag of bread"),
    "guitar": ("old room with a guitar by the wall", "quiet home recording desk with a guitar", "station stairs while carrying a guitar case"),
    "glasses": ("adjusting glasses beside a notebook computer", "holding a tiny screwdriver near her glasses", "station footbridge while adjusting her glasses"),
    "crown": ("small handmade crown resting on a table", "private celebration in an old room"),
    "flowers": ("flowers beside an old room window", "carrying one flower on a neighborhood street", "small park after rain"),
    "train": ("local train at dusk", "quiet station platform after one train left", "vending machines on a rainy station platform", "pedestrian overpass beside the railway"),
    "room": ("lived-in old apartment room", "softly lit room with laundry and books", "touching one strand of pink hair in an old room", "blank quiet moment beside the window"),
    "lunch": ("packing a small bento in the kitchen", "bento and bread on a dining table", "small bento on a park bench"),
}
REFERENCE_MEDIA_IDS = ("portrait-coat", "old-room-table", "crown-flowers", "flowers-portrait", "sweater-portrait")
OUTFITS = (
    "casual cardigan in a muted color",
    "soft gray hoodie",
    "navy striped T-shirt",
    "worn-in sweatshirt",
    "simple off-white shirt",
    "vintage-looking jacket",
    "loose knit sweater",
    "relaxed indoor clothes",
    "beige trench coat",
)
FRAMINGS = ("portrait_vertical", "square", "casual_horizontal")
FAKE_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class ImageAutogenError(RuntimeError):
    """Sanitized image-pipeline failure that never includes provider responses."""


class ImageProviderError(ImageAutogenError):
    pass


class ImageStorageError(ImageAutogenError):
    pass


@dataclass(frozen=True)
class ImageAutogenConfig:
    app_env: str = "staging"
    provider: str = "fake"
    enabled: bool = False
    post_ratio: float = 0.20
    skip_ratio: float = 0.10
    daily_limit: int = 2
    monthly_limit: int = 20
    prompt_version: str = "v1"
    storage_bucket: str = "generated-media"
    require_glasses_default: bool = True
    blur_style_default: bool = True
    max_retries: int = 0
    timeout_seconds: int = 30
    circuit_breaker_threshold: int = 3
    allow_external_send: bool = False
    autonomous_enabled: bool = False
    kill_switch: bool = True
    x_write_enabled: bool = False

    @classmethod
    def from_env(cls, values: dict[str, str] | None = None) -> "ImageAutogenConfig":
        source = os.environ if values is None else values

        def truth(name: str, default: bool) -> bool:
            raw = source.get(name)
            return default if raw is None else str(raw).strip().lower() == "true"

        return cls(
            app_env=str(source.get("APP_ENV", "staging")),
            provider=str(source.get("IMAGE_PROVIDER", "fake")),
            enabled=truth("IMAGE_AUTOGEN_ENABLED", False),
            post_ratio=float(source.get("IMAGE_POST_RATIO", "0.20")),
            skip_ratio=float(source.get("IMAGE_SKIP_RATIO", "0.10")),
            daily_limit=int(source.get("IMAGE_DAILY_LIMIT", "2")),
            monthly_limit=int(source.get("IMAGE_MONTHLY_LIMIT", "20")),
            prompt_version=str(source.get("IMAGE_PROMPT_VERSION", "v1")),
            storage_bucket=str(source.get("IMAGE_STORAGE_BUCKET", "generated-media")),
            require_glasses_default=truth("IMAGE_REQUIRE_GLASSES_DEFAULT", True),
            blur_style_default=truth("IMAGE_BLUR_STYLE_DEFAULT", True),
            max_retries=int(source.get("IMAGE_MAX_RETRIES", "0")),
            timeout_seconds=int(source.get("IMAGE_TIMEOUT_SECONDS", "30")),
            circuit_breaker_threshold=int(source.get("IMAGE_CIRCUIT_BREAKER_THRESHOLD", "3")),
            allow_external_send=truth("ALLOW_EXTERNAL_SEND", False),
            autonomous_enabled=truth("AUTONOMOUS_ENABLED", False),
            kill_switch=truth("KILL_SWITCH", True),
            x_write_enabled=truth("X_WRITE_ENABLED", False),
        )

    def require_phase_a(self) -> None:
        if self.app_env != "staging" or self.provider != "fake" or not self.enabled:
            raise ImageAutogenError("Phase A requires enabled fake provider in staging")
        if self.allow_external_send or self.autonomous_enabled or self.x_write_enabled or not self.kill_switch:
            raise ImageAutogenError("Phase A external safety gates must remain closed")
        if not 0.0 <= self.post_ratio <= 1.0 or not 0.0 <= self.skip_ratio <= 1.0 or self.post_ratio + self.skip_ratio > 1.0:
            raise ImageAutogenError("invalid image post-type ratios")
        if self.daily_limit < 1 or self.monthly_limit < 1 or self.max_retries != 0 or self.circuit_breaker_threshold < 1:
            raise ImageAutogenError("invalid Phase A cost limits")
        if not 1 <= self.timeout_seconds <= 120:
            raise ImageAutogenError("invalid image timeout")


@dataclass(frozen=True)
class ImagePlan:
    run_id: str
    post_type: str
    category: str
    motif: str
    scene: str
    mood: str
    outfit: str
    glasses: bool
    blur_style: str
    framing: str
    caption: str
    prompt_version: str
    safety_flags: dict[str, bool]
    reference_media_ids: tuple[str, ...] = REFERENCE_MEDIA_IDS

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GeneratedImage:
    content: bytes
    mime_type: str
    width: int
    height: int
    provider: str
    quality_signals: dict[str, Any]


@dataclass(frozen=True)
class ImageValidation:
    approved: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class StoredObject:
    bucket: str
    path: str


@dataclass(frozen=True)
class ImagePipelineResult:
    status: str
    post_type: str
    reason: str
    run_id: str
    plan: dict[str, Any] | None = None
    storage_path: str | None = None
    fingerprint: str | None = None
    moderation_status: str | None = None
    provider_calls: int = 0
    x_api_requests: int = 0
    x_write: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ImageProvider(Protocol):
    name: str
    calls: int

    def generate(self, plan: ImagePlan, prompt: str) -> GeneratedImage: ...


class ImageObjectStore(Protocol):
    def put(self, bucket: str, path: str, content: bytes, mime_type: str) -> StoredObject: ...


class ImageMetadataRepository(Protocol):
    def count_attempts(self, start: datetime, end: datetime) -> int: ...
    def find_duplicate(self, fingerprint: str) -> bool: ...
    def recent_generated(self, limit: int = 5) -> list[dict[str, Any]]: ...
    def create_job(self, row: dict[str, Any]) -> None: ...
    def update_job(self, job_id: str, values: dict[str, Any]) -> None: ...
    def save_generated(self, row: dict[str, Any]) -> None: ...
    def get_setting(self, key: str, default: Any = None) -> Any: ...
    def set_setting(self, key: str, value: Any) -> None: ...


class FakeImageProvider:
    name = "fake"

    def __init__(self, fail: bool = False, signals: dict[str, Any] | None = None):
        self.fail = fail
        self.calls = 0
        self.signals = signals or {
            "face_count": 1,
            "face_integrity": "ok",
            "pink_bob": True,
            "glasses": True,
            "exposure": "normal",
            "gore": False,
            "celebrity_similarity": False,
            "minor_appearance": False,
            "logo_dominant": False,
            "outfit_natural": True,
            "hands_integrity": "ok",
            "background_integrity": "ok",
            "ai_beauty_heavy": False,
        }

    def generate(self, plan: ImagePlan, prompt: str) -> GeneratedImage:
        self.calls += 1
        if self.fail:
            raise ImageProviderError("fake provider unavailable")
        return GeneratedImage(FAKE_PNG, "image/png", 1, 1, self.name, dict(self.signals))


class OpenAIImageProvider:
    """Phase B injection point; no SDK or network is constructed in Phase A."""

    name = "openai"

    def __init__(self, generate_fn: Callable[[ImagePlan, str], GeneratedImage] | None = None):
        self.generate_fn = generate_fn
        self.calls = 0

    def generate(self, plan: ImagePlan, prompt: str) -> GeneratedImage:
        self.calls += 1
        if self.generate_fn is None:
            raise ImageProviderError("real image provider is not configured")
        return self.generate_fn(plan, prompt)


def build_image_provider(
    config: ImageAutogenConfig,
    openai_generate: Callable[[ImagePlan, str], GeneratedImage] | None = None,
) -> ImageProvider:
    if config.provider == "fake":
        return FakeImageProvider()
    if config.provider == "openai":
        return OpenAIImageProvider(openai_generate)
    raise ImageAutogenError("unsupported image provider")


class ImagePlanBuilder:
    def __init__(self, config: ImageAutogenConfig, rng: random.Random | None = None):
        self.config = config
        self.rng = rng or random.Random()

    def build(self, decision: Decision, run_id: str, recent: list[dict[str, Any]] | None = None) -> ImagePlan:
        if decision.action != "post" or decision.post_type != "image_single":
            raise ImageAutogenError("image plan requires image_single post decision")
        if decision.category not in ("ordinary", "offbeat") or not decision.motif or decision.motif not in MOTIF_SCENES:
            raise ImageAutogenError("image plan category or motif is unsupported")
        history = recent or []
        recent_scenes = {row.get("scene") for row in history[-2:]}
        recent_outfits = {row.get("outfit") for row in history[-2:]}
        scenes = [value for value in MOTIF_SCENES[decision.motif] if value not in recent_scenes] or list(MOTIF_SCENES[decision.motif])
        outfits = [value for value in OUTFITS if value not in recent_outfits] or list(OUTFITS)
        glasses_probability = 0.80 if self.config.require_glasses_default else 0.50
        return ImagePlan(
            run_id=run_id,
            post_type="image_single",
            category=decision.category,
            motif=decision.motif,
            scene=self.rng.choice(scenes),
            mood="quiet, slightly odd, gently cheerful",
            outfit=self.rng.choice(outfits),
            glasses=self.rng.random() < glasses_probability,
            blur_style="soft_out_of_focus" if self.config.blur_style_default else "subtle_compact_camera_softness",
            framing=self.rng.choice(FRAMINGS),
            caption=decision.text,
            prompt_version=self.config.prompt_version,
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


class ImagePromptBuilder:
    def build(self, plan: ImagePlan) -> str:
        glasses = "wearing thin, slightly retro double-bridge glasses" if plan.glasses else "without glasses as a rare exception"
        return " ".join(
            (
                "A private everyday snapshot of one 24-year-old Japanese woman, clearly an adult,",
                "with a pink bob haircut and quiet natural makeup,",
                glasses + ",",
                f"in {plan.scene}, wearing {plan.outfit}.",
                f"Mood: {plan.mood}.",
                "Early-2000s compact digital camera and toy-film feeling, mild flash, soft grain,",
                f"slight hand shake and {plan.blur_style}, {plan.framing}, recognizable face and situation.",
                "Lived-in, unpolished, softly nostalgic, cute but low-key, not influencer-like, not luxury.",
                "No text, no watermark, no dominant logo, no celebrity resemblance, no childlike appearance,",
                "no sexualized pose, no revealing clothes, no lingerie or swimwear, no violence, gore, politics, religion, cosplay, idol styling, or horror.",
                "Avoid malformed face, extra people, malformed hands, collapsed background, and glossy AI-beauty aesthetics.",
            )
        )


class ImageSafetyValidator:
    def validate(self, plan: ImagePlan, image: GeneratedImage) -> ImageValidation:
        reasons: list[str] = []
        signals = image.quality_signals
        if not image.content or image.mime_type not in ("image/png", "image/jpeg", "image/webp"):
            reasons.append("generation_or_mime")
        if image.width < 1 or image.height < 1:
            reasons.append("dimensions")
        if signals.get("face_count") != 1 or signals.get("face_integrity") != "ok":
            reasons.append("face")
        if not signals.get("pink_bob"):
            reasons.append("pink_hair")
        if plan.glasses and not signals.get("glasses"):
            reasons.append("glasses")
        if signals.get("minor_appearance"):
            reasons.append("minor_appearance")
        if signals.get("exposure") != "normal":
            reasons.append("exposure")
        if signals.get("gore"):
            reasons.append("gore")
        if signals.get("celebrity_similarity"):
            reasons.append("celebrity")
        if signals.get("logo_dominant"):
            reasons.append("logo")
        if signals.get("outfit_natural") is not True:
            reasons.append("outfit")
        if signals.get("hands_integrity") != "ok":
            reasons.append("hands")
        if signals.get("background_integrity") != "ok":
            reasons.append("background")
        if signals.get("ai_beauty_heavy"):
            reasons.append("ai_beauty")
        if not plan.safety_flags.get("adult_subject") or any(
            plan.safety_flags.get(name) for name in ("sexual_context", "violence", "self_harm", "celebrity", "politics_or_religion", "dominant_brand_logo")
        ):
            reasons.append("plan_safety")
        return ImageValidation(not reasons, tuple(reasons))


def canonical_fingerprint(value: dict[str, Any]) -> str:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def plan_fingerprint(plan: ImagePlan) -> str:
    value = plan.to_dict()
    value.pop("run_id", None)
    value.pop("safety_flags", None)
    return canonical_fingerprint(value)


def media_fingerprint(plan: ImagePlan, image: GeneratedImage) -> str:
    return canonical_fingerprint({"plan": plan_fingerprint(plan), "content_sha256": hashlib.sha256(image.content).hexdigest()})


class InMemoryImageRepository:
    def __init__(self):
        self.jobs: dict[str, dict[str, Any]] = {}
        self.media: dict[str, dict[str, Any]] = {}
        self.settings: dict[str, Any] = {}

    def count_attempts(self, start: datetime, end: datetime) -> int:
        return sum(
            row.get("status") in ("generating", "approved", "rejected", "failed")
            and start <= datetime.fromisoformat(row["created_at"]) < end
            for row in self.jobs.values()
        )

    def find_duplicate(self, fingerprint: str) -> bool:
        return any(row.get("fingerprint") == fingerprint for row in self.media.values()) or any(row.get("plan_fingerprint") == fingerprint for row in self.jobs.values())

    def recent_generated(self, limit: int = 5) -> list[dict[str, Any]]:
        rows = sorted(self.media.values(), key=lambda row: row["created_at"])
        return [dict(row) for row in rows[-limit:]]

    def create_job(self, row: dict[str, Any]) -> None:
        if row["id"] in self.jobs or any(existing["run_id"] == row["run_id"] for existing in self.jobs.values()):
            raise ImageStorageError("duplicate media job")
        self.jobs[row["id"]] = dict(row)

    def update_job(self, job_id: str, values: dict[str, Any]) -> None:
        self.jobs[job_id].update(values)

    def save_generated(self, row: dict[str, Any]) -> None:
        if row["id"] in self.media or self.find_duplicate(row["fingerprint"]):
            raise ImageStorageError("duplicate generated media")
        self.media[row["id"]] = dict(row)

    def get_setting(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key, default)

    def set_setting(self, key: str, value: Any) -> None:
        self.settings[key] = value


class InMemoryImageObjectStore:
    def __init__(self):
        self.objects: dict[tuple[str, str], tuple[bytes, str]] = {}

    def put(self, bucket: str, path: str, content: bytes, mime_type: str) -> StoredObject:
        key = (bucket, path)
        if key in self.objects:
            raise ImageStorageError("storage object already exists")
        self.objects[key] = (bytes(content), mime_type)
        return StoredObject(bucket, path)


class SupabaseImageRepository:
    def __init__(self, client):
        self.client = client

    def count_attempts(self, start: datetime, end: datetime) -> int:
        query = (
            "select=id&created_at=gte."
            + parse.quote(start.isoformat())
            + "&created_at=lt."
            + parse.quote(end.isoformat())
            + "&status=in.(generating,approved,rejected,failed)"
        )
        return len(self.client.select("media_jobs", query))

    def find_duplicate(self, fingerprint: str) -> bool:
        media = self.client.select("generated_media", f"select=id&fingerprint=eq.{parse.quote(fingerprint)}&limit=1")
        jobs = self.client.select("media_jobs", f"select=id&plan_fingerprint=eq.{parse.quote(fingerprint)}&status=in.(planned,generating,approved)&limit=1")
        return bool(media or jobs)

    def recent_generated(self, limit: int = 5) -> list[dict[str, Any]]:
        rows = self.client.select("generated_media", f"select=scene,outfit,created_at&order=created_at.desc&limit={max(1, min(limit, 20))}")
        return list(reversed(rows))

    def create_job(self, row: dict[str, Any]) -> None:
        self.client.insert("media_jobs", row)

    def update_job(self, job_id: str, values: dict[str, Any]) -> None:
        self.client.patch("media_jobs", f"id=eq.{parse.quote(job_id)}", values)

    def save_generated(self, row: dict[str, Any]) -> None:
        self.client.insert("generated_media", row)

    def get_setting(self, key: str, default: Any = None) -> Any:
        rows = self.client.select("settings", f"select=value&key=eq.{parse.quote(key)}&limit=1")
        return rows[0]["value"] if rows else default

    def set_setting(self, key: str, value: Any) -> None:
        rows = self.client.select("settings", f"select=key&key=eq.{parse.quote(key)}&limit=1")
        if rows:
            self.client.patch("settings", f"key=eq.{parse.quote(key)}", {"value": value})
        else:
            self.client.insert("settings", {"key": key, "value": value})


class SupabaseImageObjectStore:
    """Private bucket uploader using an opaque backend secret only in `apikey`."""

    def __init__(self, url: str, secret_key: str, timeout: int = 30):
        if not url.startswith("https://") or not secret_key:
            raise ValueError("Supabase Storage credentials are not configured")
        self.url = url.rstrip("/")
        self.secret_key = secret_key
        self.timeout = timeout

    def put(self, bucket: str, path: str, content: bytes, mime_type: str) -> StoredObject:
        safe_bucket = parse.quote(bucket, safe="")
        safe_path = parse.quote(path, safe="/")
        req = request.Request(
            f"{self.url}/storage/v1/object/{safe_bucket}/{safe_path}",
            data=content,
            method="POST",
            headers={
                "apikey": self.secret_key,
                "Content-Type": mime_type,
                "x-upsert": "false",
                "User-Agent": "pandausagies-v2-staging-image-worker/1.0",
            },
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                response.read()
                if response.status not in (200, 201):
                    raise ImageStorageError("Supabase Storage upload failed")
        except (error.HTTPError, error.URLError, TimeoutError, socket.timeout):
            raise ImageStorageError("Supabase Storage upload failed") from None
        return StoredObject(bucket, path)


def _period_bounds(now: datetime) -> tuple[tuple[datetime, datetime], tuple[datetime, datetime]]:
    start_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_month = start_day.replace(day=1)
    if start_month.month == 12:
        next_month = start_month.replace(year=start_month.year + 1, month=1)
    else:
        next_month = start_month.replace(month=start_month.month + 1)
    from datetime import timedelta

    return (start_day, start_day + timedelta(days=1)), (start_month, next_month)


def _safe_object_path(now: datetime, run_id: str, fingerprint: str, mime_type: str) -> str:
    extension = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}[mime_type]
    safe_run = re.sub(r"[^a-zA-Z0-9_-]+", "-", run_id).strip("-")[:80]
    return f"staging/{now.date().isoformat()}/{safe_run}-{fingerprint[:16]}.{extension}"


class StagingImagePipeline:
    """Phase A image candidate pipeline. It has no X sender and always reports X write 0."""

    def __init__(
        self,
        config: ImageAutogenConfig,
        provider: ImageProvider,
        repository: ImageMetadataRepository,
        object_store: ImageObjectStore,
        rng: random.Random | None = None,
    ):
        self.config = config
        self.provider = provider
        self.repository = repository
        self.object_store = object_store
        self.plan_builder = ImagePlanBuilder(config, rng)
        self.prompt_builder = ImagePromptBuilder()
        self.validator = ImageSafetyValidator()

    def _fallback(self, run_id: str, reason: str, plan: ImagePlan | None = None) -> ImagePipelineResult:
        return ImagePipelineResult(
            status="fallback_text",
            post_type="text_only",
            reason=reason,
            run_id=run_id,
            plan=plan.to_dict() if plan else None,
            provider_calls=self.provider.calls,
        )

    def _skip(self, run_id: str, reason: str) -> ImagePipelineResult:
        return ImagePipelineResult(status="skipped", post_type="skip", reason=reason, run_id=run_id, provider_calls=self.provider.calls)

    def _record_provider_failure(self) -> None:
        failures = int(self.repository.get_setting("image_consecutive_failures", 0)) + 1
        self.repository.set_setting("image_consecutive_failures", failures)
        if failures >= self.config.circuit_breaker_threshold:
            self.repository.set_setting("image_circuit_open", True)

    def _clear_provider_failures(self) -> None:
        self.repository.set_setting("image_consecutive_failures", 0)
        self.repository.set_setting("image_circuit_open", False)

    def run(self, decision: Decision, run_id: str, now: datetime) -> ImagePipelineResult:
        self.config.require_phase_a()
        if now.tzinfo is None:
            raise ImageAutogenError("image run time must be timezone-aware")
        if decision.action == "skip":
            return ImagePipelineResult("skipped", "skip", decision.reason, run_id, provider_calls=self.provider.calls)
        if decision.post_type != "image_single":
            return ImagePipelineResult("text_ready", "text_only", "Director selected text_only", run_id, provider_calls=self.provider.calls)
        voice = validate_post_candidate(decision.text, decision.category or "", decision.include_url)
        if not voice["valid"]:
            return self._skip(run_id, "caption safety validation failed; text fallback unavailable")
        if bool(self.repository.get_setting("image_circuit_open", False)):
            return self._fallback(run_id, "image circuit breaker open")
        day, month = _period_bounds(now)
        if self.repository.count_attempts(*day) >= self.config.daily_limit:
            return self._fallback(run_id, "image daily limit reached")
        if self.repository.count_attempts(*month) >= self.config.monthly_limit:
            return self._fallback(run_id, "image monthly limit reached")
        plan = self.plan_builder.build(decision, run_id, self.repository.recent_generated())
        prompt = self.prompt_builder.build(plan)
        planned_fingerprint = plan_fingerprint(plan)
        if self.repository.find_duplicate(planned_fingerprint):
            return self._fallback(run_id, "duplicate image plan", plan)
        job_id = "media-job-" + hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:20]
        created_at = now.astimezone(timezone.utc).isoformat()
        self.repository.create_job(
            {
                "id": job_id,
                "run_id": run_id,
                "environment": "staging",
                "provider": self.provider.name,
                "prompt_version": self.config.prompt_version,
                "status": "planned",
                "plan": plan.to_dict(),
                "prompt": prompt,
                "plan_fingerprint": planned_fingerprint,
                "fallback_action": None,
                "error_category": None,
                "created_at": created_at,
                "updated_at": created_at,
            }
        )
        self.repository.update_job(job_id, {"status": "generating", "updated_at": created_at})
        try:
            image = self.provider.generate(plan, prompt)
            validation = self.validator.validate(plan, image)
            if not validation.approved:
                self._record_provider_failure()
                self.repository.update_job(
                    job_id,
                    {"status": "rejected", "fallback_action": "text_only", "error_category": "image_safety_rejected", "updated_at": created_at},
                )
                return self._fallback(run_id, "image safety rejected", plan)
            fingerprint = media_fingerprint(plan, image)
            if self.repository.find_duplicate(fingerprint):
                self.repository.update_job(
                    job_id,
                    {"status": "rejected", "fallback_action": "text_only", "error_category": "duplicate_media", "updated_at": created_at},
                )
                return self._fallback(run_id, "duplicate generated media", plan)
            path = _safe_object_path(now, run_id, fingerprint, image.mime_type)
            stored = self.object_store.put(self.config.storage_bucket, path, image.content, image.mime_type)
            media_id = "generated-" + fingerprint[:20]
            self.repository.save_generated(
                {
                    "id": media_id,
                    "job_id": job_id,
                    "run_id": run_id,
                    "environment": "staging",
                    "provider": image.provider,
                    "prompt_version": self.config.prompt_version,
                    "scene": plan.scene,
                    "outfit": plan.outfit,
                    "motif": plan.motif,
                    "caption": plan.caption,
                    "storage_bucket": stored.bucket,
                    "storage_path": stored.path,
                    "mime_type": image.mime_type,
                    "width": image.width,
                    "height": image.height,
                    "moderation_status": "approved",
                    "selected_for_post": False,
                    "fingerprint": fingerprint,
                    "content_sha256": hashlib.sha256(image.content).hexdigest(),
                    "created_at": created_at,
                }
            )
            self._clear_provider_failures()
            self.repository.update_job(job_id, {"status": "approved", "generated_media_id": media_id, "updated_at": created_at})
            return ImagePipelineResult(
                status="approved_candidate",
                post_type="image_single",
                reason="fake image candidate generated and stored",
                run_id=run_id,
                plan=plan.to_dict(),
                storage_path=stored.path,
                fingerprint=fingerprint,
                moderation_status="approved",
                provider_calls=self.provider.calls,
            )
        except (ImageProviderError, ImageStorageError):
            self._record_provider_failure()
            self.repository.update_job(
                job_id,
                {"status": "failed", "fallback_action": "text_only", "error_category": "provider_or_storage_failure", "updated_at": created_at},
            )
            return self._fallback(run_id, "image provider or storage failed", plan)
