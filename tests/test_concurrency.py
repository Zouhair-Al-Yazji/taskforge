"""
Exercises the two concurrency fixes:
  1. Write lock prevents "database is locked" from parallel writers.
  2. Heartbeats keep a lease alive during long job execution.
  3. Fencing prevents a stale worker from overwriting a fresh worker.
"""

import threading
import time

from tests.base import TaskforgeTestCase


class TestConcurrentWrites(TaskforgeTestCase):
    def test_heartbeats_and_writes_do_not_raise(self):
        worker_id = "worker-race"
        self.job.register_worker(worker_id, "localhost", 1)

        errors: list[Exception] = []
        stop = threading.Event()

        def heartbeat_loop():
            while not stop.is_set():
                try:
                    self.job.heartbeat(worker_id)
                except Exception as e:  # noqa: BLE001
                    errors.append(e)

        def job_loop():
            for _ in range(30):
                try:
                    self.job.create_job("task", "{}")
                    claimed = self.job.claim_next(worker_id)
                    if claimed:
                        self.job.complete(
                            claimed["id"],
                            worker_id,
                            claimed["fence_token"],
                            "{}",
                        )
                except Exception as e:  # noqa: BLE001
                    errors.append(e)

        hb_thread = threading.Thread(target=heartbeat_loop, daemon=True)
        hb_thread.start()

        job_thread = threading.Thread(target=job_loop)
        job_thread.start()
        job_thread.join()

        stop.set()
        hb_thread.join(timeout=2)

        self.assertEqual(errors, [], f"Concurrent writes raised: {errors}")


class TestFencing(TaskforgeTestCase):
    def test_stale_completion_is_rejected(self):
        self.job.register_worker("worker-a", "localhost", 1)
        self.job.register_worker("worker-b", "localhost", 2)

        self.job.create_job("task", "{}")

        claim_a = self.claim_or_fail("worker-a")
        self.assertEqual(claim_a["fence_token"], 1)

        # Force recovery: mark worker A offline.
        with self.db.get_db() as conn, self.db.write_txn(conn):
            conn.execute("UPDATE workers SET status='OFFLINE' WHERE id='worker-a'")
        self.job.recover_stale(threshold_seconds=0)

        # Worker B claims the requeued job.
        claim_b = self.claim_or_fail("worker-b")
        self.assertEqual(claim_b["fence_token"], 2)

        # Worker B completes → OK.
        self.assertEqual(
            self.job.complete(claim_b["id"], "worker-b", claim_b["fence_token"], "{}"),
            "COMPLETED",
        )

        # Worker A tries to complete with its stale token → FENCED_OUT.
        self.assertEqual(
            self.job.complete(claim_a["id"], "worker-a", claim_a["fence_token"], "{}"),
            "FENCED_OUT",
        )


class TestHeartbeatKeepsLeaseAlive(TaskforgeTestCase):
    def test_slow_job_is_not_stolen(self):
        self.job.register_worker("slow", "localhost", 1)
        self.job.register_worker("sweeper", "localhost", 2)

        self.job.create_job("task", "{}")
        claimed = self.claim_or_fail("slow")

        stop = threading.Event()

        def hb():
            while not stop.is_set():
                self.job.heartbeat("slow")
                time.sleep(0.1)

        hb_thread = threading.Thread(target=hb, daemon=True)
        hb_thread.start()
        time.sleep(1.0)

        # Aggressive threshold — would be stale if not for heartbeats.
        recovered = self.job.recover_stale(threshold_seconds=0)

        stop.set()
        hb_thread.join(timeout=2)

        self.assertEqual(recovered, 0)
        fetched = self.get_job_or_fail(claimed["id"])
        self.assertEqual(fetched["status"], "PROCESSING")
