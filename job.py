import json

import db


class AmbiguousIdentifierError(Exception):
    def __init__(self, short_id: str, matches):
        self.short_id = short_id
        self.matches = matches
        super().__init__(f"Short ID '{short_id}' matches {len(matches)} jobs")


def init_system() -> None:
    db.init_db()


def create_job(job_type: str, payload: str, max_attempts: int = 3) -> str:
    try:
        json.loads(payload)
    except json.JSONDecodeError:
        raise ValueError("Payload must be a valid JSON string.")

    return db.insert_job(None, job_type, payload, max_attempts)


def get_job(job_id: str):
    if len(job_id) < 4:
        raise ValueError("Short ID must be at least 4 characters long.")

    results = db.select_job_by_prefix(job_id)
    if not results:
        return None

    # Exact match wins.
    exact = [r for r in results if r["id"] == job_id]
    if exact:
        return exact[0]

    if len(results) > 1:
        raise AmbiguousIdentifierError(job_id, results)

    return results[0]


def get_job_attempts(job_id: str):
    return db.get_job_attempts(job_id)


def list_jobs(status: str | None, limit: int = 10):
    return db.get_jobs(status, limit)


def count_jobs(status: str | None) -> int:
    return db.count_jobs(status)


# ── Worker-facing wrappers ───────────────────────────────────────────────────


def register_worker(worker_id: str, hostname: str, pid: int) -> None:
    db.register_worker(worker_id, hostname, pid)


def heartbeat(worker_id: str) -> None:
    db.update_worker_heartbeat(worker_id)


def mark_offline(worker_id: str) -> None:
    db.mark_worker_offline(worker_id)


def claim_next(worker_id: str):
    return db.claim_next_pending_job(worker_id)


def complete(job_id: str, worker_id: str, fence_token: int, result: str) -> str:
    return db.complete_job(job_id, worker_id, fence_token, result)


def fail(job_id: str, worker_id: str, fence_token: int, err_message: str) -> str:
    return db.fail_job(job_id, worker_id, fence_token, err_message)


def mark_fenced_out(job_id: str, worker_id: str, fence_token: int) -> None:
    db.mark_attempt_fenced_out(job_id, worker_id, fence_token)


def recover_stale(threshold_seconds: int = 30) -> int:
    return db.recover_stale_jobs(threshold_seconds)


def cleanup_exhausted() -> int:
    return db.cleanup_exhausted_jobs()
