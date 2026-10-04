"""Use when daily-report bot already owns a Feishu event receiver in this process."""

from otp_bridge import OtpBridge
from otp_bridge.config import load_route, load_settings


bridge = OtpBridge()  # MUST be shared by the receiver and the download worker.


def on_verified_feishu_event(payload: dict) -> str:
    """Called AFTER your SDK has verified/decoded a real platform event."""
    # Handle bot messages here, before any existing `sender_type != user` guard.
    decision = bridge.feed_event(payload)
    # Preserve your existing human @commands branch separately.
    return decision


def download_report_in_worker(trigger_sms, submit_code, route_id="douyin_shop_b"):
    route = load_route(load_settings("config.json"), route_id)
    ticket = bridge.arm(route)
    try:
        trigger_sms()
        result = bridge.wait(ticket)  # Run in a worker, not the SDK event callback.
        return submit_code(result.code)
    finally:
        bridge.cancel(ticket)


# Never call download_report_in_worker from inside the SDK message callback:
# the callback would block the same thread needed to receive the SMS.
# Never start a second long connection for the same app just to obtain OTPs;
# extend the receiver that your daily-report robot already uses.
