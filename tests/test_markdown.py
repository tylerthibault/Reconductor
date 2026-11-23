"""Markdown vault round-trip, migration and Obsidian linking regression tests."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from reconductor import cli, core, engine, findings
from reconductor import markdown_store as store


class MarkdownStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"RECONDUCTOR_HOME": self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_markdown_only_for_new_case(self):
        path = Path(self.tmp.name) / "local.txt"
        path.write_text("hello!")
        folder, record = core.execute("file", str(path), "light")
        self.assertTrue((folder / "case.md").exists())
        self.assertTrue((folder / "report.md").exists())
        self.assertTrue((folder / "Vault.md").exists())
        self.assertFalse((folder / "case.json").exists())
        self.assertFalse((folder / "graph.json").exists())
        self.assertFalse(list((folder / "raw").glob("*.txt")))
        self.assertEqual(core.get_case(record["id"])[1], record)
        self.assertIn("[[raw/01-sha256.stdout", (folder / "Vault.md").read_text())
        self.assertTrue(all(path.suffix == ".md" for path in folder.rglob("*") if path.is_file()))

    def test_exact_raw_capture_roundtrip_for_complex_text(self):
        strings = [
            "",
            "no terminal newline",
            "line one\nline two\n",
            "~~~\n~~~~~\nmultiple fences\n",
            "A line with weird \x00 bytes already decoded; emoji 😀 and | tables",
            json.dumps([{"type": "Username", "data": "jane_user", "module": "module1"}]),
        ]
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            for index, raw in enumerate(strings):
                path = folder / (str(index) + ".md")
                store.write_capture(path, "spiderfoot" if index == 5 else "maigret", "stdout", raw)
                self.assertEqual(store.read_capture(path), raw)
                self.assertIn("## Original captured output", path.read_text())
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_case_state_structured_roundtrip(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            record = {
                "id": "20261123T054550Z-cff64fbc", "depth": "medium",
                "target": "Tyler | Thibault", "status": "partial",
                "steps": [{"tool": "spiderfoot", "command": ["spiderfoot", "-s", "Jane Doe"]}],
                "clues": [{"kind": "name", "value": "Jane Doe"}],
                "leads": [{"kind": "username", "value": "jane_user", "status": "unverified_candidate"}],
            }
            store.write_case(folder, record)
            self.assertEqual(store.load_case(folder), record)
            self.assertIn("## Starting clues", (folder / "case.md").read_text())
            self.assertIn("## Tool execution", (folder / "case.md").read_text())
            self.assertNotIn("case.json", [p.name for p in folder.iterdir()])

    def test_graph_notes_and_links_roundtrip(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            case = {
                "target": "Jane Doe", "id": "test",
                "clues": [{"kind": "name", "value": "Jane Doe"}],
                "leads": [{"kind": "username", "value": "jane_user", "origin": "raw/a.stdout.md"}],
                "steps": [{"tool": "spiderfoot", "stdout_file": "raw/a.stdout.md"}],
            }
            graph = {
                "people": [{"id": "person:test123", "name": "Alex", "note": "Possible colleague"}],
                "links": [{"source": "case:root", "target": "person:test123", "label": "possible association"}],
            }
            refs = store.sync_vault(folder, case, [], graph)
            store.write_graph(folder, graph, refs)
            self.assertEqual(store.load_graph(folder), graph)
            self.assertIn("[[People/", (folder / "Vault.md").read_text())
            self.assertIn("[[People/", (folder / "graph.md").read_text())
            self.assertIn("unverified", (folder / "graph.md").read_text().lower())
            self.assertTrue(list((folder / "People").glob("*.md")))
            self.assertTrue(list((folder / "Clues").glob("*.md")))
            self.assertTrue(list((folder / "Leads").glob("*.md")))

    def test_legacy_case_conversion_with_backup_and_evidence(self):
        folder, record = core._new_case("investigation", "Jane Doe", "medium")
        record.update({
            "clues": [{"kind": "name", "value": "Jane Doe"}],
            "leads": [{"kind": "username", "value": "jane_user", "origin": "raw/01-spiderfoot.stdout.txt"}],
            "coverage": {"court_records": "Not searched"},
            "budget": {"tasks": 8, "leads": 3},
            "steps": [{"tool": "spiderfoot", "clue_kind": "name", "state": "completed",
                       "stdout_file": "raw/01-spiderfoot.stdout.txt",
                       "stderr_file": "raw/01-spiderfoot.stderr.txt"}],
            "status": "completed",
        })
        text = json.dumps([{"type": "Username", "data": "jane_user", "source": "test"}])
        (folder / "case.json").write_text(json.dumps(record), encoding="utf-8")
        (folder / "raw/01-spiderfoot.stdout.txt").write_text(text, encoding="utf-8")
        (folder / "raw/01-spiderfoot.stderr.txt").write_text("an error\n", encoding="utf-8")
        (folder / "graph.json").write_text(json.dumps({"people": [], "links": []}))
        (folder / "report.md").write_text("Original report")
        backup_root = Path(self.tmp.name) / "legacy-backups"
        changed, backup = store.migrate_case(folder, record, backup_root)
        self.assertTrue(changed)
        self.assertIsNotNone(backup)
        self.assertEqual((backup / "case.json").read_text(), json.dumps({
            **record,
            "steps": [{**record["steps"][0],
                       "stdout_file": "raw/01-spiderfoot.stdout.txt",
                       "stderr_file": "raw/01-spiderfoot.stderr.txt"}],
            "leads": [{**record["leads"][0], "origin": "raw/01-spiderfoot.stdout.txt"}]
        }))
        self.assertEqual(store.read_capture(folder / "raw/01-spiderfoot.stdout.md"), text)
        self.assertEqual(store.read_capture(folder / "raw/01-spiderfoot.stderr.md"), "an error\n")
        self.assertFalse((folder / "case.json").exists())
        self.assertFalse((folder / "graph.json").exists())
        self.assertTrue((folder / "graph.md").exists())
        self.assertTrue((folder / "Vault.md").exists())
        self.assertTrue((folder / "dossier.md").exists())
        self.assertEqual(core.get_case(record["id"])[1], record)
        self.assertTrue(all(path.suffix == ".md" for path in folder.rglob("*") if path.is_file()))
        changed_again, _ = store.migrate_case(folder, record, backup_root)
        self.assertFalse(changed_again)

    def test_dashboard_finds_wrapped_evidence(self):
        folder, record = core._new_case("investigation", "Jane Doe", "medium")
        ref = "raw/01-spiderfoot.stdout.md"
        payload = json.dumps([{"type": "Username", "data": "jane_test", "module": "sfp_x"}])
        store.write_capture(folder / ref, "spiderfoot", "stdout", payload)
        record["steps"].append({"tool": "spiderfoot", "stdout_file": ref})
        self.assertTrue(any(x["value"] == "jane_test" for x in findings.extract(folder, record)))

    def test_cli_migration_requires_explicit_scope(self):
        self.assertEqual(cli.main(["migrate-markdown"]), 2)
        self.assertEqual(cli.main(["migrate-markdown", "--all", "20261123T054550Z-cff64fbc"]), 2)


if __name__ == "__main__":
    unittest.main()
