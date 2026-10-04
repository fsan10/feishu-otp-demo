import argparse
import json
import sys
import time

from .config import load_route, load_settings
from .core import OtpBridge, normalize_event, normalize_history
from .demo import run_demo
from .feishu import FeishuClient, PollingSource


def metadata(message):
    if message is None:
        return {"valid": False}
    return {"message_id": message.message_id, "chat_id": message.chat_id,
            "sender_type": message.sender_type,
            "sender_ids": [{"id_type": s.id_type, "id": s.id} for s in message.sender_ids],
            "created_ms": message.created_ms, "has_visible_text": bool(message.text)}


def result_json(result, show_code=False):
    value = {"ok": True, "ticket_id": result.ticket_id, "route_id": result.route_id,
             "message_id": result.message_id, "created_ms": result.created_ms,
             "code_masked": "*" * len(result.code)}
    if show_code:
        value["code"] = result.code
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Feishu SMS-bot -> report-task verification-code demo")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("demo", help="run offline, using only synthetic SMS content")
    for name in ("inspect", "wait"):
        item = sub.add_parser(name)
        item.add_argument("--config", default="config.json")
        item.add_argument("--transport", choices=("poll", "ws"), default="poll")
        if name == "inspect":
            item.add_argument("--minutes", type=int, default=10)
        else:
            item.add_argument("--route", required=True)
            item.add_argument("--show-code", action="store_true", help="explicitly print code to stdout")
    args = parser.parse_args()
    try:
        if args.command == "demo":
            print(json.dumps(run_demo(), ensure_ascii=False))
            return 0
        settings = load_settings(args.config)
        if args.command == "inspect":
            if args.transport == "poll":
                if args.minutes <= 0:
                    raise ValueError("minutes must be positive")
                now_ms = int(time.time() * 1000)
                items = FeishuClient.from_env().list_messages(
                    settings["chat_id"], now_ms - args.minutes * 60_000, now_ms,
                )
                for item in items:
                    print(json.dumps(metadata(normalize_history(item)), ensure_ascii=False))
                print(f"Inspected {len(items)} messages; SMS body and code were not printed.", file=sys.stderr)
            else:
                from .websocket import run_websocket

                def inspect_event(payload):
                    message = normalize_event(payload)
                    if message and message.chat_id == settings["chat_id"]:
                        print(json.dumps(metadata(message), ensure_ascii=False), flush=True)

                print("Waiting for live events. Wait for connection in Feishu console, then send a test SMS; Ctrl+C exits.", file=sys.stderr)
                run_websocket(inspect_event)
            return 0
        bridge = OtpBridge()
        ticket = bridge.arm(load_route(settings, args.route))
        if args.transport == "poll":
            client = FeishuClient.from_env()
            # Credential/permission preflight before asking for a live test SMS.
            now_ms = int(time.time() * 1000)
            client.list_messages(ticket.route.chat_id, now_ms - 60_000, now_ms)
            print("Waiting for a NEW SMS. Trigger a test SMS only after this line.", file=sys.stderr)
            result = PollingSource(client, bridge, interval=float(settings.get("poll_interval_seconds", 3))).wait(ticket)
            print(json.dumps(result_json(result, args.show_code), ensure_ascii=False))
        else:
            import threading
            from .websocket import run_websocket

            def callback(payload):
                bridge.feed_event(payload)

            def task():
                try:
                    result = bridge.wait(ticket)
                    print(json.dumps(result_json(result, args.show_code), ensure_ascii=False), flush=True)
                except (TimeoutError, RuntimeError) as error:
                    print(str(error), file=sys.stderr, flush=True)

            print("Single-task WS test. Wait for connection in Feishu console, then trigger a NEW SMS. Ctrl+C exits.", file=sys.stderr)
            threading.Thread(target=task, daemon=True).start()
            run_websocket(callback)
        return 0
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, KeyError, RuntimeError, TimeoutError) as error:
        # Never dump raw Feishu response payloads, SMS body or secrets.
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
