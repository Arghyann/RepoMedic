# buggy_shop

A small e-commerce backend (stdlib + sqlite3) used as the **patient** for RepoMedic-Bench.
It contains deliberately seeded, realistic backend bugs. Each benchmark case in
`../cases.json` is a GitHub-style issue plus a ground-truth test.

Do not "fix" this directory by hand — the eval harness copies it to a temp dir per case.
