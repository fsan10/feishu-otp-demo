"""Transport-independent matching. No credentials, network, database or LLM here."""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable


DEFAULT_OTP_REGEX = (
    r"(?:验证码|校验码|动态码|verification\s*code|\bOTP\b)"
    r"\s*(?:是|为|[:：])?\s*(?P<code>[0-9]{4,8})(?![0-9])"
)


@dataclass(frozen=True)
class Sender:
    id_type: str
    id: str


@dataclass(frozen=True)
class Route:
    route_id: str
    chat_id: str
    trusted_senders: tuple[Sender, ...]
    required_keywords: tuple[str, ...]
    otp_regex: str = DEFAULT_OTP_REGEX
    max_age_seconds: float = 120
    timeout_seconds: float = 120

    def __post_init__(self) -> None:
        if not self.route_id or not self.chat_id or not self.trusted_senders:
            raise ValueError("route_id, chat_id and trusted_senders are required")
        if any(not s.id_type or not s.id for s in self.trusted_senders):
            raise ValueError("trusted sender must include id_type and id")
        if not self.required_keywords or any(not k.strip() for k in self.required_keywords):
            raise ValueError("at least one non-empty routing keyword is required")
        if self.max_age_seconds <= 0 or self.timeout_seconds <= 0:
            raise ValueError("age and timeout must be positive")
        regex = re.compile(self.otp_regex, re.IGNORECASE)
        if "code" not in regex.groupindex:
            raise ValueError("otp_regex must contain a named (?P<code>...) group")


@dataclass(frozen=True)
class Message:
    message_id: str
    chat_id: str
    sender_type: str
    sender_ids: tuple[Sender, ...]
    created_ms: int
    text: str = field(repr=False)


@dataclass(frozen=True)
class OtpResult:
    code: str = field(repr=False)
    ticket_id: str
    route_id: str
    message_id: str
    created_ms: int


@dataclass
class Ticket:
    ticket_id: str
    route: Route
    armed_ms: int
    deadline: float
    result: OtpResult | None = field(default=None, repr=False)
    cancelled: bool = False
    claimed: bool = False


def visible_text(message_type: str, content: Any) -> str:
    """Extract visible text only; never collect numeric IDs, image keys or URLs."""
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except (ValueError, TypeError):
            return ""
    if not isinstance(content, dict):
        return ""
    if message_type == "text":
        value = content.get("text")
        return value if isinstance(value, str) else ""
    if message_type not in {"post", "interactive"}:
        return ""
    parts: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, list):
            for child in value:
                visit(child)
        elif isinstance(value, dict):
            tag = value.get("tag")
            if tag in {"at", "img", "image", "button", "select_static", "input"}:
                return
            for key, child in value.items():
                if key in {"text", "title"} and isinstance(child, str):
                    parts.append(child)
                elif key == "content" and isinstance(child, str) and tag in {
                    "markdown", "lark_md", "plain_text", "text",
                }:
                    parts.append(child)
                elif isinstance(child, (dict, list)):
                    visit(child)

    visit(content)
    return "\n".join(parts)


def _message(raw: dict, sender: dict, sender_ids: tuple[Sender, ...]) -> Message | None:
    try:
        if raw.get("deleted") or raw.get("updated"):
            return None
        if raw.get("chat_type", "group") != "group":
            return None
        created_ms = int(raw["create_time"])
        if created_ms <= 0 or not raw["message_id"] or not raw["chat_id"]:
            return None
        message_type = raw.get("message_type", raw.get("msg_type", ""))
        content = raw.get("content", raw.get("body", {}).get("content", ""))
        return Message(
            str(raw["message_id"]), str(raw["chat_id"]),
            str(sender.get("sender_type", "unknown")), sender_ids, created_ms,
            visible_text(message_type, content),
        )
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def normalize_history(item: dict) -> Message | None:
    """History sender_type=app, sender.id_type=app_id (not an event open_id)."""
    if not isinstance(item, dict):
        return None
    sender = item.get("sender") or {}
    if not isinstance(sender, dict):
        return None
    ids = (Sender(str(sender.get("id_type", "")), str(sender.get("id", ""))),)
    return _message(item, sender, ids)


def normalize_event(payload: dict) -> Message | None:
    """Official im.message.receive_v1 event; sender_type is user or bot."""
    if not isinstance(payload, dict):
        return None
    header = payload.get("header") or {}
    if not isinstance(header, dict) or header.get("event_type") != "im.message.receive_v1":
        return None
    event = payload.get("event") or {}
    if not isinstance(event, dict):
        return None
    sender, raw = event.get("sender") or {}, event.get("message") or {}
    if not isinstance(sender, dict) or not isinstance(raw, dict):
        return None
    ids = sender.get("sender_id") or {}
    if not isinstance(ids, dict):
        return None
    identities = tuple(Sender(k, str(v)) for k, v in ids.items() if v)
    return _message(raw, sender, identities)


