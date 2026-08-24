from __future__ import annotations

from pathlib import Path

import tweepy

from .config import Settings
from .models import PostCandidate, PostResult


def send_to_x(candidate: PostCandidate, settings: Settings) -> PostResult:
    """The only V2 function allowed to perform an X write."""
    if not settings.x_configured:
        return PostResult(False, error="X credentials are incomplete")

    media_ids = None
    try:
        if candidate.media_path:
            auth = tweepy.OAuth1UserHandler(
                settings.api_key,
                settings.api_secret,
                settings.access_token,
                settings.access_token_secret,
            )
            api = tweepy.API(auth)
            media = api.media_upload(filename=str(Path(candidate.media_path)))
            media_ids = [media.media_id]

        client = tweepy.Client(
            consumer_key=settings.api_key,
            consumer_secret=settings.api_secret,
            access_token=settings.access_token,
            access_token_secret=settings.access_token_secret,
        )
        response = client.create_tweet(text=candidate.text[:280], media_ids=media_ids)
        post_id = response.data.get("id") if response.data else None
        if not post_id:
            return PostResult(False, error="X returned no post id")
        return PostResult(True, post_id=str(post_id))
    except Exception as exc:
        return PostResult(False, error=f"{type(exc).__name__}: {exc}")
