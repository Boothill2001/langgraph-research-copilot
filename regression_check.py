"""Re-evaluate only inspected baseline failures; never overwrite the frozen benchmark."""
import asyncio
from hashlib import sha256
import json

from benchmark import ARTIFACTS, one, public_trace, tasks
from copilot.store import Store


async def main():
    baseline = json.loads((ARTIFACTS / "benchmark-baseline.json").read_text(encoding="utf-8"))
    failed = [r for r in baseline["cases"] if not r["passed"]]
    suite = {t["id"]: t for t in tasks()}
    cache = {}
    store = Store()
    # one() checkpoints here; preserve the original private checkpoint separately before this script.
    sem = asyncio.Semaphore(3)
    await asyncio.gather(*(one(suite[r["task_id"]], r["strategy"], r["repeat"], store, cache, sem) for r in failed))
    report = {"notice": "Regression check on failures from an already inspected test suite. Not a fresh holdout; do not replace baseline scores.",
              "baseline_engine_sha256": baseline["engine_sha256"],
              "fixed_engine_sha256": sha256((ARTIFACTS.parent / "src/copilot/engine.py").read_bytes()).hexdigest(),
              "n": len(cache), "passed": sum(v["passed"] for v in cache.values()), "cases": public_trace(list(cache.values()))}
    (ARTIFACTS / "regression-check.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
