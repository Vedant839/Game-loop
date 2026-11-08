`turso_serverless` 0.1.0 remote Python DB-API (per [current docs](https://docs.turso.tech/sdk/python/quickstart)): unique table `codex_spike_01d41113dfa2` created, seed inserted, and read back successfully.
Five simultaneous writes on separate connections all landed (5/5) in 2.744 seconds; no write failed.
Ten sequential `SELECT COUNT(*)` queries: mean 331.18 ms, median 329.04 ms, min 316.13 ms, max 355.27 ms from this machine.
The client API is synchronous; each `execute()` call blocks the calling thread while waiting for its remote result.
No spike operation failed; the test table and its rows remain in the throwaway Turso database for inspection.
