"""Tests for claim, complete, fail, retry, and recovery."""

from tests.base import TaskforgeTestCase


class TestClaim(TaskforgeTestCase):
    def test_returns_none_when_empty(self):
        worker_id = self.register_worker()
        self.assertIsNone(self.job.claim_next(worker_id))

    def test_marks_job_processing(self):
        worker_id = self.register_worker()
        job_id = self.job.create_job("task", "{}")

        claimed = self.claim_or_fail(worker_id)
        self.assertEqual(claimed["id"], job_id)
        self.assertEqual(claimed["fence_token"], 1)
        self.assertEqual(claimed["attempts"], 1)

        fetched = self.get_job_or_fail(job_id)
        self.assertEqual(fetched["status"], "PROCESSING")
        self.assertEqual(fetched["worker_id"], worker_id)

    def test_fifo_order(self):
        worker_id = self.register_worker()
        id1 = self.job.create_job("task", "{}")
        id2 = self.job.create_job("task", "{}")

        first = self.claim_or_fail(worker_id)
        self.assertEqual(first["id"], id1)
        self.job.complete(first["id"], worker_id, first["fence_token"], "{}")

        second = self.claim_or_fail(worker_id)
        self.assertEqual(second["id"], id2)

    def test_two_workers_do_not_get_same_job(self):
        w1 = self.register_worker("worker-1")
        w2 = self.register_worker("worker-2")
        self.job.create_job("task", "{}")

        claim1 = self.job.claim_next(w1)
        claim2 = self.job.claim_next(w2)

        self.assertIsNotNone(claim1)
        self.assertIsNone(claim2)


class TestComplete(TaskforgeTestCase):
    def test_success(self):
        worker_id = self.register_worker()
        self.job.create_job("task", "{}")
        claimed = self.claim_or_fail(worker_id)

        status = self.job.complete(
            claimed["id"], worker_id, claimed["fence_token"], '{"ok": true}'
        )
        self.assertEqual(status, "COMPLETED")

        fetched = self.get_job_or_fail(claimed["id"])
        self.assertEqual(fetched["status"], "COMPLETED")
        self.assertEqual(fetched["result"], '{"ok": true}')
        self.assertIsNotNone(fetched["completed_at"])

    def test_stale_token_is_fenced_out(self):
        worker_id = self.register_worker()
        self.job.create_job("task", "{}")
        claimed = self.claim_or_fail(worker_id)

        status = self.job.complete(
            claimed["id"], worker_id, claimed["fence_token"] - 1, "{}"
        )
        self.assertEqual(status, "FENCED_OUT")

    def test_wrong_worker_is_fenced_out(self):
        worker_id = self.register_worker("worker-a")
        self.register_worker("worker-b")
        self.job.create_job("task", "{}")
        claimed = self.claim_or_fail(worker_id)

        status = self.job.complete(
            claimed["id"], "worker-b", claimed["fence_token"], "{}"
        )
        self.assertEqual(status, "FENCED_OUT")


class TestFail(TaskforgeTestCase):
    def test_retries_when_attempts_remain(self):
        worker_id = self.register_worker()
        self.job.create_job("task", "{}")  # max_attempts=3
        claimed = self.claim_or_fail(worker_id)

        status = self.job.fail(claimed["id"], worker_id, claimed["fence_token"], "boom")
        self.assertEqual(status, "RETRY")

        fetched = self.get_job_or_fail(claimed["id"])
        self.assertEqual(fetched["status"], "PENDING")
        self.assertEqual(fetched["attempts"], 1)
        self.assertEqual(fetched["error_message"], "boom")

    def test_marks_terminal_when_exhausted(self):
        worker_id = self.register_worker()
        self.job.create_job("task", "{}", max_attempts=2)

        c1 = self.claim_or_fail(worker_id)
        self.assertEqual(
            self.job.fail(c1["id"], worker_id, c1["fence_token"], "e1"),
            "RETRY",
        )

        c2 = self.claim_or_fail(worker_id)
        self.assertEqual(
            self.job.fail(c2["id"], worker_id, c2["fence_token"], "e2"),
            "FAILED",
        )

        fetched = self.get_job_or_fail(c2["id"])
        self.assertEqual(fetched["status"], "FAILED")
        self.assertEqual(fetched["attempts"], 2)

    def test_stale_token_is_fenced_out(self):
        worker_id = self.register_worker()
        self.job.create_job("task", "{}")
        claimed = self.claim_or_fail(worker_id)

        status = self.job.fail(
            claimed["id"], worker_id, claimed["fence_token"] + 1, "boom"
        )
        self.assertEqual(status, "FENCED_OUT")


class TestStaleRecovery(TaskforgeTestCase):
    def _mark_worker_offline(self, worker_id: str) -> None:
        with self.db.get_db() as conn, self.db.write_txn(conn):
            conn.execute(
                "UPDATE workers SET status='OFFLINE', "
                "last_seen=datetime('now','-1 hour') WHERE id = ?",
                (worker_id,),
            )

    def test_requeues_job(self):
        worker_id = self.register_worker()
        self.job.create_job("task", "{}")
        claimed = self.claim_or_fail(worker_id)

        self._mark_worker_offline(worker_id)

        recovered = self.job.recover_stale(threshold_seconds=30)
        self.assertEqual(recovered, 1)

        fetched = self.get_job_or_fail(claimed["id"])
        self.assertEqual(fetched["status"], "PENDING")
        self.assertIsNone(fetched["worker_id"])

    def test_marks_failed_when_exhausted(self):
        worker_id = self.register_worker()
        self.job.create_job("task", "{}", max_attempts=1)
        claimed = self.claim_or_fail(worker_id)

        self._mark_worker_offline(worker_id)
        self.job.recover_stale(threshold_seconds=30)

        fetched = self.get_job_or_fail(claimed["id"])
        self.assertEqual(fetched["status"], "FAILED")


class TestFencedOutAudit(TaskforgeTestCase):
    def test_records_attempt_status(self):
        worker_id = self.register_worker()
        self.job.create_job("task", "{}")
        claimed = self.claim_or_fail(worker_id)

        self.job.mark_fenced_out(claimed["id"], worker_id, claimed["fence_token"])

        attempts = self.job.get_job_attempts(claimed["id"])
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]["status"], "FENCED_OUT")
