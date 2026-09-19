import contextlib
import logging
import sqlite3
import uuid
from pathlib import Path

log = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "taskforge.db"


@contextlib.contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    """
    Create tables if they don't exist. NOT a migration tool
    Schema changes require manual migration or deleting the DB.
    """
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS workers (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'ALIVE' CHECK(status IN ("ALIVE", "OFFLINE")),
                hostname TEXT NOT NULL,
                pid INTEGER NOT NULL,
                last_seen DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                payload TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ("PENDING", "PROCESSING", "FAILED", "COMPLETED")),
                worker_id TEXT NULL,
                fence_token INTEGER NOT NULL DEFAULT 0 CHECK (fence_token >= 0),
                attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
                max_attempts INTEGER NOT NULL DEFAULT 3 CHECK (max_attempts > 0),
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                claimed_at DATETIME NULL,
                completed_at DATETIME NULL,
                error_message TEXT NULL,
                result TEXT NULL,
                CHECK (
                    (status = 'PENDING' AND worker_id IS NULL AND claimed_at IS NULL)
                    OR
                    (status = 'PROCESSING' AND worker_id IS NOT NULL AND claimed_at IS NOT NULL)
                    OR
                    (status IN ('FAILED','COMPLETED') AND worker_id IS NULL)
                )
            );
            
            CREATE TABLE IF NOT EXISTS job_attempts (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                worker_id TEXT NOT NULL,
                attempt_number INTEGER NOT NULL CHECK(attempt_number > 0),
                fence_token INTEGER NOT NULL CHECK(fence_token >= 0),
                started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                finished_at DATETIME NULL,
                status TEXT NOT NULL CHECK(status IN ("IN_PROGRESS","SUCCESS","APP_ERROR","FENCED_OUT","STALE_TIMEOUT")),
                error_message TEXT NULL,
                FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
            );  
                        
            CREATE INDEX IF NOT EXISTS idx_jobs_poll ON jobs(status, created_at);
            CREATE INDEX IF NOT EXISTS idx_job_attempts_lookup ON job_attempts(job_id, fence_token);
            CREATE INDEX IF NOT EXISTS idx_jobs_processing ON jobs(status, worker_id) WHERE status = 'PROCESSING';
        """)


# ─────────────────────────────────────────────────────────────────────────────
# Jobs
# ─────────────────────────────────────────────────────────────────────────────


def insert_job(
    job_id: str | None, job_type: str, payload: str, max_attempts: int = 3
) -> str:
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    if not job_type or not job_type.strip():
        raise ValueError("job_type is required")

    job_id = job_id or str(uuid.uuid4())
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO jobs (id, type, payload, max_attempts) VALUES (?, ?, ?, ?)",
            (job_id, job_type, payload, max_attempts),
        )
        conn.execute("COMMIT")
    return job_id


def select_job_by_prefix(short_id: str):
    escaped = short_id.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"{escaped}%"
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM jobs WHERE id LIKE ? ESCAPE '\\' ORDER BY created_at DESC LIMIT 50",
            (pattern,),
        )
        return cursor.fetchall()


def claim_next_pending_job(worker_id: str):
    if not worker_id:
        raise ValueError("worker_id is required")

    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            """
            SELECT id, type, payload, fence_token, attempts, max_attempts 
            FROM jobs
            WHERE status = 'PENDING' AND attempts < max_attempts 
            ORDER BY created_at ASC 
            LIMIT 1 
            """
        )
        job = cursor.fetchone()

        if not job:
            conn.execute("ROLLBACK")
            return None

        new_fence_token = job["fence_token"] + 1
        new_attempts = job["attempts"] + 1

        cur = conn.execute(
            """
            UPDATE jobs 
            SET status = 'PROCESSING', 
                fence_token = ?, 
                attempts = ?, 
                worker_id = ?, 
                claimed_at = CURRENT_TIMESTAMP, 
                completed_at = NULL, 
                error_message = NULL
            WHERE id = ? AND status = 'PENDING' 
            """,
            (new_fence_token, new_attempts, worker_id, job["id"]),
        )

        if cur.rowcount == 0:
            conn.execute("ROLLBACK")
            return None

        conn.execute(
            """
            INSERT INTO job_attempts 
                (id, job_id, worker_id, fence_token, attempt_number, started_at, status) 
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, 'IN_PROGRESS')
            """,
            (str(uuid.uuid4()), job["id"], worker_id, new_fence_token, new_attempts),
        )
        conn.execute("COMMIT")
        return {
            "id": job["id"],
            "type": job["type"],
            "payload": job["payload"],
            "fence_token": new_fence_token,
            "attempts": new_attempts,
            "max_attempts": job["max_attempts"],
        }


def complete_job(job_id: str, worker_id: str, fence_token: int, result: str) -> str:
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            """
            UPDATE jobs 
            SET status = 'COMPLETED',
                completed_at = CURRENT_TIMESTAMP,
                worker_id = NULL, 
                result = ?
            WHERE id = ? AND status = 'PROCESSING' AND worker_id = ? AND fence_token = ? 
            """,
            (result, job_id, worker_id, fence_token),
        )

        if cursor.rowcount == 0:
            conn.execute("ROLLBACK")
            return "FENCED_OUT"

        conn.execute(
            """
            UPDATE job_attempts
            SET status = 'SUCCESS', finished_at = CURRENT_TIMESTAMP
            WHERE job_id = ? AND status = 'IN_PROGRESS' AND worker_id = ? AND fence_token = ? 
            """,
            (job_id, worker_id, fence_token),
        )

        conn.execute("COMMIT")
        return "COMPLETED"


def fail_job(job_id: str, worker_id: str, fence_token: int, err_message: str):
    """
    Record a job failure. Returns one of:
        - "FENCED_OUT" — worker no longer owns this job
        - "RETRY"      — job reset to PENDING for another attempt
        - "FAILED"     — attempts exhausted; job is terminal
    """
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")

        row = conn.execute(
            """
            SELECT attempts, max_attempts 
            FROM jobs
            WHERE id = ? AND fence_token = ? AND worker_id = ? AND status = 'PROCESSING' 
            """,
            (job_id, fence_token, worker_id),
        ).fetchone()

        if row is None:
            conn.execute("ROLLBACK")
            return "FENCED_OUT"

        conn.execute(
            """
            UPDATE job_attempts
            SET status = 'APP_ERROR', finished_at = CURRENT_TIMESTAMP, error_message = ?
            WHERE job_id = ? AND status = 'IN_PROGRESS' AND worker_id = ? AND fence_token = ? 
            """,
            (err_message, job_id, worker_id, fence_token),
        )

        if row["attempts"] >= row["max_attempts"]:
            conn.execute(
                """
                UPDATE jobs
                SET status = 'FAILED',
                    completed_at = CURRENT_TIMESTAMP,
                    worker_id = NULL, 
                    error_message = ?
                WHERE id = ? AND fence_token = ? 
                """,
                (err_message, job_id, fence_token),
            )
            conn.execute("COMMIT")
            return "FAILED"

        conn.execute(
            """
            UPDATE jobs
            SET status = 'PENDING',
                worker_id = NULL,
                claimed_at = NULL, 
                error_message = ?
            WHERE id = ? AND fence_token = ? 
                """,
            (err_message, job_id, fence_token),
        )

        conn.execute("COMMIT")
        return "RETRY"


def mark_attempt_fenced_out(job_id: str, worker_id: str, fence_token: int) -> None:
    try:
        with get_db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                UPDATE job_attempts
                SET status = 'FENCED_OUT', 
                    finished_at = CURRENT_TIMESTAMP,
                    error_message = 'Worker lost execution lease prior to completion ACK'
                WHERE job_id = ? AND status = 'IN_PROGRESS' AND worker_id = ? AND fence_token = ? 
                """,
                (job_id, worker_id, fence_token),
            )
            conn.execute("COMMIT")
    except sqlite3.Error:
        log.exception("Failed to mark attempt fenced out for job %s", job_id)


