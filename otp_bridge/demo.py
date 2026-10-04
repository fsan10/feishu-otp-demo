"""Offline simulation: SMS bot -> Feishu message -> daily report handler -> form."""

import json
import time

from .core import OtpBridge, Route, Sender


DEMO_TEXT = (
    "平台：抖音\n账号：旗舰店 B\n手机号：138****8888\n"
    "【抖音电商】验证码：123456，用于报表导出，5分钟内有效。"
)


def history_fixture(created_ms: int, message_id: str = "om_demo_sms") -> dict:
    return {
        "message_id": message_id, "chat_id": "oc_demo_sms_group",
        "create_time": str(created_ms), "msg_type": "text", "deleted": False,
        "sender": {"id": "cli_demo_sms_forwarder", "id_type": "app_id", "sender_type": "app"},
        "body": {"content": json.dumps({"text": DEMO_TEXT}, ensure_ascii=False)},
    }


def event_fixture(created_ms: int, message_id: str = "om_demo_sms") -> dict:
    return {
        "schema": "2.0",
        "header": {"event_type": "im.message.receive_v1", "event_id": "ev_demo",
                   "app_id": "cli_demo_daily_report_receiver"},
        "event": {
            "sender": {"sender_type": "bot", "sender_id": {"open_id": "ou_demo_sms_forwarder"}},
            "message": {
                "message_id": message_id, "chat_id": "oc_demo_sms_group", "chat_type": "group",
                "create_time": str(created_ms), "message_type": "text",
                "content": json.dumps({"text": DEMO_TEXT}, ensure_ascii=False),
            },
        },
    }


def demo_route() -> Route:
    return Route(
        "douyin_shop_b", "oc_demo_sms_group",
        (Sender("app_id", "cli_demo_sms_forwarder"), Sender("open_id", "ou_demo_sms_forwarder")),
        ("抖音", "旗舰店 B", "138****8888", "报表导出"),
    )


def run_demo() -> dict:
    bridge = OtpBridge()
    ticket = bridge.arm(demo_route())
    print("1. 每日报表任务已登记等待窗口，然后模拟点击发送验证码。")
    now_ms = int(time.time() * 1000)
    history = history_fixture(now_ms)
    print("2. 模拟短信机器人发到飞书群，历史消息入口：", bridge.feed_history(history))
    print("3. 同一消息又通过长连接到达，去重结果：", bridge.feed_event(event_fixture(now_ms)))
    result = bridge.wait(ticket)
    # The fake form proves that the actual code is available to the backend callback.
    form = {"verification_code": result.code}
    assert form["verification_code"] == "123456"
    print("4. 每日报表后端已自动填入模拟表单：******；流程完成，没有手动转发。")
    return {"ok": True, "route_id": result.route_id, "message_id": result.message_id,
            "code_masked": "*" * len(result.code)}
