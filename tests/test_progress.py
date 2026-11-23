"""Progress indicator and subprocess heartbeat regression tests."""
import contextlib
import io
import os
import sys
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from reconductor import cli, core, engine
from reconductor.progress import TerminalProgress


class ProgressTests(unittest.TestCase):
    def test_progress_writes_to_stderr_stream(self):
        output = io.StringIO()
        progress = TerminalProgress(output)
        progress({"event": "case_started", "case_id": "case-test", "maximum": 8})
        progress({"event": "step_started", "tool": "spiderfoot", "index": 1,
                  "maximum": 8, "timeout": 300})
        progress({"event": "heartbeat", "tool": "spiderfoot", "elapsed": 20, "timeout": 300})
        progress({"event": "lead_discovered", "kind": "username", "count": 1, "maximum": 3})
        progress({"event": "step_finished", "tool": "spiderfoot", "index": 1,
                  "state": "completed", "duration": 26.5})
        progress({"event": "case_finished", "case_id": "case-test", "status": "completed"})
        text = output.getvalue()
        self.assertIn("Starting spiderfoot", text)
        self.assertIn("still running 00:20 / 05:00 timeout", text)
        self.assertIn("New unverified username lead", text)
        self.assertIn("completed in 00:26", text)
        self.assertIn("case-test: completed", text)

    def test_subprocess_can_report_heartbeat_without_losing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            ticks = []
            code = "import time; time.sleep(0.20); print('hello from tool')"
            rc, stdout, stderr, state = core._run_tool(
                [sys.executable, "-c", code], Path(directory), timeout=3,
                on_tick=lambda seconds: ticks.append(seconds), tick_seconds=0.05
            )
            self.assertEqual(rc, 0)
            self.assertEqual(state, "completed")
            self.assertIn("hello from tool", stdout)
            self.assertEqual(stderr, "")
            self.assertGreaterEqual(len(ticks), 1)

    def test_subprocess_timeout_still_enforced(self):
        with tempfile.TemporaryDirectory() as directory:
            rc, _, _, state = core._run_tool(
                [sys.executable, "-c", "import time;time.sleep(2)"],
                Path(directory), timeout=0.1,
                on_tick=lambda _: None, tick_seconds=0.03
            )
            self.assertEqual(rc, 124)
            self.assertEqual(state, "timeout")

    def test_engine_reports_events_without_changing_case_results(self):
        with tempfile.TemporaryDirectory() as directory:
            clues = engine.normalize_clues(names=["Jane Doe"])
            events = []
            with mock.patch.dict(os.environ, {"RECONDUCTOR_HOME": directory}):
                with mock.patch("reconductor.engine.shutil.which", return_value="/bin/true"):
                    with mock.patch("reconductor.engine.core._run_tool") as runner:
                        def simulate(argv, cwd, timeout, **kwargs):
                            if "on_tick" in kwargs:
                                kwargs["on_tick"](11.0)
                            return 0, "[]", "", "completed"
                        runner.side_effect = simulate
                        folder, record = engine.run(
                            clues, "medium", acknowledge_exposure=True,
                            on_progress=events.append
                        )
            self.assertEqual(record["status"], "completed")
            kinds = [event["event"] for event in events]
            self.assertEqual(kinds, [
                "case_started", "step_started", "heartbeat",
                "step_finished", "case_finished"
            ])

    def test_scan_cli_progress_enabled_and_can_be_disabled(self):

        with mock.patch("reconductor.cli.core.execute", return_value=(
            Path("/tmp/example"), {"id": "example", "status": "completed", "steps": []}
        )) as execute:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main([
                    "scan", "username", "janedoe",
                    "--execute", "--acknowledge-exposure"
                ]), 0)
            self.assertIsInstance(execute.call_args.kwargs["on_progress"], TerminalProgress)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main([
                    "scan", "username", "janedoe",
                    "--execute", "--acknowledge-exposure", "--no-progress"
                ]), 0)
            self.assertIsNone(execute.call_args.kwargs["on_progress"])


if __name__ == "__main__":
    unittest.main()
