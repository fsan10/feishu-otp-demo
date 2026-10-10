"""Explicit live smoke test: send one SYNTHETIC message using your SMS-bot webhook.

This script sends a Feishu group message only when run directly.
It is separate from the read-only receiver and offline demo.
"""

import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from otp_bridge.env import load_env_file


TEST_TEXT = "OTP_BRIDGE_TEST\ndemo-account-8888\n验证码：123456（仅测试，非真实平台验证码）"


def make_payload(secret="", timestamp=None):
    payload = {"msg_type": "text", "content": {"text": TEST_TEXT}}
    if secret:
        timestamp = str(int(time.time())) if timestamp is None else str(timestamp)
        # Feishu custom bot signing: HMAC key is timestamp + newline + secret;
        # message is empty. This is not the usual 'secret as key' convention.
        key = (timestamp + "\n" + secret).encode("utf-8")
        payload.update(timestamp=timestamp,
                       sign=base64.b64encode(hmac.new(key, b"", hashlib.sha256).digest()).decode())
    return payload


def main():
    load_env_file()
    url = os.getenv("FEISHU_SMS_WEBHOOK_URL", "")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != "open.feishu.cn" or not parsed.path.startswith("/open-apis/bot/v2/hook/"):
        raise ValueError("set FEISHU_SMS_WEBHOOK_URL to the existing Feishu SMS custom-bot webhook")
    payload = make_payload(os.getenv("FEISHU_SMS_WEBHOOK_SECRET", ""))
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"}, method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            result = json.load(response)
    except Exception:
        # urllib errors include the URL, which contains the private webhook token.
        raise RuntimeError("test message could not be sent; check webhook, network and security settings") from None
    code = result.get("code", result.get("StatusCode", -1))
    if code != 0:
        raise RuntimeError(f"test message rejected (code={code}); check bot keyword/signature/IP settings")
    print("Synthetic SMS-bot message sent. Check the receiver's test_sms result.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
