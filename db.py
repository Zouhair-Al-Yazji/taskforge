import contextlib
import sqlite3

DB_PATH = "taskforge.db"


@contextlib.contextmanager
def get_db():
    """Yields a database connection with WAL mode enabled."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db() -> None:
    """Initializes the database schema with strict state constraints."""
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                payload TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED')),
                worker_id TEXT NULL,
                error_message TEXT NULL,
                result TEXT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_status_created 
            ON jobs(status, created_at)
        """)


def insert_job(job_id: str, type: str, payload: str) -> None:
    """Persists a new job to the database."""
    with get_db() as conn:
        conn.execute(
            "INSERT INTO jobs (id, type, payload) VALUES (?, ?, ?)",
            (job_id, type, payload),
        )


def select_job_by_prefix(short_id: str):
    """Retrieves a single job by its ID. Returns None if not found."""
    pattern = f"{short_id}%"
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT id, type, status, created_at FROM jobs WHERE id LIKE ?", (pattern,)
        )
        return cursor.fetchall()


def get_next_pending_job():
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * from jobs WHERE status = 'PENDING' ORDER BY created_at ASC LIMIT 1"
        )
        return cursor.fetchone()


def claim_job(job_id: str, worker_id: str):
    with get_db() as conn:
        cursor = conn.execute(
            "UPDATE jobs SET status = 'PROCESSING', worker_id = ? WHERE id = ? AND status = 'PENDING'",
            (worker_id, job_id),
        )
        return cursor.rowcount


def fail_job(job_id: str, err_message: str):
    with get_db() as conn:
        conn.execute(
            "UPDATE jobs SET error_message = ?, status = 'FAILED' WHERE id = ?",
            (err_message, job_id),
        )


def complete_job(job_id: str, result: str):
    with get_db() as conn:
        conn.execute(
            "UPDATE jobs SET result = ?, status = 'COMPLETED' WHERE id = ?",
            (result, job_id),
        )
