"""Run inside the existing daily-report backend; replace only the SMS input step."""

from otp_bridge import FeishuClient, OtpBridge, PollingSource
from otp_bridge.config import load_route, load_settings


def download_report(trigger_sms, submit_code, route_id="douyin_order_otp", *, task_id=None):
    """Callbacks are your existing platform code, e.g. Playwright or requests."""
    settings = load_settings("config.json")
    route = load_route(settings, route_id, task_id=task_id)
    bridge = OtpBridge()  # Production: inject the process-wide singleton instead.
    client = FeishuClient.from_env()
    # Preflight must happen before the platform side effect, not after sending SMS.
    import time
    now_ms = int(time.time() * 1000)
    client.list_messages(route.chat_id, now_ms - 60_000, now_ms)
    source = PollingSource(client, bridge, interval=settings.get("poll_interval_seconds", 3))
    ticket = bridge.arm(route)  # Register FIRST; clicking can send SMS immediately.
    try:
        trigger_sms()
        result = source.wait(ticket)
        return submit_code(result.code)  # Pass directly to existing code; never to an LLM.
    finally:
        bridge.cancel(ticket)


# Existing synchronous Playwright flow:
# download_report(
#     trigger_sms=lambda: send_sms_button.click(),
#     submit_code=lambda code: verification_input.fill(code),
# )
# Keep your existing "confirm/export/download" code after this call.
# For async Playwright, do NOT use synchronous lambdas here; see AI_INTEGRATION.md.
