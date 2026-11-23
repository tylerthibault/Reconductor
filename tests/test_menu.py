"""Interactive CLI menu tests with no real network lookups."""
import contextlib
import io
from pathlib import Path
import unittest
from unittest import mock

from reconductor import cli, menu
from reconductor.progress import TerminalProgress


class MenuTests(unittest.TestCase):
    def test_exit(self):
        out = io.StringIO()
        with mock.patch("builtins.input", side_effect=["q"]), contextlib.redirect_stdout(out):
            self.assertEqual(menu.run_menu(), 0)
        self.assertIn("New investigation", out.getvalue())

    def test_cli_menu_when_tty(self):
        with mock.patch("reconductor.cli.sys.stdin") as stdin, mock.patch(
            "reconductor.cli.sys.stdout"
        ) as stdout, mock.patch("reconductor.cli.menu.run_menu", return_value=0) as runner:
            stdin.isatty.return_value = True
            stdout.isatty.return_value = True
            self.assertEqual(cli.main([]), 0)
            runner.assert_called_once_with()

    def test_cli_help_non_tty(self):
        out = io.StringIO()
        with mock.patch("reconductor.cli.sys.stdin") as stdin, contextlib.redirect_stdout(out):
            stdin.isatty.return_value = False
            self.assertEqual(cli.main([]), 0)
        self.assertIn("usage: reconductor", out.getvalue())

    def test_explicit_menu_command(self):
        with mock.patch("reconductor.cli.menu.run_menu", return_value=0) as runner:
            self.assertEqual(cli.main(["menu"]), 0)
            runner.assert_called_once_with()

    def test_preview_and_decline_does_not_run(self):
        answers = ["1", "1", "Jane Doe", "", "", "", "", "2", "n", "q"]
        out = io.StringIO()
        with mock.patch("builtins.input", side_effect=answers), mock.patch(
            "reconductor.menu.engine.run"
        ) as run, contextlib.redirect_stdout(out):
            self.assertEqual(menu.run_menu(), 0)
            run.assert_not_called()
        self.assertIn("PREVIEW", out.getvalue())
        self.assertIn("no network requests made", out.getvalue())

    def test_network_requires_exact_run_ack(self):
        answers = ["1", "2", "example_user", "1", "y", "no", "q"]
        with mock.patch("builtins.input", side_effect=answers), mock.patch(
            "reconductor.menu.engine.run"
        ) as run, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(menu.run_menu(), 0)
            run.assert_not_called()

    def test_confirmed_investigation_uses_existing_engine(self):
        answers = ["1", "2", "example_user", "2", "y", "RUN", "q"]
        result = (Path("/tmp/example"), {"id": "test-id", "status": "completed", "steps": [], "leads": []})
        with mock.patch("builtins.input", side_effect=answers), mock.patch(
            "reconductor.menu.engine.run", return_value=result
        ) as run, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(menu.run_menu(), 0)
        self.assertTrue(run.call_args.kwargs["acknowledge_exposure"])
        self.assertIsInstance(run.call_args.kwargs["on_progress"], TerminalProgress)

    def test_local_file_decline_does_not_run(self):
        with mock.patch("builtins.input", side_effect=["1", "4", __file__, "1", "n", "q"]), mock.patch(
            "reconductor.menu.core.execute"
        ) as run, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(menu.run_menu(), 0)
            run.assert_not_called()

    def test_case_menu_and_diagnostics(self):
        with mock.patch("builtins.input", side_effect=["2", "3", "4", "h", "q"]), mock.patch(
            "reconductor.menu.core.list_cases", return_value=[]
        ), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(menu.run_menu(), 0)


if __name__ == "__main__":
    unittest.main()
