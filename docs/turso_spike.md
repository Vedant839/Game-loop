Turso's current Python quickstart recommends `turso_serverless` for remote Turso databases; it uses synchronous DB-API `connect`, `execute`, and `commit` calls ([official docs](https://docs.turso.tech/sdk/python/quickstart)).
The package documentation lookup worked, but this machine has no Turso CLI or database credentials, so I could not create a database or token.
The create-table, insert/read-back, and five simultaneous write checks were not run.
Ten-query latency was not measured because there was no reachable Turso database.
The documented API is synchronous; whether its calls block in practice was not measured here.
