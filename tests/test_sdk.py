"""Optional offline compatibility test against the real official SDK package."""

import importlib.util
import json
import unittest

from otp_bridge.core import normalize_event
from otp_bridge.demo import event_fixture
from otp_bridge.websocket import build_handler


@unittest.skipUnless(importlib.util.find_spec("lark_oapi"), "optional lark-oapi SDK not installed")
class SdkTests(unittest.TestCase):
    def test_typed_official_event_round_trip_and_handler_construction(self):
        import lark_oapi as lark
        from lark_oapi.api.im.v1 import P2ImMessageReceiveV1

        payload = event_fixture(1_800_000_000_000)
        typed_event = P2ImMessageReceiveV1(payload)
        round_trip = json.loads(lark.JSON.marshal(typed_event))
        message = normalize_event(round_trip)
        self.assertIsNotNone(message)
        self.assertEqual(message.sender_type, "bot")
        self.assertEqual(message.sender_ids[0].id, "ou_demo_sms_forwarder")
        self.assertIsNotNone(build_handler(lambda payload: None))


if __name__ == "__main__":
    unittest.main()
