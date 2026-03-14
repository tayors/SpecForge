from __future__ import annotations

from pathlib import Path
import json
import unittest

from formal_check.traces import load_trace, normalize_apalache_trace, normalize_tlc_trace, normalize_z3_result


FIXTURES = Path(__file__).parent / "fixtures" / "traces"


class TraceTests(unittest.TestCase):
    def test_normalizes_apalache_trace(self) -> None:
        trace = normalize_apalache_trace(
            FIXTURES / "apalache.itf.json",
            spec_id="retry-lease",
            spec_kind="tla",
            check_id="at-most-one-holder",
            expr="AtMostOneHolder",
            severity="critical",
            code_paths=["src/main/java/example/LeaseService.java"],
            test_paths=["src/test/java/example/LeaseServiceTest.java"],
        )
        self.assertEqual(trace.payload["backend"], "apalache")
        self.assertEqual(trace.payload["action_path"], ["Claim", "Ack"])

    def test_normalizes_tlc_trace(self) -> None:
        trace = normalize_tlc_trace(
            FIXTURES / "tlc.json",
            spec_id="retry-lease",
            spec_kind="tla",
            check_id="acked-jobs-stay-out-of-queue",
            expr="AckedJobsStayOutOfQueue",
            severity="high",
            code_paths=["src/main/java/example/RetryWorker.java"],
            test_paths=["src/test/java/example/RetryWorkerTest.java"],
        )
        self.assertEqual(trace.payload["backend"], "tlc")
        self.assertEqual(trace.payload["steps"][1]["state"]["holder"], 0)

    def test_loads_trace_and_renders_markdown(self) -> None:
        trace = load_trace(FIXTURES / "z3.json")
        self.assertIn("quota-never-negative", trace.to_markdown())

    def test_normalizes_z3_result(self) -> None:
        payload = json.loads((FIXTURES / "z3.json").read_text(encoding="utf-8"))
        trace = normalize_z3_result(
            {
                "status": "sat",
                "summary": payload["summary"],
                "states": [{"index": 0, "values": {"quota": 3, "spend": 5, "next_quota": -2}}],
            },
            spec_id="quota-arithmetic",
            check_id="quota-never-negative",
            expr="quota-never-negative",
            severity="critical",
            objective="sat_counterexample",
            entry="formal/quota_model.py",
        )
        self.assertEqual(trace.payload["steps"][0]["state"]["next_quota"], -2)


if __name__ == "__main__":
    unittest.main()
