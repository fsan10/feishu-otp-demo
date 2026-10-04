"""Read-only Feishu API client and polling source, using only Python's stdlib."""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

from .core import OtpBridge, OtpResult, Ticket


class FeishuError(RuntimeError):
    def __init__(self, *, status: int = 0, code: int = 0, retryable: bool = False):
        self.status, self.code, self.retryable = status, code, retryable
        super().__init__(f"Feishu request failed (http={status}, code={code})")


def http_json(method: str, url: str, headers: dict, body: dict | None,
              timeout: float) -> tuple[int, dict]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, raw = error.code, error.read()
    except (urllib.error.URLError, TimeoutError, OSError):
        raise FeishuError(retryable=True) from None
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise FeishuError(status=status, retryable=(status == 429 or status >= 500)) from None
    if not isinstance(payload, dict):
        raise FeishuError(status=status)
    return status, payload


class FeishuClient:
    # Tokens and SMS content are intentionally never logged or included in exceptions.
    def __init__(self, app_id: str, app_secret: str, *, timeout: float = 8,
                 request: Callable = http_json, sleep: Callable = time.sleep,
                 monotonic: Callable = time.monotonic) -> None:
        if not app_id or not app_secret:
            raise ValueError("FEISHU_APP_ID and FEISHU_APP_SECRET are required")
        self._app_id, self._secret = app_id, app_secret
        self._request, self._sleep, self._mono = request, sleep, monotonic
        self.timeout = timeout
        self._token, self._expires = "", 0.0
        self._lock = threading.RLock()

    @classmethod
    def from_env(cls) -> FeishuClient:
        return cls(os.environ.get("FEISHU_APP_ID", ""), os.environ.get("FEISHU_APP_SECRET", ""))

    def _call(self, method: str, path: str, *, body: dict | None = None,
              params: dict | None = None, token: str = "", deadline: float | None = None) -> dict:
        url = "https://open.feishu.cn/open-apis" + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if token:
            headers["Authorization"] = "Bearer " + token
        for attempt in range(3):
            try:
                remaining = self.timeout if deadline is None else deadline - self._mono()
                if remaining <= 0:
                    raise TimeoutError("SMS verification code wait timed out")
                status, payload = self._request(method, url, headers, body, min(self.timeout, remaining))
                code = int(payload.get("code", -1))
                if status == 200 and code == 0:
                    return payload
                raise FeishuError(status=status, code=code,
                                  retryable=(status == 429 or status >= 500 or
                                             code in {99991400, 99991401}))
            except FeishuError as error:
                if not error.retryable or attempt == 2:
                    raise
                delay = min(2 ** attempt, 4)
                if deadline is not None:
                    delay = min(delay, max(0, deadline - self._mono()))
                self._sleep(delay)
        raise AssertionError("unreachable")

    def _tenant_token(self, deadline: float | None = None) -> str:
        with self._lock:
            if self._token and self._mono() < self._expires:
                return self._token
            payload = self._call("POST", "/auth/v3/tenant_access_token/internal", body={
                "app_id": self._app_id, "app_secret": self._secret,
            }, deadline=deadline)
            token = payload.get("tenant_access_token")
            if not isinstance(token, str) or not token:
                raise FeishuError()
            self._token = token
            self._expires = self._mono() + max(1, int(payload.get("expire", 7200)) - 60)
            return token

    def _get(self, path: str, params: dict, deadline: float | None = None) -> dict:
        try:
            return self._call("GET", path, params=params, token=self._tenant_token(deadline), deadline=deadline)
        except FeishuError as error:
            if error.code not in {99991661, 99991663, 99991664, 99991668}:
                raise
            with self._lock:
                self._token, self._expires = "", 0
            return self._call("GET", path, params=params, token=self._tenant_token(deadline), deadline=deadline)

    def list_messages(self, chat_id: str, start_ms: int, end_ms: int,
                      *, max_pages: int = 20, deadline: float | None = None) -> list[dict[str, Any]]:
        if not chat_id or start_ms < 0 or end_ms < start_ms or max_pages <= 0:
            raise ValueError("invalid history query window")
        params = {
            "container_id_type": "chat", "container_id": chat_id,
            # API filters are seconds; response create_time is milliseconds.
            "start_time": str(max(0, start_ms // 1000 - 1)),
            "end_time": str(end_ms // 1000 + 1),
            "sort_type": "ByCreateTimeAsc", "page_size": "50",
            "card_msg_content_type": "user_card_content",
        }
        items: list[dict] = []
        page_tokens: set[str] = set()
        for _ in range(max_pages):
            payload = self._get("/im/v1/messages", params, deadline)
            data = payload.get("data")
            if not isinstance(data, dict) or not isinstance(data.get("items", []), list):
                raise FeishuError()
            items.extend(data.get("items", []))
            if not data.get("has_more"):
                return items
            page_token = data.get("page_token")
            if not isinstance(page_token, str) or not page_token or page_token in page_tokens:
                raise FeishuError()
            page_tokens.add(page_token)
            params["page_token"] = page_token
        raise RuntimeError("history pagination limit reached; use a dedicated SMS group")


class PollingSource:
    def __init__(self, client: FeishuClient, bridge: OtpBridge, *, interval: float = 3,
                 sleep: Callable = time.sleep, wall_clock: Callable = time.time):
        if interval <= 0:
            raise ValueError("poll interval must be positive")
        self.client, self.bridge = client, bridge
        self.interval, self._sleep, self._wall = interval, sleep, wall_clock

    def wait(self, ticket: Ticket) -> OtpResult:
        """Poll only while a download task is waiting; no always-on history scan."""
        try:
            while True:
                result = self.bridge.claim(ticket)
                if result is not None:
                    return result
                try:
                    items = self.client.list_messages(ticket.route.chat_id, ticket.armed_ms,
                                                      int(self._wall() * 1000), deadline=ticket.deadline)
                    for item in items:
                        self.bridge.feed_history(item)
                except FeishuError as error:
                    if not error.retryable:
                        raise
                    # Transient failures remain within the same ticket window.
                result = self.bridge.claim(ticket)
                if result is not None:
                    return result
                self._sleep(self.interval)
        except BaseException:
            self.bridge.cancel(ticket)
            raise
