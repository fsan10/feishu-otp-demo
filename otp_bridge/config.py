"""Non-secret JSON configuration. Secrets come from the process environment."""

import json
from pathlib import Path

from .core import DEFAULT_OTP_REGEX, Route, Sender


def load_settings(path: str) -> dict:
    with Path(path).open(encoding="utf-8") as stream:
        settings = json.load(stream)
    if not isinstance(settings, dict) or not settings.get("chat_id"):
        raise ValueError("config must contain chat_id")
    return settings


def load_route(settings: dict, route_id: str) -> Route:
    raw = settings.get("routes", {}).get(route_id)
    if not isinstance(raw, dict):
        raise ValueError("unknown route_id")
    senders = settings.get("trusted_senders", [])
    if not isinstance(senders, list):
        raise ValueError("trusted_senders must be a list")
    return Route(
        route_id=route_id, chat_id=settings["chat_id"],
        trusted_senders=tuple(Sender(item["id_type"], item["id"]) for item in senders),
        required_keywords=tuple(raw.get("required_keywords", [])),
        otp_regex=raw.get("otp_regex", DEFAULT_OTP_REGEX),
        max_age_seconds=float(raw.get("max_age_seconds", 120)),
        timeout_seconds=float(raw.get("timeout_seconds", 120)),
    )
