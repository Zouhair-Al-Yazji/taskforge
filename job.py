import json
import uuid

import db


def create_job(type: str, payload: str) -> str:
    """
    Validates input, assigns a UUID, and stores the new job.
    Returns the generated Job ID.
    """
    try:
        json.loads(payload)
    except json.JSONDecodeError:
        raise ValueError("Payload must be a valid JSON string.")

    job_id = str(uuid.uuid4())
    db.insert_job(job_id, type, payload)

    return job_id


class AmbiguousIdentifierError(Exception):
    def __init__(self, matches):
        self.matches = matches


def get_job(job_id: str):
    """Get the job based in its ID"""
    if len(job_id) < 4:
        raise ValueError("Short ID must be at least 4 characters long.")
    results = db.select_job_by_prefix(job_id)
    if not results:
        return None
    for row in results:
        if row["id"] == job_id:
            return row
    if len(results) > 1:
        raise AmbiguousIdentifierError(results)
    return results[0]


def list_jobs(status: str | None, limit: int = 10):
    return db.get_jobs(status, limit)


def count_jobs(status: str | None) -> int:
    return db.count_jobs(status)
