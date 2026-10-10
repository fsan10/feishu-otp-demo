"""Optional official SDK event source. No public callback endpoint required."""

import json
import os
from typing import Callable

from .env import load_env_file


def build_handler(callback: Callable[[dict], None]):
    try:
        import lark_oapi as lark
    except ImportError:
        raise RuntimeError("install requirements-websocket.txt to use WebSocket") from None

    def on_message(data) -> None:
        # SDK verifies and decodes the WebSocket frame. Do not print this payload.
        payload = json.loads(lark.JSON.marshal(data))
        callback(payload)

    return (lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(on_message).build())


def run_websocket(callback: Callable[[dict], None]) -> None:
    load_env_file()
    handler = build_handler(callback)
    import lark_oapi as lark
    app_id, secret = os.getenv("FEISHU_APP_ID", ""), os.getenv("FEISHU_APP_SECRET", "")
    if not app_id or not secret:
        raise ValueError("FEISHU_APP_ID and FEISHU_APP_SECRET are required")
    client = lark.ws.Client(app_id, secret, event_handler=handler, log_level=lark.LogLevel.ERROR)
    client.start()
