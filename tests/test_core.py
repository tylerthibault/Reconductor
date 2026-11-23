import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from reconductor import cli, core


class PlanTests(unittest.TestCase):
    def test_username_depths(self):
        light = core.plan("username", "test_123", "light")
        medium = core.plan("username", "test_123", "medium")
        deep = core.plan("username", "test_123", "deep")
        self.assertEqual([x["tool"] for x in light], ["sherlock"])
        self.assertEqual([x["tool"] for x in medium], ["sherlock", "maigret"])
        self.assertGreater(deep[0]["timeout"], medium[0]["timeout"])

    def test_domain_passive_only(self):
        tasks = core.plan("domain", "Example.ORG", "deep")
        self.assertEqual(tasks[0]["argv"][1:5], ["-s", "example.org", "-u", "passive"])
        self.assertEqual(tasks[1]["tool"], "theHarvester")
        self.assertTrue(all(step["network"] for step in tasks))

    def test_rejects_unsafe_targets(self):
        for invalid in ("-command", "test;echo", "a b", "a/b"):
            with self.assertRaises(core.ReconductorError):
                core.validate_target("username", invalid)
        for invalid in ("https://example.org", "127.0.0.1", "example.org/path", "x;touch /tmp/test"):
            with self.assertRaises(core.ReconductorError):
                core.validate_target("domain", invalid)

    def test_file_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "test.txt"
            file.write_text("hello")
            self.assertEqual([t["tool"] for t in core.plan("file", str(file), "light")], ["sha256"])
            self.assertEqual([t["tool"] for t in core.plan("file", str(file), "deep")], ["sha256", "exiftool"])


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"RECONDUCTOR_HOME": self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_network_requires_acknowledgment(self):
        with self.assertRaises(core.ReconductorError):
            core.execute("username", "example_user", "light")
        self.assertFalse(core.cases_root().exists())

    def test_offline_file_executed_and_preserved(self):
        file = Path(self.tmp.name) / "fixture.txt"
        file.write_bytes(b"hello")
        with mock.patch("reconductor.core.subprocess.Popen") as process:
            folder, record = core.execute("file", str(file), "light")
            process.assert_not_called()
        self.assertEqual(record["status"], "completed")
        self.assertEqual(len(core.list_cases()), 1)
        raw = (folder / "raw/01-sha256.stdout.txt").read_text()
        self.assertIn(hashlib.sha256(b"hello").hexdigest(), raw)
        self.assertTrue((folder / "report.md").exists())
        self.assertEqual(folder.stat().st_mode & 0o777, 0o700)
        self.assertEqual((folder / "case.json").stat().st_mode & 0o777, 0o600)

    def test_missing_tool_is_reported(self):
        with mock.patch("reconductor.core.shutil.which", return_value=None):
            folder, record = core.execute(
                "username", "test_123", "light", acknowledge_exposure=True
            )
        self.assertEqual(record["status"], "no_results")
        self.assertEqual(record["steps"][0]["state"], "skipped_missing")
        self.assertTrue((folder / "raw/01-sherlock.stderr.txt").exists())

    def test_case_traversal_rejected(self):
        with self.assertRaises(core.ReconductorError):
            core.get_case("../anything")

    def test_cli_dry_run_does_not_execute(self):
        stdout = io.StringIO()
        with mock.patch("reconductor.cli.core.execute") as execute, contextlib.redirect_stdout(stdout):
            result = cli.main(["scan", "username", "demo", "--depth", "medium"])
        self.assertEqual(result, 0)
        execute.assert_not_called()
        self.assertIn("DRY RUN", stdout.getvalue())

    def test_help_for_subcommands(self):
        with self.assertRaises(SystemExit) as raised:
            with contextlib.redirect_stdout(io.StringIO()):
                cli.main(["scan", "--help"])
        self.assertEqual(raised.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