def extract_code(text: str, regex: str) -> str | None:
    codes = {
        match.group("code")
        for match in re.finditer(regex, text, re.IGNORECASE)
        if match.group("code") and re.fullmatch(r"[0-9]{4,8}", match.group("code"))
    }
    return next(iter(codes)) if len(codes) == 1 else None


class OtpBridge:
    """In-process one-shot ticket broker. Every message can satisfy at most one task."""

    def __init__(self, wall_clock: Callable[[], float] = time.time,
                 monotonic: Callable[[], float] = time.monotonic) -> None:
        self._wall = wall_clock
        self._mono = monotonic
        self._condition = threading.Condition()
        self._tickets: dict[str, Ticket] = {}
        self._seen: dict[str, float] = {}

    def _prune(self) -> None:
        now = self._mono()
        self._seen = {key: expires for key, expires in self._seen.items() if expires > now}
        for key, ticket in list(self._tickets.items()):
            if ticket.deadline <= now or ticket.cancelled:
                del self._tickets[key]

    def arm(self, route: Route) -> Ticket:
        """Call before clicking 'send SMS'; keep one active ticket per route."""
        with self._condition:
            self._prune()
            if any(t.route.route_id == route.route_id for t in self._tickets.values()):
                raise RuntimeError("this route already has an active ticket; serialize its tasks")
            ticket = Ticket(uuid.uuid4().hex, route, int(self._wall() * 1000),
                            self._mono() + route.timeout_seconds)
            self._tickets[ticket.ticket_id] = ticket
            return ticket

    def ingest(self, message: Message | None) -> str:
        """Return a non-sensitive decision label; code stays in result memory."""
        if message is None:
            return "invalid_message"
        with self._condition:
            self._prune()
            if message.message_id in self._seen:
                return "duplicate"
            if message.sender_type not in {"app", "bot"}:
                return "not_bot"
            candidates: list[tuple[Ticket, str]] = []
            now_ms = int(self._wall() * 1000)
            for ticket in self._tickets.values():
                route = ticket.route
                if ticket.result or ticket.cancelled:
                    continue
                if message.chat_id != route.chat_id:
                    continue
                if not set(route.trusted_senders).intersection(message.sender_ids):
                    continue
                if message.created_ms < ticket.armed_ms or message.created_ms > now_ms:
                    continue
                if now_ms - message.created_ms > route.max_age_seconds * 1000:
                    continue
                if not all(keyword in message.text for keyword in route.required_keywords):
                    continue
                code = extract_code(message.text, route.otp_regex)
                if code is not None:
                    candidates.append((ticket, code))
            # Even unclaimed bot messages are observed once, not recycled for later tickets.
            self._seen[message.message_id] = self._mono() + 600
            if len(candidates) > 1:
                return "ambiguous_route"
            if not candidates:
                return "no_match"
            ticket, code = candidates[0]
            ticket.result = OtpResult(code, ticket.ticket_id, ticket.route.route_id,
                                      message.message_id, message.created_ms)
            self._condition.notify_all()
            return "matched"

    def feed_event(self, payload: dict) -> str:
        return self.ingest(normalize_event(payload))

    def feed_history(self, item: dict) -> str:
        return self.ingest(normalize_history(item))

    def claim(self, ticket: Ticket) -> OtpResult | None:
        with self._condition:
            if ticket.claimed:
                raise RuntimeError("ticket has already been consumed")
            if ticket.cancelled:
                raise RuntimeError("ticket was cancelled")
            if self._mono() >= ticket.deadline:
                self.cancel(ticket)
                raise TimeoutError("SMS verification code wait timed out")
            if ticket.result is None:
                return None
            ticket.claimed = True
            self._tickets.pop(ticket.ticket_id, None)
            result, ticket.result = ticket.result, None
            return result

    def wait(self, ticket: Ticket) -> OtpResult:
        """For an existing event receiver feeding this same bridge in another thread."""
        with self._condition:
            while True:
                result = self.claim(ticket)
                if result is not None:
                    return result
                self._condition.wait(timeout=max(0, ticket.deadline - self._mono()))

    def cancel(self, ticket: Ticket) -> None:
        with self._condition:
            ticket.cancelled = True
            self._tickets.pop(ticket.ticket_id, None)
            ticket.result = None
            self._condition.notify_all()
