"""Tests for CLI dispatch. No subprocess needed."""

import contextlib
import io
from types import SimpleNamespace

from tests.base import TaskforgeTestCase


class TestCliParser(TaskforgeTestCase):
    def test_all_subcommands_have_help(self):
        parser = self.cli.build_parser()
        for cmd in ("submit", "status", "jobs", "attempts", "worker"):
            with self.assertRaises(SystemExit) as ctx:
                parser.parse_args([cmd, "--help"])
            self.assertEqual(ctx.exception.code, 0)


class TestSubmitCommand(TaskforgeTestCase):
    def test_submit_creates_job(self):
        args = SimpleNamespace(
            task_type="resize_image",
            payload='{"file": "x.jpg"}',
            quiet=False,
        )

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = self.cli.cmd_submit(args)

        self.assertEqual(rc, 0)
        self.assertIn("Job submitted successfully", buf.getvalue())

    def test_submit_rejects_bad_json(self):
        args = SimpleNamespace(
            task_type="resize_image",
            payload="not json",
            quiet=False,
        )

        err_buf = io.StringIO()
        with contextlib.redirect_stderr(err_buf):
            rc = self.cli.cmd_submit(args)

        self.assertEqual(rc, 1)
        self.assertIn("Error", err_buf.getvalue())

    def test_submit_quiet_prints_only_id(self):
        args = SimpleNamespace(
            task_type="resize_image",
            payload='{"file": "x.jpg"}',
            quiet=True,
        )

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = self.cli.cmd_submit(args)

        self.assertEqual(rc, 0)
        out = buf.getvalue().strip()
        self.assertEqual(len(out), 36)


class TestStatusCommand(TaskforgeTestCase):
    def test_prints_job(self):
        job_id = self.job.create_job("resize_image", "{}")
        args = SimpleNamespace(job_id=job_id)

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = self.cli.cmd_status(args)

        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("Taskforge Job Status", out)
        self.assertIn(job_id[:8], out)

    def test_unknown_id_returns_error(self):
        args = SimpleNamespace(job_id="deadbeef")

        err_buf = io.StringIO()
        with contextlib.redirect_stderr(err_buf):
            rc = self.cli.cmd_status(args)

        self.assertEqual(rc, 1)
        self.assertIn("No job found", err_buf.getvalue())


class TestJobsCommand(TaskforgeTestCase):
    def test_empty_queue(self):
        args = SimpleNamespace(status=None, limit=10)

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = self.cli.cmd_jobs(args)

        self.assertEqual(rc, 0)
        self.assertIn("No jobs found", buf.getvalue())

    def test_lists_jobs(self):
        self.job.create_job("resize_image", "{}")
        self.job.create_job("send_email", "{}")

        args = SimpleNamespace(status=None, limit=10)

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = self.cli.cmd_jobs(args)

        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("ID", out)
        self.assertIn("Showing 2 of 2 jobs", out)

    def test_filters_by_status(self):
        self.job.create_job("resize_image", "{}")
        self.job.create_job("send_email", "{}")

        args = SimpleNamespace(status="PENDING", limit=10)

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = self.cli.cmd_jobs(args)

        self.assertEqual(rc, 0)
        self.assertIn("Showing 2 of 2 jobs", buf.getvalue())


class TestAttemptsCommand(TaskforgeTestCase):
    def test_no_attempts_yet(self):
        job_id = self.job.create_job("resize_image", "{}")
        args = SimpleNamespace(job_id=job_id)

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = self.cli.cmd_attempts(args)

        self.assertEqual(rc, 0)
        self.assertIn("No attempts recorded", buf.getvalue())

    def test_shows_attempts(self):
        worker_id = self.register_worker()
        job_id = self.job.create_job("resize_image", "{}")
        claimed = self.claim_or_fail(worker_id)
        self.job.complete(claimed["id"], worker_id, claimed["fence_token"], "{}")

        args = SimpleNamespace(job_id=job_id)

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = self.cli.cmd_attempts(args)

        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("Attempts for job", out)
        self.assertIn("SUCCESS", out)

    def test_unknown_id_returns_error(self):
        args = SimpleNamespace(job_id="deadbeef")

        err_buf = io.StringIO()
        with contextlib.redirect_stderr(err_buf):
            rc = self.cli.cmd_attempts(args)

        self.assertEqual(rc, 1)
        self.assertIn("No job found", err_buf.getvalue())
