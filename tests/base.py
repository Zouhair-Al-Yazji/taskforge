"""
Shared base class for taskforge tests.

Each test gets a fresh, isolated SQLite database in a temp directory.
The taskforge package modules are reimported on every setUp so module-level
state (like db.DB_PATH) doesn't leak between tests.

Also provides type-narrowing helpers (assertNotNone, claim_or_fail,
get_job_or_fail) that satisfy both runtime correctness and static checkers
like Pylance and mypy.
"""

import sys
import tempfile
import unittest
from pathlib import Path

# Every module in the taskforge package that caches state we care about.
_PACKAGE_MODULES = (
    "taskforge",
    "taskforge.db",
    "taskforge.job",
    "taskforge.utils",
    "taskforge.worker",
    "taskforge.cli",
)


class TaskforgeTestCase(unittest.TestCase):
    """
    Base class for all taskforge tests.

    Responsibilities:
      1. Create a temp directory per test.
      2. Reimport the taskforge package with DB_PATH pointed at a fresh DB.
      3. Expose self.db, self.job, self.utils, self.cli, self.worker.
      4. Provide type-narrowing helpers for common test patterns.
      5. Clean up modules and temp files in tearDown.
    """

    # ── Setup / teardown ─────────────────────────────────────────────────────

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)
        self.db_file = self.tmp_path / "test_taskforge.db"

        for name in _PACKAGE_MODULES:
            sys.modules.pop(name, None)

        import taskforge.db as db_mod

        db_mod.DB_PATH = self.db_file
        db_mod.init_db()

        import taskforge.job as job_mod
        import taskforge.utils as utils_mod
        import taskforge.cli as cli_mod
        import taskforge.worker as worker_mod

        self.db = db_mod
        self.job = job_mod
        self.utils = utils_mod
        self.cli = cli_mod
        self.worker = worker_mod

    def tearDown(self) -> None:
        for name in _PACKAGE_MODULES:
            sys.modules.pop(name, None)
        self._tmpdir.cleanup()

    # ── Type-narrowing helpers ───────────────────────────────────────────────

    def assertNotNone(self, value, msg: str = "expected non-None"):
        """
        Runtime check + type narrowing.

        Fails the test if value is None; otherwise returns it with a
        non-None type so Pylance stops complaining about subscripts.
        """
        self.assertIsNotNone(value, msg)
        assert value is not None  # narrows type for static checkers
        return value

    def claim_or_fail(self, worker_id: str) -> dict:
        """Claim the next job, failing the test if none is available."""
        return self.assertNotNone(
            self.job.claim_next(worker_id),
            f"worker {worker_id} got no job",
        )

    def get_job_or_fail(self, job_id: str) -> dict:
        """Fetch a job by ID, failing the test if it doesn't exist."""
        return self.assertNotNone(
            self.job.get_job(job_id),
            f"job {job_id} not found",
        )

    # ── Fixture helpers ──────────────────────────────────────────────────────

    def register_worker(self, worker_id: str = "worker-a") -> str:
        """Register a worker in the DB and return its ID."""
        self.job.register_worker(worker_id, "localhost", 12345)
        return worker_id
