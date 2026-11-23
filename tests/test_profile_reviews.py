"""Readable site descriptions and operator-only profile review decisions."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from reconductor import core, findings, reviews, webapp, markdown_store as store


class ProfileReviewTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.folder = Path(self.directory.name)
        self.folder.joinpath("raw").mkdir()
        raw = json.dumps([
            {"type": "Username", "data": "sampleuser"},
            {"type": "Account on External Site",
             "data": "Bandcamp (Category: music) <SFURL>https://bandcamp.com/sampleuser</SFURL>"},
            {"type": "Account on External Site",
             "data": "UnknownSite (Category: social) <SFURL>https://example.org/sampleuser</SFURL>"},
            {"type": "Account on External Site",
             "data": "7 Cups (Category: social) <SFURL>https://www.7cups.com/@sampleuser</SFURL>"},
        ])
        store.write_capture(self.folder/"raw/01-spiderfoot.stdout.md","spiderfoot","stdout",raw)
        self.record={"target":"Sample User","clues":[],"leads":[],"steps":[{
            "tool":"spiderfoot","stdout_file":"raw/01-spiderfoot.stdout.md",
        }]}
        self.findings=findings.extract(self.folder,self.record)

    def tearDown(self):
        self.directory.cleanup()

    def test_known_site_summaries_not_person_attribution(self):
        bandcamp=next(f for f in self.findings if f["display_name"]=="Bandcamp")
        self.assertIn("music",bandcamp["site_summary"].lower())
        self.assertEqual(bandcamp["verification"],"unverified")
        unknown=next(f for f in self.findings if f["display_name"]=="UnknownSite")
        self.assertIn("not cataloged",unknown["site_summary"])
        seven=next(f for f in self.findings if f["display_name"]=="7 Cups")
        self.assertIn("peer support",seven["site_summary"])
        self.assertIn("ownership unknown",seven["match_basis"])

    def test_operator_accept_reject_undo_persists_markdown(self):
        to_accept=self.findings[1]["id"]
        to_reject=self.findings[2]["id"]
        reviews.set_review(self.folder,to_accept,"matches",self.findings)
        reviews.set_review(self.folder,to_reject,"not_a_match",self.findings)
        self.assertTrue((self.folder/"reviews.md").exists())
        self.assertEqual((self.folder/"reviews.md").stat().st_mode&0o777,0o600)
        marked=reviews.apply(self.findings,reviews.load(self.folder))
        self.assertEqual(marked[1]["review"],"matches")
        self.assertEqual(marked[2]["review"],"not_a_match")
        self.assertEqual(marked[0]["review"],"unreviewed")
        self.assertEqual(marked[1]["verification"],"unverified")
        graph=findings.graph_data(self.record,marked,{"people":[],"links":[]})
        by_id={n["id"]:n for n in graph["nodes"]}
        self.assertNotIn(to_reject,by_id)
        self.assertEqual(by_id[to_accept]["status"],"operator_marked_match")
        self.assertEqual(len(graph["edges"]),len(marked)-1)
        reviews.set_review(self.folder,to_reject,"unreviewed",self.findings)
        self.assertNotIn(to_reject,reviews.load(self.folder))

    def test_reject_invented_finding_and_bad_decisions(self):
        with self.assertRaises(ValueError):
            reviews.set_review(self.folder,"finding:"+"1"*20,"matches",self.findings)
        with self.assertRaises(ValueError):
            reviews.set_review(self.folder,self.findings[0]["id"],"verified",self.findings)
        with self.assertRaises(ValueError):
            reviews.set_review(self.folder,"../../etc/passwd","matches",self.findings)
        self.assertFalse((self.folder/"reviews.md").exists())


if __name__ == "__main__":
    unittest.main()
