import copy
import dataclasses
import json
import threading
import time
import unittest

from otp_bridge.core import (
    DEFAULT_OTP_REGEX, OtpBridge, Route, Sender, extract_code,
    normalize_event, normalize_history, visible_text,
)
from otp_bridge.demo import demo_route, event_fixture, history_fixture


class Clock:
    def __init__(self):
        self.wall = 1_800_000_000.0
        self.mono = 100.0

    def advance(self, seconds):
        self.wall += seconds
        self.mono += seconds


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.bridge = OtpBridge(lambda: self.clock.wall, lambda: self.clock.mono)
        self.route = demo_route()
        self.ticket = self.bridge.arm(self.route)
        self.clock.advance(.1)
        self.item = history_fixture(int(self.clock.wall * 1000))

    def test_valid_sms_is_available_to_report_backend_once(self):
        self.assertEqual(self.bridge.feed_history(self.item), "matched")
        result = self.bridge.wait(self.ticket)
        self.assertEqual(result.code, "123456")
        self.assertEqual(result.route_id, self.route.route_id)
        self.assertIsNone(self.ticket.result)
        self.assertNotIn(result.code, repr(result))
        with self.assertRaises(RuntimeError):
            self.bridge.claim(self.ticket)

    def test_history_and_event_same_message_id_are_deduplicated(self):
        self.assertEqual(self.bridge.feed_history(self.item), "matched")
        event = event_fixture(int(self.clock.wall * 1000))
        event["header"]["event_id"] = "different_event_id"
        self.assertEqual(self.bridge.feed_event(event), "duplicate")

    def test_bot_event_works_without_mentions(self):
        self.assertEqual(self.bridge.feed_event(event_fixture(int(self.clock.wall * 1000))), "matched")
        self.assertEqual(self.bridge.claim(self.ticket).code, "123456")

    def test_user_message_even_with_trusted_id_is_rejected(self):
        self.item["sender"]["sender_type"] = "user"
        self.assertEqual(self.bridge.feed_history(self.item), "not_bot")
        self.assertIsNone(self.bridge.claim(self.ticket))

    def test_other_bot_is_rejected(self):
        self.item["sender"]["id"] = "cli_untrusted"
        self.assertEqual(self.bridge.feed_history(self.item), "no_match")

    def test_wrong_group_is_rejected(self):
        self.item["chat_id"] = "oc_other_group"
        self.assertEqual(self.bridge.feed_history(self.item), "no_match")

    def test_sender_id_type_cannot_be_swapped(self):
        self.item["sender"]["id_type"] = "open_id"
        self.assertEqual(self.bridge.feed_history(self.item), "no_match")

    def test_receiver_header_app_id_is_not_sender_identity(self):
        event = event_fixture(int(self.clock.wall * 1000))
        event["header"]["app_id"] = "cli_demo_sms_forwarder"
        event["event"]["sender"]["sender_id"] = {"open_id": "ou_unknown"}
        self.assertEqual(self.bridge.feed_event(event), "no_match")

    def test_sms_before_arm_is_rejected_even_if_fresh(self):
        self.item["create_time"] = str(self.ticket.armed_ms - 1)
        self.assertEqual(self.bridge.feed_history(self.item), "no_match")

    def test_future_timestamp_is_rejected(self):
        self.item["create_time"] = str(int(self.clock.wall * 1000) + 1_000)
        self.assertEqual(self.bridge.feed_history(self.item), "no_match")

    def test_expired_sms_is_rejected(self):
        self.bridge.cancel(self.ticket)
        self.ticket = self.bridge.arm(dataclasses.replace(self.route, timeout_seconds=300))
        self.item["create_time"] = str(self.ticket.armed_ms)
        self.clock.advance(121)
        self.assertEqual(self.bridge.feed_history(self.item), "no_match")

    def test_all_routing_keywords_are_required(self):
        content = json.loads(self.item["body"]["content"])
        content["text"] = content["text"].replace("旗舰店 B", "旗舰店 C")
        self.item["body"]["content"] = json.dumps(content)
        self.assertEqual(self.bridge.feed_history(self.item), "no_match")

    def test_same_route_tasks_are_serialized(self):
        with self.assertRaisesRegex(RuntimeError, "serialize"):
            self.bridge.arm(self.route)

    def test_indistinguishable_routes_are_not_guessed(self):
        other = self.bridge.arm(dataclasses.replace(self.route, route_id="overlapping_route"))
        self.clock.advance(.1)
        self.item["create_time"] = str(int(self.clock.wall * 1000))
        self.assertEqual(self.bridge.feed_history(self.item), "ambiguous_route")
        self.assertIsNone(self.bridge.claim(self.ticket))
        self.assertIsNone(self.bridge.claim(other))

    def test_distinct_store_routes_receive_their_own_codes(self):
        other = self.bridge.arm(dataclasses.replace(self.route, route_id="shop_c",
                              required_keywords=("旗舰店 C", "138****9999", "报表导出")))
        self.clock.advance(.1)
        item_c = history_fixture(int(self.clock.wall * 1000), "om_c")
        item_c["body"]["content"] = item_c["body"]["content"].replace("旗舰店 B", "旗舰店 C").replace("8888", "9999").replace("123456", "654321")
        self.assertEqual(self.bridge.feed_history(item_c), "matched")
        self.assertIsNone(self.bridge.claim(self.ticket))
        self.assertEqual(self.bridge.claim(other).code, "654321")

    def test_cancellation_clears_the_pending_code(self):
        self.bridge.feed_history(self.item)
        self.bridge.cancel(self.ticket)
        self.assertIsNone(self.ticket.result)
        with self.assertRaises(RuntimeError):
            self.bridge.claim(self.ticket)
        self.bridge.arm(self.route)

    def test_deadline_prevents_late_consume(self):
        self.clock.advance(121)
        with self.assertRaises(TimeoutError):
            self.bridge.claim(self.ticket)
        self.assertEqual(self.bridge.feed_history(self.item), "no_match")

    def test_already_observed_message_is_not_recycled_for_a_new_task(self):
        self.bridge.feed_history(self.item)
        self.bridge.claim(self.ticket)
        self.clock.advance(1)
        self.bridge.arm(self.route)
        self.assertEqual(self.bridge.feed_history(self.item), "duplicate")

    def test_deleted_and_updated_messages_are_rejected(self):
        for flag in ("deleted", "updated"):
            raw = copy.deepcopy(self.item)
            raw[flag] = True
            self.assertIsNone(normalize_history(raw))

    def test_event_p2p_is_rejected(self):
        event = event_fixture(int(self.clock.wall * 1000))
        event["event"]["message"]["chat_type"] = "p2p"
        self.assertIsNone(normalize_event(event))

    def test_worker_is_woken_by_event_receiver(self):
        bridge = OtpBridge()
        ticket = bridge.arm(self.route)
        ready, results = threading.Event(), []

        def worker():
            ready.set()
            results.append(bridge.wait(ticket))

        thread = threading.Thread(target=worker)
        thread.start()
        self.assertTrue(ready.wait(1))
        self.assertEqual(bridge.feed_event(event_fixture(int(time.time() * 1000))), "matched")
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results[0].code, "123456")


