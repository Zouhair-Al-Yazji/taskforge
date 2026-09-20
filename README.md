# Taskforge

A minimal, reliable background job queue written in pure Python + SQLite.
No Redis. No RabbitMQ. No Celery. Just a single-file database and a worker
loop that survives crashes, restarts, and slow jobs.

Taskforge is designed as a **command-line tool** you install once and use
across your OS — submit jobs from any shell, run workers in the background,
and inspect the queue from anywhere.

---

## Why

Most job queues require you to stand up external infrastructure. Taskforge
takes the opposite approach: everything lives in one SQLite file, and the
worker is a single Python process. It's ideal for:

- Local development pipelines
- Small self-hosted services
- Learning how job queues work under the hood
- Prototyping before committing to a "real" queue

Despite its simplicity, Taskforge handles the hard parts correctly:

- **Fencing tokens** — a crashed worker cannot overwrite the results of the
  worker that took over its job.
- **Heartbeats** — long-running jobs keep their lease alive as long as the
  worker is healthy, even during graceful shutdown.
- **Stale recovery** — jobs whose workers vanish are automatically requeued
  and retried up to a per-job attempt budget.
- **In-process write serialization** — SQLite-safe under concurrent threads.

---

## Requirements

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (recommended) or plain `pip`

No third-party runtime dependencies.

---

## Installation

### With `uv` (recommended)

Install Taskforge as an isolated CLI tool. `uv` creates its own virtualenv
and puts the `taskforge` command on your `PATH`:

```bash
git clone https://github.com/<you>/taskforge.git
cd taskforge
uv tool install .
```

Verify:

```bash
taskforge --help
```

Because the tool is installed in its own environment, it won't interfere
with any other Python project on your machine.

### Editable install (for development)

If you're hacking on Taskforge itself:

```bash
uv tool install --editable .
```

Edits to the source take effect immediately — no reinstall needed.

### With `pip`

```bash
git clone https://github.com/<you>/taskforge.git
cd taskforge
pip install .
```

If `taskforge` isn't found after install, add your local bin directory to
`PATH`:

```bash
# macOS / Linux (bash)
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

On `uv`, `uv tool update-shell` will do this for you automatically.

### Uninstall

```bash
uv tool uninstall taskforge       # if installed with uv
pip uninstall taskforge           # if installed with pip
```

---

## Quick Start

Open three terminals.

**Terminal 1 — start a worker:**

```bash
taskforge worker
```

**Terminal 2 — submit a job:**

```bash
taskforge submit resize_image '{"file": "photo.jpg", "width": 800}'
```

Output:

```
Job submitted successfully! ID: 3f8a1b2c
```

**Terminal 3 — inspect the queue:**

```bash
taskforge jobs
```

```
ID         TYPE               STATUS         AGE
───────────────────────────────────────────────────────
3f8a1b2c   resize_image       ⚙ PROCESSING    2s ago
───────────────────────────────────────────────────────
Showing 1 of 1 jobs
```

---

## Commands

### `taskforge submit <type> <payload>`

Create a new job. The payload must be valid JSON.

```bash
taskforge submit send_email '{"to": "user@example.com", "subject": "Hi"}'
```

| Argument  | Description                                          |
| --------- | ---------------------------------------------------- |
| `type`    | A short string naming the task (e.g. `resize_image`) |
| `payload` | A JSON string with the task's parameters             |

**Flags:**

- `-q`, `--quiet` — print only the job ID. Useful for scripting.

```bash
JOB_ID=$(taskforge submit resize_image '{"file":"x.jpg"}' -q)
echo "tracking $JOB_ID"
```

Exit codes: `0` on success, `1` on error.

### `taskforge status <job_id>`

Show full details for a single job. Accepts a full UUID or any unambiguous
prefix of at least 4 characters.

```bash
taskforge status 3f8a1b2c
```

```
--- Taskforge Job Status ---
ID:          3f8a1b2c
TYPE:        resize_image
STATUS:      PROCESSING
WORKER ID:   a1b2c3d4
ATTEMPTS:    1/3
FENCE TOKEN: 1
CREATED AT:  5s ago
CLAIMED AT:  3s ago
FINISHED AT: —
-----------------------------
```

### `taskforge jobs [-n N] [--status STATUS]`

List recent jobs. Defaults to the 10 most recent.

```bash
taskforge jobs
taskforge jobs -n 50
taskforge jobs --status FAILED
taskforge jobs -n 5 --status COMPLETED
```

Valid statuses: `PENDING`, `PROCESSING`, `COMPLETED`, `FAILED`.

### `taskforge attempts <job_id>`

Show the full attempt history for a job. Useful for debugging retries.

```bash
taskforge attempts 3f8a1b2c
```

```
--- Attempts for job 3f8a1b2c ---
#    WORKER     TOKEN        STATUS           STARTED          ERROR
──────────────────────────────────────────────────────────────────────
1    a1b2c3d4   1            STALE_TIMEOUT    2m ago           Worker missed heartbeat deadline.
2    e5f6g7h8   2            SUCCESS          30s ago
```

### `taskforge worker`

Start a background worker. Blocks until interrupted with `Ctrl+C`.

The worker:

- Registers itself in the database on startup
- Sends a heartbeat every 5 seconds
- Sweeps for stale jobs every 15 seconds
- Claims and executes jobs from the queue
- Gracefully finishes its current job on `SIGINT`/`SIGTERM`
- Marks itself offline on exit

Run multiple workers in parallel for higher throughput — the fencing
mechanism keeps them from stepping on each other.

```bash
# Terminal 1
taskforge worker

