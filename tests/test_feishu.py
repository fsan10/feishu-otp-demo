import unittest
from urllib.parse import parse_qs, urlparse

from otp_bridge import FeishuClient, FeishuError, OtpBridge, PollingSource
from otp_bridge.demo import demo_route, history_fixture
from tests.test_core import Clock


AUTH = (200, {"code": 0, "tenant_access_token": "synthetic-token", "expire": 7200})


def page(items=None, **extra):
    return 200, {"code": 0, "data": {"items": items or [], "has_more": False, **extra}}


class Transport:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append((method, url, dict(headers), body, timeout))
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class ClientTests(unittest.TestCase):
    def client(self, responses):
        transport = Transport(responses)
        delays = []
        client = FeishuClient("synthetic-app", "synthetic-secret", request=transport, sleep=delays.append)
        return client, transport, delays

    def test_auth_caching_and_official_history_params(self):
        client, transport, _ = self.client([AUTH, page(), page()])
        client.list_messages("oc_test", 1_800_000_000_123, 1_800_000_001_789)
        client.list_messages("oc_test", 1_800_000_000_123, 1_800_000_001_789)
        self.assertEqual([c[0] for c in transport.calls], ["POST", "GET", "GET"])
        query = parse_qs(urlparse(transport.calls[1][1]).query)
        self.assertEqual(query["start_time"], ["1799999999"])
        self.assertEqual(query["end_time"], ["1800000002"])
        self.assertEqual(query["page_size"], ["50"])
        self.assertEqual(query["sort_type"], ["ByCreateTimeAsc"])
        self.assertEqual(query["card_msg_content_type"], ["user_card_content"])

    def test_history_follows_all_pages(self):
        client, transport, _ = self.client([AUTH, page([{"message_id": "one"}], has_more=True, page_token="next"), page([{"message_id": "two"}])])
        items = client.list_messages("oc_test", 0, 1000)
        self.assertEqual([x["message_id"] for x in items], ["one", "two"])
        self.assertEqual(parse_qs(urlparse(transport.calls[2][1]).query)["page_token"], ["next"])

    def test_missing_or_repeated_page_tokens_fail_loudly(self):
        for responses in (
            [AUTH, page(has_more=True)],
            [AUTH, page(has_more=True, page_token="same"), page(has_more=True, page_token="same")],
        ):
            client, _, _ = self.client(responses)
            with self.assertRaises(FeishuError):
                client.list_messages("oc_test", 0, 1000)

    def test_page_limit_is_not_silently_truncated(self):
        client, _, _ = self.client([AUTH, page(has_more=True, page_token="more")])
        with self.assertRaisesRegex(RuntimeError, "pagination"):
            client.list_messages("oc_test", 0, 1000, max_pages=1)

    def test_rate_limit_retries_and_succeeds(self):
        client, transport, delays = self.client([AUTH, (429, {"code": 99991400}), page()])
        client.list_messages("oc_test", 0, 1000)
        self.assertEqual(len(transport.calls), 3)
        self.assertEqual(delays, [1])

    def test_expired_token_is_refreshed_once(self):
        client, transport, _ = self.client([AUTH, (400, {"code": 99991668}), AUTH, page()])
        client.list_messages("oc_test", 0, 1000)
        self.assertEqual([c[0] for c in transport.calls], ["POST", "GET", "POST", "GET"])

    def test_permission_error_fails_without_retry_and_without_leaking_body(self):
        client, transport, _ = self.client([AUTH, (403, {"code": 99991672, "msg": "SMS123456 SECRET"})])
        with self.assertRaises(FeishuError) as result:
            client.list_messages("oc_test", 0, 1000)
        self.assertEqual(len(transport.calls), 2)
        self.assertFalse(result.exception.retryable)
        self.assertNotIn("123456", str(result.exception))
        self.assertNotIn("SECRET", str(result.exception))

    def test_request_timeout_is_capped_to_task_deadline(self):
        clock = Clock()
        transport = Transport([AUTH, page()])
        client = FeishuClient("app", "secret", request=transport, monotonic=lambda: clock.mono)
        client.list_messages("oc_test", 0, 1000, deadline=clock.mono + .25)
        self.assertEqual([c[4] for c in transport.calls], [.25, .25])

    def test_deadline_stops_before_new_api_requests(self):
        clock = Clock()
        transport = Transport([])
        client = FeishuClient("app", "secret", request=transport, monotonic=lambda: clock.mono)
        with self.assertRaises(TimeoutError):
            client.list_messages("oc_test", 0, 1000, deadline=clock.mono)
        self.assertEqual(transport.calls, [])


class PollingTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.bridge = OtpBridge(lambda: self.clock.wall, lambda: self.clock.mono)
        self.ticket = self.bridge.arm(demo_route())

    def test_sms_arrives_during_polling(self):
        clock = self.clock

        class Client:
            count = 0

            def list_messages(self, *args, **kwargs):
                self.count += 1
                return [] if self.count == 1 else [history_fixture(int(clock.wall * 1000))]

        client = Client()
        source = PollingSource(client, self.bridge, interval=1, sleep=self.clock.advance, wall_clock=lambda: self.clock.wall)
        self.assertEqual(source.wait(self.ticket).code, "123456")
        self.assertEqual(client.count, 2)

    def test_no_sms_times_out_and_releases_route(self):
        class Client:
            def list_messages(self, *args, **kwargs):
                return []

        source = PollingSource(Client(), self.bridge, interval=60, sleep=self.clock.advance, wall_clock=lambda: self.clock.wall)
        with self.assertRaises(TimeoutError):
            source.wait(self.ticket)
        self.assertTrue(self.ticket.cancelled)
        self.bridge.arm(demo_route())

    def test_permission_failure_cancels_ticket(self):
        class Client:
            def list_messages(self, *args, **kwargs):
                raise FeishuError(code=99991672)

        with self.assertRaises(FeishuError):
            PollingSource(Client(), self.bridge).wait(self.ticket)
        self.assertTrue(self.ticket.cancelled)

    def test_transient_api_error_can_recover_within_ticket_window(self):
        clock = self.clock

        class Client:
            count = 0

            def list_messages(self, *args, **kwargs):
                self.count += 1
                if self.count == 1:
                    raise FeishuError(status=503, retryable=True)
                return [history_fixture(int(clock.wall * 1000))]

        source = PollingSource(Client(), self.bridge, interval=1, sleep=self.clock.advance, wall_clock=lambda: self.clock.wall)
        self.assertEqual(source.wait(self.ticket).code, "123456")


if __name__ == "__main__":
    unittest.main()
