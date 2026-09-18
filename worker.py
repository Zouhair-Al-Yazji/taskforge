import os
import socket
import time
import uuid

import job


def execute_job(current_job: dict, worker_id: str):
    short_job_id = current_job["id"][:8]
    short_worker_id = worker_id[:8]
    fence_token = current_job["fence_token"]

    print(
        f"[{short_worker_id}] Executing job {short_job_id} ({current_job['type']}) [Token: {fence_token}]..."
    )
    try:
        time.sleep(3)
        status = job.complete(
            current_job["id"], worker_id, fence_token, '{"status": "ok"}'
        )
        if status == "FENCED_OUT":
            print(
                f"[{short_worker_id}] FENCED OUT on job {short_job_id}. Marking audit trail..."
            )
            job.mark_fenced_out(current_job["id"], worker_id, fence_token)
        else:
            print(f"[{short_worker_id}] Job {short_job_id} COMPLETED successfully.")
    except Exception as e:
        status = job.fail(current_job["id"], worker_id, fence_token, str(e))
        if status == "FENCED_OUT":
            print(
                f"[{short_worker_id}] FENCED OUT on job {short_job_id}. Marking audit trail..."
            )
            job.mark_fenced_out(current_job["id"], worker_id, fence_token)
        else:
            print(f"[{short_worker_id}] Job {short_job_id} FAILED: {e}")


def run_worker():
    worker_id = str(uuid.uuid4())
    job.register_worker(worker_id, socket.gethostname(), os.getpid())
    print(f"Worker {worker_id[:8]} online. Polling job queue...")

    last_heartbeat = time.time()
    last_sweep = time.time()

    while True:
        now = time.time()

        if now - last_heartbeat > 5:
            job.heartbeat(worker_id)
            last_heartbeat = now

        if now - last_sweep > 15:
            recovered = job.recover_stale()
            exhausted = job.cleanup_exhausted()
            if recovered > 0 or exhausted > 0:
                print(
                    f"[Sweeper] Recovered {recovered} stale job(s); failed {exhausted} exhausted job(s)."
                )
            last_sweep = now

        current_job = job.claim_next(worker_id)
        if not current_job:
            time.sleep(2)
            continue

        execute_job(current_job, worker_id)


if __name__ == "__main__":
    run_worker()