# Terminal 2 — a second worker for parallelism
taskforge worker
```

---

## How It Works

### Job Lifecycle

```
PENDING ──► PROCESSING ──► COMPLETED
              │
              │ (retryable failure)
              ▼
           PENDING ──► ...
              │
              │ (attempts exhausted)
              ▼
            FAILED
```

### Fencing Tokens

Every time a job is claimed, its `fence_token` is incremented. All
completion/failure writes must include the current token, or they are
rejected with `FENCED_OUT`.

This prevents this scenario:

1. Worker A claims job X (token = 1).
2. Worker A freezes (VM pause, network partition, `SIGSTOP`).
3. Sweeper declares A dead, resets job X.
4. Worker B claims job X (token = 2).
5. Worker A wakes up and calls `complete()`.
6. The DB rejects A's write because `1 ≠ 2`. No corruption.

### Heartbeats and Graceful Shutdown

The worker runs a **dedicated heartbeat thread** independent of the main
execution loop. When a shutdown signal arrives:

- The main loop stops claiming **new** jobs.
- The heartbeat thread **keeps running** until the current job finishes.
- Only after the in-flight job completes does the worker mark itself
  offline and exit.

This means a 45-second job isn't fenced out by a sweeper just because you
pressed `Ctrl+C` halfway through.

### Recovery

Any worker can act as a sweeper. Every 15 seconds it:

1. Finds jobs in `PROCESSING` whose worker is `OFFLINE` or hasn't
   heartbeated within `STALE_THRESHOLD` (30s).
2. Marks the corresponding attempt `STALE_TIMEOUT`.
3. Requeues the job (`PENDING`) if attempts remain, or marks it `FAILED`.

### Write Serialization

SQLite allows one writer at a time. Because the worker has two threads
(main + heartbeat) writing to the DB, `db.py` provides a `write_txn`
context manager that holds a process-wide lock around every
`BEGIN IMMEDIATE` transaction. Combined with SQLite's `busy_timeout`,
this eliminates `database is locked` errors from intra-process
contention.

---

## Configuration

Tunable constants live at the top of `taskforge/worker.py`:

| Constant             | Default | Purpose                                              |
| -------------------- | ------- | ---------------------------------------------------- |
| `HEARTBEAT_INTERVAL` | 5s      | How often the worker pulses the DB                   |
| `SWEEP_INTERVAL`     | 15s     | How often the worker recovers stale jobs             |
| `IDLE_POLL_INTERVAL` | 2s      | Sleep time when no jobs are available                |
| `STALE_THRESHOLD`    | 30s     | Grace period before a silent worker is declared dead |

Rule of thumb: `STALE_THRESHOLD > HEARTBEAT_INTERVAL * 2`.

---

## Project Layout

```
taskforge/                      ← repo root
├── taskforge/                  ← the installable package
│   ├── __init__.py
│   ├── cli.py                  # argument parsing + user-facing commands
│   ├── worker.py               # long-running worker loop + heartbeat thread
│   ├── job.py                  # thin API layer over db.py
│   ├── db.py                   # SQLite access, transactions, schema
│   └── utils.py                # formatting helpers
├── tests/                      # unittest suite
│   ├── __init__.py
│   ├── base.py                 # shared TaskforgeTestCase
│   ├── test_job.py
│   ├── test_worker_flow.py
│   ├── test_concurrency.py
│   └── test_cli.py
├── pyproject.toml
├── README.md
└── LICENSE
```

---

## Running Tests

The test suite uses Python's built-in `unittest` — no extra dependencies.

```bash
uv run python -m unittest discover -s tests -v
```

Or without `uv`:

```bash
python -m unittest discover -s tests -v
```

Tests cover:

- Job creation and payload validation
- Claim → complete / fail / retry flows
- Fencing token enforcement
- Stale job recovery
- Concurrent writers (heartbeat vs. main loop)
- Graceful shutdown behavior
- CLI command dispatch and exit codes

---

## Development

Clone and install in editable mode:

```bash
git clone https://github.com/<you>/taskforge.git
cd taskforge
uv tool install --editable .
```

Run a worker against your local DB:

```bash
taskforge worker
```

Make a change, then re-run tests:

```bash
uv run python -m unittest discover -s tests -v
```

---

## Roadmap

- [ ] Configurable retry backoff
- [ ] Job priorities
- [ ] Real task handlers (currently a stub `time.sleep(5)`)
- [ ] Web dashboard
- [ ] Postgres backend option

---

## License

MIT
