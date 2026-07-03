from __future__ import annotations

import argparse
import json
import statistics
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib import error, request


def send(base_url: str, api_key: str, index: int) -> tuple[int, float]:
    payload = {
        "event_id": f"load-{uuid.uuid4()}",
        "event_type": "agent_run",
        "trace_id": f"load-trace-{index}",
        "payload": {
            "status": "completed",
            "latency_ms": index % 1000,
        },
    }

    req = request.Request(
        f"{base_url.rstrip('/')}/api/ingestion/events",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )

    started = time.perf_counter()

    try:
        with request.urlopen(req, timeout=15) as response:
            response.read()
            status = response.status
    except error.HTTPError as exc:
        status = exc.code
    except Exception:
        status = 0

    elapsed_ms = (time.perf_counter() - started) * 1000
    return status, elapsed_ms


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0

    ordered = sorted(values)
    position = int(round((len(ordered) - 1) * p))
    return ordered[position]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--requests", type=int, default=200)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--max-p95-ms", type=float, default=1000)
    args = parser.parse_args()

    started = time.perf_counter()
    results = []

    with ThreadPoolExecutor(
        max_workers=args.concurrency
    ) as executor:
        futures = [
            executor.submit(
                send,
                args.base_url,
                args.api_key,
                index,
            )
            for index in range(args.requests)
        ]

        for future in as_completed(futures):
            results.append(future.result())

    total_seconds = time.perf_counter() - started
    statuses = [status for status, _ in results]
    latencies = [latency for _, latency in results]
    successful = sum(1 for status in statuses if status == 200)
    p95 = percentile(latencies, 0.95)

    print(f"requests: {args.requests}")
    print(f"successful: {successful}")
    print(f"failed: {args.requests - successful}")
    print(f"throughput_rps: {args.requests / total_seconds:.2f}")
    print(f"latency_mean_ms: {statistics.mean(latencies):.2f}")
    print(f"latency_p95_ms: {p95:.2f}")
    print(f"latency_max_ms: {max(latencies):.2f}")

    if successful != args.requests:
        raise SystemExit("RESULT: FAIL — requests failed")

    if p95 > args.max_p95_ms:
        raise SystemExit(
            f"RESULT: FAIL — p95 {p95:.2f} ms exceeds "
            f"{args.max_p95_ms:.2f} ms"
        )

    print("RESULT: PASS")


if __name__ == "__main__":
    main()
