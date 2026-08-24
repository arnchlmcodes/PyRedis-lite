#!/usr/bin/env python3
"""
PyRedis-lite Benchmark Suite.

Fires N concurrent requests across configurable workloads (PING, SET, GET,
LPUSH, HSET, and MIXED) against a running PyRedis-lite instance, measures
throughput (requests/second) and latency percentiles (min, p50, p90, p95, p99, max),
and prints/saves structured results.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import datetime
import json
import os
import platform
import statistics
import sys
import threading
import time
from typing import Callable

import redis

# Add project root to sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from redis_clone.server import Server


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PyRedis-lite Benchmark Suite")
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Redis host to connect to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=6380,
        help="Redis port to connect to (default: 6380)",
    )
    parser.add_argument(
        "-n",
        "--requests",
        type=int,
        default=5000,
        help="Number of requests per workload test (default: 5000)",
    )
    parser.add_argument(
        "-c",
        "--concurrency",
        type=int,
        default=25,
        help="Number of concurrent client workers (default: 25)",
    )
    parser.add_argument(
        "--spawn-server",
        action="store_true",
        default=True,
        help="Automatically spawn PyRedis-lite Server in background if not reachable",
    )
    parser.add_argument(
        "--no-spawn",
        action="store_false",
        dest="spawn_server",
        help="Do not spawn an in-process server; expect an already running instance",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default=os.path.join(os.path.dirname(__file__), "results.json"),
        help="Path to save benchmark JSON results (default: bench/results.json)",
    )
    return parser.parse_args()


def check_connection(host: str, port: int) -> bool:
    """Test if a Redis-compatible server is reachable."""
    try:
        c = redis.Redis(host=host, port=port, socket_timeout=0.5)
        return bool(c.ping())
    except Exception:
        return False


def run_workload(
    name: str,
    num_requests: int,
    concurrency: int,
    task_fn: Callable[[redis.Redis, int], None],
    pool: redis.ConnectionPool,
) -> dict:
    """Execute a workload with concurrent workers and measure throughput and latency."""
    latencies: list[float] = [0.0] * num_requests

    def worker_task(idx: int) -> None:
        client = redis.Redis(connection_pool=pool)
        start = time.perf_counter()
        task_fn(client, idx)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        latencies[idx] = elapsed_ms

    print(f"\nRunning workload: {name.upper()} ({num_requests} requests, concurrency={concurrency})...")

    wall_start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        list(executor.map(worker_task, range(num_requests)))
    wall_duration = time.perf_counter() - wall_start

    sorted_lats = sorted(latencies)
    throughput = num_requests / wall_duration if wall_duration > 0 else 0.0

    p50 = sorted_lats[int(num_requests * 0.50)]
    p90 = sorted_lats[int(num_requests * 0.90)]
    p95 = sorted_lats[int(num_requests * 0.95)]
    p99 = sorted_lats[int(num_requests * 0.99)]
    min_lat = sorted_lats[0]
    max_lat = sorted_lats[-1]
    mean_lat = statistics.mean(sorted_lats)

    return {
        "workload": name,
        "requests": num_requests,
        "concurrency": concurrency,
        "duration_seconds": round(wall_duration, 4),
        "throughput_rps": round(throughput, 2),
        "latencies_ms": {
            "min": round(min_lat, 3),
            "p50": round(p50, 3),
            "p90": round(p90, 3),
            "p95": round(p95, 3),
            "p99": round(p99, 3),
            "max": round(max_lat, 3),
            "mean": round(mean_lat, 3),
        },
    }


def main() -> None:
    args = parse_args()
    spawned_server: Server | None = None
    server_thread: threading.Thread | None = None

    # Check if target host:port is alive or spawn local instance
    if not check_connection(args.host, args.port):
        if args.spawn_server:
            print(f"No instance found on {args.host}:{args.port}. Spawning PyRedis-lite Server...")
            spawned_server = Server(host=args.host, port=args.port)
            server_thread = threading.Thread(target=spawned_server.run, daemon=True)
            server_thread.start()
            # Wait for server to bind
            for _ in range(20):
                time.sleep(0.1)
                if check_connection(args.host, args.port):
                    print(f"Server successfully listening on {args.host}:{args.port}")
                    break
            else:
                print(f"Failed to connect to spawned server on {args.host}:{args.port}", file=sys.stderr)
                sys.exit(1)
        else:
            print(f"Cannot connect to Redis server on {args.host}:{args.port}", file=sys.stderr)
            sys.exit(1)
    else:
        print(f"Connected to existing Redis instance at {args.host}:{args.port}")

    pool = redis.ConnectionPool(
        host=args.host,
        port=args.port,
        max_connections=args.concurrency * 2,
        decode_responses=True,
    )

    # Define tasks
    def ping_task(c: redis.Redis, idx: int) -> None:
        c.ping()

    def set_task(c: redis.Redis, idx: int) -> None:
        c.set(f"bench:key:{idx % 1000}", f"value_{idx}")

    def get_task(c: redis.Redis, idx: int) -> None:
        c.get(f"bench:key:{idx % 1000}")

    def lpush_task(c: redis.Redis, idx: int) -> None:
        c.lpush(f"bench:list:{idx % 50}", f"item_{idx}")

    def hset_task(c: redis.Redis, idx: int) -> None:
        c.hset(f"bench:hash:{idx % 50}", f"field_{idx % 10}", f"val_{idx}")

    def mixed_task(c: redis.Redis, idx: int) -> None:
        op = idx % 10
        if op < 5:  # 50% GET
            c.get(f"bench:key:{idx % 1000}")
        elif op < 8:  # 30% SET
            c.set(f"bench:key:{idx % 1000}", f"mixed_val_{idx}")
        elif op == 8:  # 10% LPUSH
            c.lpush(f"bench:list:{idx % 50}", f"item_{idx}")
        else:  # 10% HSET
            c.hset(f"bench:hash:{idx % 50}", f"field_{idx % 10}", f"val_{idx}")

    # Seed some data for GET
    seed_client = redis.Redis(connection_pool=pool)
    for i in range(1000):
        seed_client.set(f"bench:key:{i}", f"seed_val_{i}")

    results = []

    workloads = [
        ("PING", ping_task),
        ("SET", set_task),
        ("GET", get_task),
        ("LPUSH", lpush_task),
        ("HSET", hset_task),
        ("MIXED", mixed_task),
    ]

    for name, fn in workloads:
        res = run_workload(name, args.requests, args.concurrency, fn, pool)
        results.append(res)
        lats = res["latencies_ms"]
        print(f"  Throughput:  {res['throughput_rps']:>9,.1f} req/s")
        print(f"  Latency p50: {lats['p50']:>9.2f} ms")
        print(f"  Latency p95: {lats['p95']:>9.2f} ms")
        print(f"  Latency p99: {lats['p99']:>9.2f} ms")
        print(f"  Latency max: {lats['max']:>9.2f} ms")

    # Clean up benchmark keys
    try:
        keys_to_del = [f"bench:key:{i}" for i in range(1000)]
        keys_to_del += [f"bench:list:{i}" for i in range(50)]
        keys_to_del += [f"bench:hash:{i}" for i in range(50)]
        if keys_to_del:
            seed_client.delete(*keys_to_del)
    except Exception:
        pass

    # Print Summary Table
    print("\n" + "=" * 78)
    print(f" {'PYREDIS-LITE BENCHMARK SUMMARY':^76} ")
    print("=" * 78)
    header = f"{'Workload':<10} {'Reqs':>7} {'Conc':>5} {'Req/sec':>12} {'p50 (ms)':>10} {'p95 (ms)':>10} {'p99 (ms)':>10}"
    print(header)
    print("-" * 78)
    for r in results:
        l = r["latencies_ms"]
        row = (
            f"{r['workload']:<10} "
            f"{r['requests']:>7} "
            f"{r['concurrency']:>5} "
            f"{r['throughput_rps']:>12,.1f} "
            f"{l['p50']:>10.2f} "
            f"{l['p95']:>10.2f} "
            f"{l['p99']:>10.2f}"
        )
        print(row)
    print("=" * 78)

    # Save JSON report
    report = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "python": platform.python_version(),
            "processor": platform.processor(),
        },
        "config": {
            "host": args.host,
            "port": args.port,
            "requests_per_test": args.requests,
            "concurrency": args.concurrency,
        },
        "results": results,
    }

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"\nResults successfully saved to: {args.output}")

    # Tear down spawned server if started
    if spawned_server:
        spawned_server.stop()
        if server_thread:
            server_thread.join(timeout=2)


if __name__ == "__main__":
    main()
