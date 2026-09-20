import logging
import os
import signal
import socket
import threading
import time
import uuid

import job

log = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 5  # seconds
SWEEP_INTERVAL = 15  # seconds
IDLE_POLL_INTERVAL = 2  # seconds
STALE_THRESHOLD = 30  # must be > HEARTBEAT_INTERVAL * 2


def execute_job(current_job: dict, worker_id: str) -> None:
    short_job_id = current_job["id"][:8]
    short_worker_id = worker_id[:8]
    fence_token = current_job["fence_token"]

    print(
        f"[{short_worker_id}] Executing job {short_job_id} ({current_job['type']}) [Token: {fence_token}]..."
    )
    try:
        time.sleep(5)
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
        elif status == "RETRY":
            print(f"[{short_worker_id}] Job {short_job_id} FAILED (will retry): {e}")
        else:
            print(f"[{short_worker_id}] Job {short_job_id} FAILED permanently: {e}")


def sweep(worker_id: str) -> None:
    try:
        recovered = job.recover_stale(STALE_THRESHOLD)
    except Exception:
        log.exception("recover_stale failed")
        recovered = 0

    try:
        exhausted = job.cleanup_exhausted()
    except Exception:
        log.exception("cleanup_exhausted failed")
        exhausted = 0

    if recovered or exhausted:
        print(
            f"[{worker_id[:8]}] Sweeper: recovered={recovered}, exhausted={exhausted}"
        )


def heartbeat_loop(worker_id: str, stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        try:
            job.heartbeat(worker_id)
        except Exception:
            log.exception("heartbeat failed for worker %s", worker_id)
        stop_event.wait(HEARTBEAT_INTERVAL)


# ─────────────────────────────────────────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────────────────────────────────────────


def run_worker():
    worker_id = str(uuid.uuid4())
    job.register_worker(worker_id, socket.gethostname(), os.getpid())
    print(f"Worker {worker_id[:8]} online. Polling job queue...")

    shutting_down = False
    hb_stop_event = threading.Event()

    def shutdown(signum, frame, _flag_holder=None):
        nonlocal shutting_down
        print(f"\nWorker {worker_id[:8]} received signal. Finishing current job...")
        shutting_down = True

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # --- Start the heartbeat thread ---
    hb_thread = threading.Thread(
        target=heartbeat_loop,
        args=(worker_id, hb_stop_event),
        daemon=True,
        name=f"heartbeat-{worker_id[:8]}",
    )
    hb_thread.start()

    last_sweep = time.time()

    try:
        while not shutting_down:
            now = time.time()

            # Sweep
            if now - last_sweep > SWEEP_INTERVAL:
                sweep(worker_id)
                last_sweep = now

            # Claim + execute
            try:
                current_job = job.claim_next(worker_id)
            except Exception:
                log.exception("claim_next failed")
                time.sleep(IDLE_POLL_INTERVAL)
                continue

            if not current_job:
                time.sleep(IDLE_POLL_INTERVAL)
                continue

            try:
                execute_job(current_job, worker_id)
            except Exception:
                log.exception("execute_job crashed for job %s", current_job["id"])
    finally:
        hb_stop_event.set()
        hb_thread.join(timeout=HEARTBEAT_INTERVAL + 1)

        try:
            job.mark_offline(worker_id)
        except Exception:
            log.exception("Failed to mark worker offline")

        print(f"Worker {worker_id[:8]} offline. Goodbye.")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    run_worker()
