import time
import uuid

import db


def execute_job(job, worker_id: str):
    short_job_id = job["id"][:8]
    short_worker_id = worker_id[:8]
    print(f"[{short_worker_id}] Processing job {short_job_id} ({job['type']})...")
    try:
        time.sleep(3)
        db.complete_job(job["id"], '{"result": "completed"}')
        print(f"[{short_worker_id}] Job {short_job_id} COMPLETED")
    except Exception as e:
        db.fail_job(job["id"], str(e))
        print(f"[{short_worker_id}] Job {short_job_id} FAILED: {e}")


def run_worker():
    worker_id = str(uuid.uuid4())
    print(f"Worker {worker_id[:8]} started. Polling for jobs...")
    while True:
        job = db.get_next_pending_job()
        if not job:
            time.sleep(2)
            continue
        rows = db.claim_job(job["id"], worker_id)
        if rows == 0:
            continue
        execute_job(job, worker_id)


if __name__ == "__main__":
    run_worker()
