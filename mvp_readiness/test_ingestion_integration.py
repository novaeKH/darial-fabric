from __future__ import annotations

import json
import os
import time
import unittest
import uuid
from datetime import datetime, timedelta
from urllib import error, request


BASE_URL = os.getenv("DARIAL_BASE_URL", "http://localhost:8000")
ADMIN_PRINCIPAL = os.getenv("DARIAL_ADMIN_PRINCIPAL", "")
PRODUCT_A = os.getenv("DARIAL_TEST_PRODUCT_A", "")
PRODUCT_B = os.getenv("DARIAL_TEST_PRODUCT_B", "")


def api(
    method: str,
    path: str,
    payload: dict | None = None,
    *,
    bearer: str | None = None,
    principal: str | None = None,
):
    headers = {"Content-Type": "application/json"}

    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"

    if principal:
        headers["X-Darial-Principal"] = principal

    body = (
        json.dumps(payload).encode("utf-8")
        if payload is not None
        else None
    )

    req = request.Request(
        f"{BASE_URL.rstrip('/')}{path}",
        data=body,
        method=method,
        headers=headers,
    )

    try:
        with request.urlopen(req, timeout=10) as response:
            text = response.read().decode("utf-8")
            return response.status, json.loads(text) if text else {}
    except error.HTTPError as exc:
        text = exc.read().decode("utf-8")
        try:
            body = json.loads(text)
        except json.JSONDecodeError:
            body = {"raw": text}
        return exc.code, body


class IngestionIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not ADMIN_PRINCIPAL:
            raise unittest.SkipTest(
                "DARIAL_ADMIN_PRINCIPAL is not set"
            )

        status, source = api(
            "POST",
            "/api/ingestion/sources",
            {
                "name": f"mvp-readiness-{uuid.uuid4()}",
                "source_type": "integration_test",
                "product_id": PRODUCT_A or None,
                "environment": "test",
            },
            principal=ADMIN_PRINCIPAL,
        )
        if status not in {200, 201}:
            raise RuntimeError(
                f"Failed to create source: {status} {source}"
            )

        cls.source_id = source["id"]

        status, key = api(
            "POST",
            f"/api/ingestion/sources/{cls.source_id}/keys",
            {
                "name": "integration",
                "allowed_event_types": [
                    "agent_run",
                    "llm_call",
                    "tool_call",
                    "business_outcome",
                ],
                "rate_limit_per_minute": 0,
            },
            principal=ADMIN_PRINCIPAL,
        )
        if status not in {200, 201}:
            raise RuntimeError(
                f"Failed to create key: {status} {key}"
            )

        cls.key_id = key["id"]
        cls.api_key = key["api_key"]

    def test_duplicate_event_id(self):
        event_id = f"duplicate-{uuid.uuid4()}"
        payload = {
            "event_id": event_id,
            "event_type": "agent_run",
            "product_id": PRODUCT_A or None,
            "trace_id": str(uuid.uuid4()),
            "payload": {"status": "completed"},
        }

        first_status, first = api(
            "POST",
            "/api/ingestion/events",
            payload,
            bearer=self.api_key,
        )
        second_status, second = api(
            "POST",
            "/api/ingestion/events",
            payload,
            bearer=self.api_key,
        )

        self.assertEqual(first_status, 200)
        self.assertEqual(first["accepted"], 1)
        self.assertEqual(second_status, 200)
        self.assertEqual(second["duplicate"], 1)

    def test_sanitization(self):
        event_id = f"sanitize-{uuid.uuid4()}"

        status, result = api(
            "POST",
            "/api/ingestion/events",
            {
                "event_id": event_id,
                "event_type": "agent_run",
                "product_id": PRODUCT_A or None,
                "trace_id": str(uuid.uuid4()),
                "payload": {
                    "prompt": "confidential",
                    "authorization": "Bearer secret",
                    "safe": "visible",
                },
            },
            bearer=self.api_key,
        )

        self.assertEqual(status, 200)
        self.assertEqual(result["accepted"], 1)

        status, events = api(
            "GET",
            f"/api/ingestion/events?source_id={self.source_id}&limit=20",
            principal=ADMIN_PRINCIPAL,
        )

        self.assertEqual(status, 200)
        row = next(
            item
            for item in events
            if item["event_id"] == event_id
        )

        payload_json = row["payload_json"]
        self.assertEqual(payload_json["prompt"], "[REDACTED]")
        self.assertEqual(
            payload_json["authorization"],
            "[REDACTED]",
        )
        self.assertEqual(payload_json["safe"], "visible")

    def test_product_spoofing_is_blocked(self):
        if not PRODUCT_A or not PRODUCT_B:
            self.skipTest(
                "DARIAL_TEST_PRODUCT_A/B are not set"
            )

        status, body = api(
            "POST",
            "/api/ingestion/events",
            {
                "event_id": str(uuid.uuid4()),
                "event_type": "agent_run",
                "product_id": PRODUCT_B,
                "trace_id": str(uuid.uuid4()),
                "payload": {"status": "completed"},
            },
            bearer=self.api_key,
        )

        self.assertEqual(status, 403)
        self.assertIn("another product", str(body))

    def test_disallowed_event_type(self):
        status, body = api(
            "POST",
            "/api/ingestion/events",
            {
                "event_id": str(uuid.uuid4()),
                "event_type": "raw_prompt",
                "product_id": PRODUCT_A or None,
                "payload": {},
            },
            bearer=self.api_key,
        )

        self.assertEqual(status, 403)
        self.assertIn("not allowed", str(body))

    def test_batch_contract(self):
        trace_id = str(uuid.uuid4())

        status, body = api(
            "POST",
            "/api/ingestion/events/batch",
            {
                "events": [
                    {
                        "event_id": str(uuid.uuid4()),
                        "event_type": "agent_run",
                        "product_id": PRODUCT_A or None,
                        "trace_id": trace_id,
                        "payload": {"status": "completed"},
                    },
                    {
                        "event_id": str(uuid.uuid4()),
                        "event_type": "tool_call",
                        "product_id": PRODUCT_A or None,
                        "trace_id": trace_id,
                        "payload": {
                            "tool_name": "search",
                            "status": "completed",
                        },
                    },
                ]
            },
            bearer=self.api_key,
        )

        self.assertEqual(status, 200)
        self.assertIn("accepted_count", body)
        self.assertIn("rejected_count", body)
        self.assertIn("request_id", body)

    def test_revoked_key(self):
        status, key = api(
            "POST",
            f"/api/ingestion/sources/{self.source_id}/keys",
            {
                "name": "revoked-test",
                "allowed_event_types": ["agent_run"],
            },
            principal=ADMIN_PRINCIPAL,
        )
        self.assertIn(status, {200, 201})

        status, _ = api(
            "PATCH",
            f"/api/ingestion/keys/{key['id']}/revoke",
            principal=ADMIN_PRINCIPAL,
        )
        self.assertEqual(status, 200)

        status, _ = api(
            "POST",
            "/api/ingestion/events",
            {
                "event_id": str(uuid.uuid4()),
                "event_type": "agent_run",
                "payload": {},
            },
            bearer=key["api_key"],
        )
        self.assertEqual(status, 401)

    def test_expired_key(self):
        expired_at = (
            datetime.utcnow() - timedelta(minutes=1)
        ).isoformat()

        status, key = api(
            "POST",
            f"/api/ingestion/sources/{self.source_id}/keys",
            {
                "name": "expired-test",
                "expires_at": expired_at,
                "allowed_event_types": ["agent_run"],
            },
            principal=ADMIN_PRINCIPAL,
        )
        self.assertIn(status, {200, 201})

        status, _ = api(
            "POST",
            "/api/ingestion/events",
            {
                "event_id": str(uuid.uuid4()),
                "event_type": "agent_run",
                "payload": {},
            },
            bearer=key["api_key"],
        )
        self.assertEqual(status, 401)


if __name__ == "__main__":
    unittest.main()
