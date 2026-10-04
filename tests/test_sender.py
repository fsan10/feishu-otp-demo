import base64
import hashlib
import hmac
import unittest

from examples.send_test_sms import TEST_TEXT, make_payload


class TestSenderTests(unittest.TestCase):
    def test_unsigned_payload_uses_test_marker_and_text_type(self):
        payload = make_payload()
        self.assertEqual(payload["msg_type"], "text")
        self.assertIn("OTP_BRIDGE_TEST", payload["content"]["text"])
        self.assertNotIn("sign", payload)

    def test_feishu_custom_bot_signature(self):
        payload = make_payload("synthetic-signing-secret", 1_800_000_000)
        expected = base64.b64encode(hmac.new(b"1800000000\nsynthetic-signing-secret", b"", hashlib.sha256).digest()).decode()
        self.assertEqual(payload["timestamp"], "1800000000")
        self.assertEqual(payload["sign"], expected)
        self.assertNotIn("synthetic-signing-secret", str(payload))


if __name__ == "__main__":
    unittest.main()
