import unittest
from unittest.mock import patch

from darial_sdk import DarialClient, sanitize_value


class SDKTests(unittest.TestCase):
    def test_sanitization(self):
        cleaned = sanitize_value({
            "prompt": "secret",
            "nested": {
                "authorization": "Bearer abc",
                "safe": 1,
            },
        })
        self.assertEqual(cleaned["prompt"], "[REDACTED]")
        self.assertEqual(
            cleaned["nested"]["authorization"],
            "[REDACTED]",
        )
        self.assertEqual(cleaned["nested"]["safe"], 1)

    def test_offline_queue(self):
        client = DarialClient(
            "http://127.0.0.1:9",
            "dr_test",
            max_retries=0,
        )
        client.track_event("agent_run", {"status": "completed"})
        result = client.flush()
        self.assertEqual(result["queued"], 1)
        self.assertEqual(result["queue_size"], 1)

    def test_context_manager_flushes(self):
        client = DarialClient(
            "http://localhost",
            "dr_test",
            batch_size=10,
        )
        with patch.object(
            client,
            "_post",
            return_value={
                "accepted": 3,
                "duplicate": 0,
            },
        ):
            with client.run(
                "demo",
                agent_name="demo-agent",
            ) as run:
                run.record_tool_call(tool_name="search")
        self.assertEqual(len(client._buffer), 0)


if __name__ == "__main__":
    unittest.main()
