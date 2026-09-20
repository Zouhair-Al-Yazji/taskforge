"""Tests for the job API layer (taskforge/job.py)."""

import json

from tests.base import TaskforgeTestCase


class TestCreateJob(TaskforgeTestCase):
    def test_returns_uuid(self):
        job_id = self.job.create_job("resize_image", '{"file": "x.jpg"}')
        self.assertIsInstance(job_id, str)
        self.assertEqual(len(job_id), 36)  # UUID4 format

    def test_rejects_bad_json(self):
        with self.assertRaises(ValueError) as ctx:
            self.job.create_job("resize_image", "not json")
        self.assertIn("valid JSON", str(ctx.exception))

    def test_rejects_empty_type(self):
        with self.assertRaises(ValueError):
            self.job.create_job("", "{}")


class TestGetJob(TaskforgeTestCase):
    def test_returns_none_for_unknown_id(self):
        self.assertIsNone(self.job.get_job("deadbeef"))

    def test_rejects_short_prefix(self):
        with self.assertRaises(ValueError) as ctx:
            self.job.get_job("abc")
        self.assertIn("at least 4 characters", str(ctx.exception))

    def test_full_uuid(self):
        job_id = self.job.create_job("send_email", '{"to": "a@b.c"}')
        fetched = self.get_job_or_fail(job_id)
        self.assertEqual(fetched["id"], job_id)
        self.assertEqual(fetched["status"], "PENDING")
        self.assertEqual(fetched["attempts"], 0)

    def test_short_prefix(self):
        job_id = self.job.create_job("send_email", '{"to": "a@b.c"}')
        fetched = self.get_job_or_fail(job_id[:8])
        self.assertEqual(fetched["id"], job_id)

    def test_ambiguous_prefix_raises(self):
        # Insert two jobs sharing the "abcd" prefix.
        self.db.insert_job("abcd1111-0000-0000-0000-000000000001", "t1", "{}")
        self.db.insert_job("abcd2222-0000-0000-0000-000000000002", "t2", "{}")

        with self.assertRaises(self.job.AmbiguousIdentifierError) as ctx:
            self.job.get_job("abcd")
        self.assertEqual(len(ctx.exception.matches), 2)


class TestListJobs(TaskforgeTestCase):
    def test_list_and_count(self):
        for i in range(3):
            self.job.create_job("task", json.dumps({"i": i}))

        jobs = self.job.list_jobs(None, limit=10)
        self.assertEqual(len(jobs), 3)
        self.assertEqual(self.job.count_jobs(None), 3)

    def test_filter_by_status(self):
        self.job.create_job("task", "{}")
        self.job.create_job("task", "{}")

        pending = self.job.list_jobs("PENDING", limit=10)
        self.assertEqual(len(pending), 2)

        completed = self.job.list_jobs("COMPLETED", limit=10)
        self.assertEqual(len(completed), 0)

    def test_rejects_invalid_status(self):
        with self.assertRaises(ValueError) as ctx:
            self.job.list_jobs("BOGUS", limit=10)
        self.assertIn("Invalid status", str(ctx.exception))