class ParsingTests(unittest.TestCase):
    def test_sms_keyword_regex_ignores_phone_date_and_balance(self):
        text = "手机13812345678，2026-10-04，余额9999；验证码：654321，5分钟有效"
        self.assertEqual(extract_code(text, DEFAULT_OTP_REGEX), "654321")

    def test_regex_does_not_take_first_digits_of_phone_number(self):
        self.assertIsNone(extract_code("验证码：13812345678", DEFAULT_OTP_REGEX))

    def test_two_distinct_codes_are_ambiguous(self):
        self.assertIsNone(extract_code("验证码123456，旧验证码654321", DEFAULT_OTP_REGEX))

    def test_repeated_same_code_can_be_extracted(self):
        self.assertEqual(extract_code("验证码123456，验证码123456", DEFAULT_OTP_REGEX), "123456")

    def test_custom_regex_supports_code_before_keyword(self):
        self.assertEqual(extract_code("123456为您的验证码", r"(?P<code>[0-9]{6})为您的验证码"), "123456")

    def test_post_extracts_visible_text_and_ignores_at_user_id(self):
        post = {"zh_cn": {"title": "报表导出", "content": [[
            {"tag": "text", "text": "验证码：123456"},
            {"tag": "at", "user_id": "654321", "user_name": "机器人"},
        ]]}}
        text = visible_text("post", json.dumps(post))
        self.assertIn("123456", text)
        self.assertNotIn("654321", text)

    def test_cards_v1_and_v2(self):
        for card in (
            {"elements": [{"tag": "div", "text": {"tag": "lark_md", "content": "验证码：123456"}}]},
            {"schema": "2.0", "body": {"elements": [{"tag": "markdown", "content": "验证码：123456"}]}},
            {"text": "验证码：123456"},
        ):
            self.assertEqual(extract_code(visible_text("interactive", card), DEFAULT_OTP_REGEX), "123456")

    def test_images_and_malformed_json_are_not_parsed(self):
        self.assertEqual(visible_text("image", '{"image_key":"123456"}'), "")
        self.assertEqual(visible_text("text", "not-json-123456"), "")

    def test_invalid_event_and_history_shapes_are_ignored(self):
        for payload in (None, [], {}, {"header": []}, {"header": "bad"},
                        {"header": {"event_type": "im.message.receive_v1"}, "event": []}):
            self.assertIsNone(normalize_event(payload))
        for item in (None, [], {}, {"sender": "bad"}):
            self.assertIsNone(normalize_history(item))

    def test_route_rejects_missing_matching_constraints(self):
        for change in ({"trusted_senders": ()}, {"required_keywords": ()},
                       {"otp_regex": "[0-9]+"}, {"timeout_seconds": 0}):
            with self.assertRaises(ValueError):
                dataclasses.replace(demo_route(), **change)


if __name__ == "__main__":
    unittest.main()
