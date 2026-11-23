"""Tests for deterministic planning, evidence provenance and bounded lead follow-ups."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from reconductor import cli, core, engine


class InvestigatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.dict(os.environ, {"RECONDUCTOR_HOME": self.tmp.name})
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_accepts_multiple_clues_and_deduplicates(self):
        clues = engine.normalize_clues(
            ["Jane Doe", "Jane Doe"], ["janedoe"], ["jane@example.org"], ["example.org"]
        )
        self.assertEqual([c["kind"] for c in clues], ["name", "username", "email", "domain"])
        self.assertTrue(all(c["status"] == "operator_supplied" for c in clues))

    def test_rejects_invalid_input(self):
        with self.assertRaises(core.ReconductorError):
            engine.normalize_clues()
        with self.assertRaises(core.ReconductorError):
            engine.normalize("name", "Jane")
        with self.assertRaises(core.ReconductorError):
            engine.normalize("email", "invalid")
        with self.assertRaises(core.ReconductorError):
            engine.normalize("username", "--help")

    def test_name_uses_passive_spiderfoot(self):
        clues = engine.normalize_clues(names=["Jane Doe"])
        task = engine.tasks_for(clues[0], "medium")[0]
        self.assertEqual(task["tool"], "spiderfoot")
        self.assertEqual(task["argv"], ["spiderfoot", "-s", "Jane Doe", "-u", "passive", "-o", "json"])

    def test_dry_run_executes_nothing(self):
        stdout = io.StringIO()
        with mock.patch("reconductor.cli.engine.run") as execute, contextlib.redirect_stdout(stdout):
            result = cli.main(["investigate", "--name", "Jane Doe", "--depth", "medium"])
        self.assertEqual(result, 0)
        self.assertIn("DRY RUN", stdout.getvalue())
        execute.assert_not_called()
        self.assertFalse(core.cases_root().exists())

    def test_live_requires_acknowledgment(self):
        clues = engine.normalize_clues(names=["Jane Doe"])
        with self.assertRaises(core.ReconductorError):
            engine.run(clues, "medium")
        self.assertFalse(core.cases_root().exists())

    def test_structured_leads_and_provenance(self):
        clue = engine.normalize_clues(names=["Jane Doe"])[0]
        raw = json.dumps([
            {"type": "Username", "data": "jane_doe", "module": "sfp_social", "source": "https://example.net/a"},
            {"type": "Username", "data": "-bad", "module": "sfp_social"},
            {"type": "Email Address", "data": "private@example.org", "module": "x"},
            {"type": "Username", "data": "jane_doe", "module": "x"},
            {"type": "Username", "data": "other_1", "module": "x"},
        ])
        results = engine._spiderfoot_candidates(raw, clue, "raw/01-spiderfoot.stdout.txt", 3)
        self.assertEqual([r["value"] for r in results], ["jane_doe", "other_1"])
        self.assertTrue(all(r["status"] == "unverified_candidate" for r in results))
        self.assertEqual(results[0]["source_module"], "sfp_social")
        self.assertEqual(results[0]["origin"], "raw/01-spiderfoot.stdout.txt")

    def test_domain_followups_stay_in_supplied_zone(self):
        clue = engine.normalize_clues(domains=["example.org"])[0]
        raw = json.dumps([
            {"type": "Internet Name", "data": "docs.example.org"},
            {"type": "Internet Name", "data": "outside.example.com"},
            {"type": "Internet Name", "data": "example.org"},
        ])
        found = engine._spiderfoot_candidates(raw, clue, "raw/a", 9)
        self.assertEqual([(x["kind"], x["value"]) for x in found], [("domain", "docs.example.org")])

    def test_invalid_json_never_causes_automatic_search(self):
        clue = engine.normalize_clues(names=["Jane Doe"])[0]
        self.assertEqual(engine._spiderfoot_candidates("not json", clue, "raw/a", 8), [])

    def test_followup_is_bounded_and_saved_locally(self):
        clues = engine.normalize_clues(names=["Jane Doe"])
        spiderfoot = json.dumps([
            {"type": "Username", "data": "jane_doe", "module": "sfp_social"},
            {"type": "Username", "data": "jane_new", "module": "sfp_social"},
            {"type": "Username", "data": "jane_old", "module": "sfp_social"},
            {"type": "Username", "data": "jane_more", "module": "sfp_social"},
        ])
        def simulate(argv, cwd, timeout):
            stdout = spiderfoot if argv[0] == "spiderfoot" else "Test stub output"
            return (0, stdout, "", "completed")
        with mock.patch("reconductor.engine.shutil.which", return_value="/usr/bin/test"), mock.patch(
            "reconductor.engine.core._run_tool", side_effect=simulate
        ):
            folder, record = engine.run(clues, "medium", acknowledge_exposure=True)
        self.assertEqual(len(record["leads"]), 3)
        self.assertLessEqual(len(record["steps"]), engine.BUDGETS["medium"]["tasks"])
        self.assertEqual(record["steps"][0]["tool"], "spiderfoot")
        self.assertTrue(any(s["tool"] == "sherlock" for s in record["steps"]))
        self.assertTrue((folder / "dossier.md").exists())
        self.assertEqual(folder.stat().st_mode & 0o777, 0o700)
        dossier = (folder / "dossier.md").read_text()
        self.assertIn("NOT verified identities", dossier)
        self.assertIn("Not searched: no jurisdiction adapter installed", dossier)
        self.assertNotIn("private@example.org", dossier)

    def test_light_never_autofollows(self):
        clues = engine.normalize_clues(names=["Jane Doe"])
        spiderfoot = json.dumps([{"type": "Username", "data": "jane_doe"}])
        with mock.patch("reconductor.engine.shutil.which", return_value="/bin/true"), mock.patch(
            "reconductor.engine.core._run_tool", return_value=(0, spiderfoot, "", "completed")
        ):
            folder, record = engine.run(clues, "light", acknowledge_exposure=True)
        self.assertEqual(len(record["steps"]), 1)
        self.assertEqual(record["leads"], [])


if __name__ == "__main__":
    unittest.main()
