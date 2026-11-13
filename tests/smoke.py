"""End-to-end checks against a running API and real workers (standard library only)."""

import argparse
import json
import time
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from app.compute import count_primes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8001")
    parser.add_argument("--tasks", type=int, default=30)
    parser.add_argument("--n", type=int, default=1_000_000)
    parser.add_argument("--min-workers", type=int, default=1)
    args = parser.parse_args()
    if args.tasks < 1 or not 1 <= args.min_workers <= args.tasks:
        parser.error("tasks must be positive and min-workers between 1 and tasks")
    expected = count_primes(args.n)

    def request(path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            args.url.rstrip("/") + path, data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.load(response)

    if request("/ready") != {"status": "ready"}:
        raise RuntimeError("API not ready")
    with ThreadPoolExecutor(max_workers=8) as pool:
        tasks = list(pool.map(lambda _: request("/tasks", {"n": args.n}), range(args.tasks)))
    pending = {task["id"] for task in tasks}
    completed = []
    deadline = time.monotonic() + 120
    while pending and time.monotonic() < deadline:
        for task_id in list(pending):
            task = request(f"/tasks/{task_id}")
            if task["status"] == "FAILED":
                raise RuntimeError(f"Task failed: {task}")
            if task["status"] == "COMPLETED":
                if task["result"] != expected:
                    raise RuntimeError(f"Incorrect result: {task}")
                completed.append(task)
                pending.remove(task_id)
        if pending:
            time.sleep(0.2)
    if pending:
        raise RuntimeError(f"Timed out waiting for tasks: {sorted(pending)}")
    distribution = Counter(task["worker_id"] for task in completed)
    if len(distribution) < args.min_workers:
        raise RuntimeError(f"Not enough distinct workers: {dict(distribution)}")
    print(json.dumps({"completed": len(completed), "expected_result": expected,
                      "workers": dict(distribution), "sample_task_id": completed[0]["id"]}, indent=2))


if __name__ == "__main__":
    main()