def recover_stale_jobs(heartbeat_threshold_seconds: int = 30) -> int:
    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT j.id, j.worker_id AS stale_worker_id, j.fence_token, j.attempts, j.max_attempts
            FROM jobs j LEFT JOIN workers w ON j.worker_id = w.id
            WHERE j.status = 'PROCESSING'
                AND (
                    w.id IS NULL
                    OR w.status = 'OFFLINE'
                    OR w.last_seen < datetime('now', '-' || ? || ' seconds')
                )
        """,
            (heartbeat_threshold_seconds,),
        )
        stale_jobs = cursor.fetchall()

    recovered = 0

    for j in stale_jobs:
        job_id = j["id"]
        old_token = j["fence_token"]
        attempts = j["attempts"]
        max_attempts = j["max_attempts"]

        with get_db() as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                check = conn.execute(
                    "SELECT status, fence_token FROM jobs WHERE id = ?", (job_id,)
                ).fetchone()

                if (
                    not check
                    or check["status"] != "PROCESSING"
                    or check["fence_token"] != old_token
                ):
                    conn.execute("ROLLBACK")
                    continue

                conn.execute(
                    """
                    UPDATE job_attempts
                    SET status = 'STALE_TIMEOUT',
                        finished_at = CURRENT_TIMESTAMP,
                        error_message = 'Worker missed heartbeat deadline.'
                    WHERE job_id = ? AND fence_token = ? AND status = 'IN_PROGRESS'
                """,
                    (job_id, old_token),
                )

                if attempts >= max_attempts:
                    conn.execute(
                        """
                        UPDATE jobs
                        SET status = 'FAILED',
                            completed_at = CURRENT_TIMESTAMP,
                            worker_id = NULL, 
                            error_message = 'MAX attempt budget exhausted upon recovery.'
                        WHERE id = ? AND fence_token = ? 
                        """,
                        (job_id, old_token),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE jobs
                        SET status = 'PENDING',
                            worker_id = NULL,
                            claimed_at = NULL
                        WHERE id = ? AND fence_token = ? 
                        """,
                        (job_id, old_token),
                    )

                conn.execute("COMMIT")
                recovered += 1
            except Exception:
                log.exception("Failed to recover stale job %s", job_id)
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass

    return recovered


