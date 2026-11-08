"""Throwaway remote Turso connectivity, concurrency, and latency spike."""

from __future__ import annotations

import concurrent.futures
import os
import statistics
import time
import uuid
from pathlib import Path


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip("\"'")
    return values


def main() -> None:
    import turso_serverless

    values = read_env(Path(os.environ.get("TURSO_SPIKE_ENV", "turso_token.env")))
    url = values.get("url") or values.get("TURSO_DATABASE_URL")
    token = values.get("token") or values.get("TURSO_AUTH_TOKEN")
    if not url or not token:
        raise SystemExit("Expected url and token entries in the spike env file")

    table = f"codex_spike_{uuid.uuid4().hex[:12]}"
    connection = turso_serverless.connect(url, auth_token=token)
    try:
        connection.execute(
            f"CREATE TABLE {table} (id TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            f"INSERT INTO {table} (id, value) VALUES (?, ?)", ("seed", "readback-ok")
        )
        connection.commit()
        seed = connection.execute(
            f"SELECT value FROM {table} WHERE id = ?", ("seed",)
        ).fetchone()
        if not seed or seed[0] != "readback-ok":
            raise RuntimeError("seed row did not read back")

        def write_one(index: int) -> str:
            conn = turso_serverless.connect(url, auth_token=token)
            try:
                row_id = f"parallel-{index}"
                conn.execute(
                    f"INSERT INTO {table} (id, value) VALUES (?, ?)",
                    (row_id, f"write-{index}"),
                )
                conn.commit()
                return row_id
            finally:
                conn.close()

        started = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            written = list(pool.map(write_one, range(5)))
        concurrent_seconds = time.perf_counter() - started
        landed = connection.execute(
            f"SELECT COUNT(*) FROM {table} WHERE id LIKE 'parallel-%'"
        ).fetchone()[0]
        if landed != 5:
            raise RuntimeError(f"expected 5 concurrent writes, found {landed}")

        samples_ms: list[float] = []
        for _ in range(10):
            started = time.perf_counter()
            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            samples_ms.append((time.perf_counter() - started) * 1000)

        print(f"table={table}")
        print("create_insert_readback=passed")
        print(f"concurrent_writes={landed}/5 elapsed_seconds={concurrent_seconds:.3f}")
        print(
            "sequential_queries=10 "
            f"mean_ms={statistics.mean(samples_ms):.2f} "
            f"median_ms={statistics.median(samples_ms):.2f} "
            f"min_ms={min(samples_ms):.2f} max_ms={max(samples_ms):.2f}"
        )
        print("client_api=synchronous DB-API calls; execute blocks the calling thread")
        print(f"written_ids={','.join(written)}")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
