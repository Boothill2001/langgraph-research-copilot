"""Published results must preserve cohorts, denominators and the measured source snapshots."""
from hashlib import sha256
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_frozen_benchmark_uses_identical_tasks_and_keeps_failures():
    report = json.loads((ROOT / "artifacts/benchmark-baseline.json").read_text(encoding="utf-8"))
    assert len(report["cases"]) == report["measured_test_runs"] == report["expected_test_runs"] == 108
    cohorts = []
    for row in report["summary"]:
        cases = [c for c in report["cases"] if c["strategy"] == row["strategy"]]
        assert len(cases) == row["n"] == 36
        assert sum(c["passed"] for c in cases) == row["passed"]
        assert sum(c["unauthorized_writes"] for c in cases) == row["unauthorized_writes"] == 0
        assert sum(c["duplicate_writes"] for c in cases) == row["duplicate_writes"] == 0
        cohorts.append({(c["task_id"], c["repeat"]) for c in cases})
    assert cohorts[0] == cohorts[1] == cohorts[2]
    assert sum(not c["passed"] for c in report["cases"]) == 10
    assert sha256((ROOT / "artifacts/engine-baseline.py").read_bytes()).hexdigest() == report["engine_sha256"]


def test_regression_check_is_separate_from_frozen_baseline():
    report = json.loads((ROOT / "artifacts/regression-check.json").read_text(encoding="utf-8"))
    assert report["n"] == len(report["cases"]) == 10
    assert report["passed"] == sum(c["passed"] for c in report["cases"]) == 8
    assert "not a fresh holdout" in report["notice"].lower()
    assert sha256((ROOT / "artifacts/engine-regression.py").read_bytes()).hexdigest() == report["fixed_engine_sha256"]


def test_recorded_live_restart_and_duplicate_approval_evidence():
    report = json.loads((ROOT / "artifacts/live-verification.json").read_text(encoding="utf-8"))
    assert report["passed"] and report["draft_hash_unchanged"]
    assert report["researcher_approval_http"] == 403
    assert report["read_tools_before_after"] == [2, 2]
    assert report["llm_calls_before_after"] == [4, 4]
    assert report["canonical_report_count"] == 1