def cleanup_exhausted_jobs() -> int:
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            """
            UPDATE jobs
            SET status = 'FAILED',
                completed_at = CURRENT_TIMESTAMP,
                error_message = 'MAX execution attempts exhausted'
            WHERE status = 'PENDING' AND attempts >= max_attempts 
            """,
        )
        count = cursor.rowcount
        conn.execute("COMMIT")
        return count


JOB_STATUSES = ("PENDING", "PROCESSING", "COMPLETED", "FAILED")


def get_jobs(status: str | None, limit: int = 10):
    if status is not None and status not in JOB_STATUSES:
        raise ValueError(f"Invalid status: {status!r}. Must be one of {JOB_STATUSES}")

    with get_db() as conn:
        if status:
            return conn.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            return conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()


def count_jobs(status: str | None) -> int:
    if status is not None and status not in JOB_STATUSES:
        raise ValueError(f"Invalid status: {status!r}. Must be one of {JOB_STATUSES}")

    with get_db() as conn:
        if status:
            return conn.execute(
                "SELECT COUNT(*) from jobs WHERE status = ?", (status,)
            ).fetchone()[0]

        return conn.execute(
            "SELECT COUNT(*) from jobs",
        ).fetchone()[0]


def get_job_attempts(job_id: str):
    with get_db() as conn:
        return conn.execute(
            """
            SELECT * FROM job_attempts
            WHERE job_id = ?
            ORDER BY attempt_number ASC
            """,
            (job_id,),
        ).fetchall()


# ─────────────────────────────────────────────────────────────────────────────
# Workers
# ─────────────────────────────────────────────────────────────────────────────


def register_worker(worker_id: str, hostname: str, pid: int) -> None:
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO workers (id, status, hostname, pid, started_at, last_seen) 
            VALUES (?, 'ALIVE', ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET
                status = 'ALIVE',
                last_seen = CURRENT_TIMESTAMP  
            """,
            (worker_id, hostname, pid),
        )
        conn.execute("COMMIT")


def update_worker_heartbeat(worker_id: str) -> None:
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE workers SET last_seen = CURRENT_TIMESTAMP,status = 'ALIVE' WHERE id=?",
            (worker_id,),
        )
        conn.execute("COMMIT")


def mark_worker_offline(worker_id: str) -> None:
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE workers SET status = 'OFFLINE', last_seen = CURRENT_TIMESTAMP WHERE id = ?",
            (worker_id,),
        )
        conn.execute("COMMIT")
