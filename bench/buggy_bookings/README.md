# buggy_bookings

A small event-ticket booking backend (stdlib + sqlite3). It is the **held-out patient** for
RepoMedic-Bench: it was written after the agent design was frozen and was never used to tune
the agent. Its cases are in `../heldout_cases.json`.

Do not "fix" this directory by hand. The eval harness copies it to a temp dir per case.
