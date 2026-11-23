"""Deeper research planning, structured candidates, and archival adapter tests."""
from __future__ import annotations

import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from reconductor import core, engine, findings, markdown_store as store, wayback


class DeepIntegrationTests(unittest.TestCase):
    def test_deep_username_adds_social_analyzer_and_maigret_markdown(self):
        tasks=core.plan("username","sampleuser","deep")
        self.assertEqual([task["tool"] for task in tasks],
                         ["sherlock","maigret","social-analyzer"])
        maigret=next(task for task in tasks if task["tool"]=="maigret")
        self.assertIn("--md",maigret["argv"])
        self.assertIn("--folderoutput",maigret["argv"])
        social=next(task for task in tasks if task["tool"]=="social-analyzer")
        self.assertEqual(social["argv"][0],"social-analyzer")
        self.assertIn("--output",social["argv"])
        self.assertEqual([task["tool"] for task in core.plan("username","sampleuser","medium")],
                         ["sherlock","maigret"])

    def test_deep_domain_includes_explicit_wayback_lookup(self):
        clue={"kind":"domain","value":"example.org","hops":0}
        tools=[task["tool"] for task in engine.tasks_for(clue,"deep")]
        self.assertIn("wayback",tools)
        self.assertNotIn("wayback",[task["tool"] for task in engine.tasks_for(clue,"light")])
        summary=engine.preview([clue],"deep")
        self.assertIn("wayback",summary)

    def test_structured_social_analyzer_filters_unknown_candidates(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            raw=json.dumps({
                "detected":[{"found":3,"link":"https://github.com/sampleuser","rate":"%97.2"}],
                "unknown":[{"link":"https://example.org/sampleuser"}],
                "failed":[{"found":0,"link":"https://reddit.com/user/sampleuser"}],
            })
            file=folder/"raw/01-social-analyzer.stdout.md"
            store.write_capture(file,"social-analyzer","stdout",raw)
            record={"steps":[{"tool":"social-analyzer","stdout_file":"raw/01-social-analyzer.stdout.md"}]}
            rows=findings.extract(folder,record)
            self.assertEqual([f["url"] for f in rows],["https://github.com/sampleuser"])
            self.assertEqual(rows[0]["verification"],"unverified")

    def test_archived_snapshot_parses_without_identity_attribution(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            file=folder/"raw/01-wayback.stdout.md"
            raw=json.dumps([{"type":"Historical snapshot",
                              "data":"https://web.archive.org/web/20220101090000/https://example.org/",
                              "source":"Internet Archive"}])
            store.write_capture(file,"wayback","stdout",raw)
            result=findings.extract(folder,{"steps":[{"tool":"wayback",
                                "stdout_file":"raw/01-wayback.stdout.md"}]})
            self.assertEqual(result[0]["category"],"history")
            self.assertIn("2022-01-01",result[0]["display_name"])
            self.assertEqual(result[0]["verification"],"unverified")

    def test_wayback_host_is_fixed_and_result_is_bounded(self):
        payload=json.dumps([
            ["timestamp","original","statuscode"],
            ["20220301000000","https://example.org/","200"],
            ["bad","https://example.org/","200"],
        ]).encode()
        response=mock.MagicMock()
        response.__enter__.return_value.read.return_value=payload
        with mock.patch.object(wayback,"urlopen",return_value=response) as opener:
            raw=wayback.snapshots("example.org")
        events=json.loads(raw)
        self.assertEqual(len(events),1)
        self.assertEqual(events[0]["timestamp"],"20220301000000")
        url=opener.call_args.args[0].full_url
        self.assertEqual(urlsplit(url).hostname,"web.archive.org")
        self.assertEqual(parse_qs(urlsplit(url).query)["url"],["example.org"])
        with self.assertRaises(core.ReconductorError):
            wayback.snapshots("http://127.0.0.1")

    def test_maigret_report_preserved_for_readable_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            report_path=folder/"raw/02-maigret.profile-report.md"
            store.write_capture(report_path,"maigret","report",
                                "# Maigret profile summary\nPublic profile https://github.com/sampleuser")
            record={"steps":[{"tool":"maigret","stdout_file":None,
                               "report_file":"raw/02-maigret.profile-report.md"}]}
            rows=findings.extract(folder,record)
            self.assertTrue(any(f["url"]=="https://github.com/sampleuser" for f in rows))
            preview=findings.step_previews(folder,record)[0]
            self.assertIn("Maigret profile summary",preview["report"])


if __name__=="__main__":
    unittest.main()
