import base64
import json
import tempfile
import unittest
import urllib.parse
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from incidentlab.evidence.collection import collect_git_metadata, collect_telemetry


def response_for(url: str, *, duplicate: bool = False) -> bytes:
    decoded = urllib.parse.unquote(url)
    if "/api/traces" in url:
        trace = {
            "traceID": "a" * 32,
            "spans": [
                {
                    "operationName": "db.pool.acquire",
                    "tags": [{"key": "db.pool.timeout", "value": True}],
                }
            ],
        }
        return json.dumps({"data": [trace, trace] if duplicate else [trace]}).encode()
    if "/loki/" in url:
        event = json.dumps({"event": "checkout_result", "request_id": "request-1"})
        values = [["1", event], ["1", event]] if duplicate else [["1", event]]
        return json.dumps({"data": {"result": [{"values": values}]}}).encode()
    value = "0" if "pool_available" in decoded else "1"
    result = {"metric": {}, "values": [["1", value], ["2", value]]}
    return json.dumps({"data": {"result": [result, result] if duplicate else [result]}}).encode()


class EvidenceCollectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.run_id = uuid4()
        self.start = datetime.now(UTC) - timedelta(seconds=5)
        self.end = datetime.now(UTC)

    def collect(self, fetch, attempts: int = 1):
        return collect_telemetry(
            self.run_id,
            self.start,
            self.end,
            ["request-1"],
            fetch=fetch,
            attempts=attempts,
            delay_seconds=0,
        )

    def test_empty_telemetry_is_explicit_gap_evidence(self) -> None:
        bundle = self.collect(lambda _: b'{"data":{"result":[]}}')
        self.assertEqual(len(bundle.items), 6)
        self.assertTrue(all(item.kind == "gap" for item in bundle.items))
        self.assertTrue(all(item.artifact_ref for item in bundle.items))

    def test_late_telemetry_is_polled_without_leaving_false_gaps(self) -> None:
        calls: dict[str, int] = {}

        def late(url: str) -> bytes:
            calls[url] = calls.get(url, 0) + 1
            if calls[url] == 1:
                if "/api/traces" in url:
                    return b'{"data":[]}'
                return b'{"data":{"result":[]}}'
            return response_for(url)

        bundle = self.collect(late, attempts=2)
        self.assertEqual(len(bundle.items), 6)
        self.assertFalse(any(item.kind == "gap" for item in bundle.items))

    def test_duplicate_telemetry_produces_one_normalized_item_per_query(self) -> None:
        bundle = self.collect(lambda url: response_for(url, duplicate=True))
        self.assertEqual(len(bundle.items), 6)
        self.assertEqual(len({item.id for item in bundle.items}), 6)

    def test_malformed_telemetry_is_saved_as_gap_not_raised(self) -> None:
        bundle = self.collect(lambda _: b"not-json")
        self.assertEqual(len(bundle.items), 6)
        self.assertTrue(all(item.kind == "gap" for item in bundle.items))
        self.assertTrue(all("malformed" in item.summary for item in bundle.items))
        for artifact in bundle.artifacts:
            envelope = json.loads(artifact.content)
            self.assertEqual(base64.b64decode(envelope["response_base64"]), b"not-json")

    def test_git_head_is_an_attributable_commit_fact(self) -> None:
        commit = "a" * 40
        with tempfile.TemporaryDirectory() as temporary:
            git_dir = Path(temporary)
            (git_dir / "refs/heads").mkdir(parents=True)
            (git_dir / "HEAD").write_text("ref: refs/heads/main\n")
            (git_dir / "refs/heads/main").write_text(commit + "\n")
            bundle = collect_git_metadata(self.run_id, commit, git_dir)
        self.assertEqual(bundle.items[0].kind, "commit")
        self.assertEqual(bundle.items[0].content_sha256, bundle.artifacts[0].content_sha256)


if __name__ == "__main__":
    unittest.main()
