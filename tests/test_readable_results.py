"""Ensure tool output is presented as understandable, unverified leads."""
import json
from pathlib import Path
import tempfile
import unittest

from reconductor import findings
from reconductor import markdown_store as store


class ReadableResultsTests(unittest.TestCase):
    def test_spiderfoot_sfurllinks_become_clean_profile_cards(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            raw = json.dumps([
                {"type": "Username", "data": "tylerthibault"},
                {"type": "Account on External Site",
                 "data": "Codewars (Category: coding) <SFURL>https://www.codewars.com/users/tylerthibault</SFURL>"},
                {"type": "Account on External Site",
                 "data": "Disqus (Category: social) <SFURL>https://disqus.com/by/tylerthibault/?key=secret</SFURL>"},
            ])
            path=folder / "raw/01-spiderfoot.stdout.md"
            store.write_capture(path,"spiderfoot","stdout",raw)
            record={"steps":[{"tool":"spiderfoot","stdout_file":"raw/01-spiderfoot.stdout.md"}]}
            rows=findings.extract(folder,record)
            self.assertEqual(len(rows),3)
            username=rows[0]
            self.assertEqual(username["category"],"username")
            self.assertEqual(username["display_name"],"tylerthibault")
            site=rows[1]
            self.assertEqual(site["category"],"profile")
            self.assertEqual(site["display_name"],"Codewars")
            self.assertEqual(site["description"],"Coding category")
            self.assertEqual(site["url"],"https://www.codewars.com/users/tylerthibault")
            self.assertIn("<SFURL>",site["value"])  # original observation stays preserved
            self.assertEqual(site["verification"],"unverified")
            self.assertEqual(rows[2]["url"],"https://disqus.com/by/tylerthibault/")
            self.assertNotIn("key=secret",rows[2]["url"])
            graph=findings.graph_data(
                {"clues":[],"leads":[],"target":"Subject"},rows,{"people":[],"links":[]}
            )
            labels={node["label"] for node in graph["nodes"]}
            self.assertIn("Codewars",labels)
            self.assertTrue(all(node["status"]!="verified" for node in graph["nodes"]))
            self.assertEqual(store.read_capture(path),raw)

    def test_malformed_or_non_http_tags_not_clickable(self):
        display=findings._display_fields(
            "Account on External Site","Unknown <SFURL>javascript:alert(1)</SFURL>"
        )
        self.assertIsNone(display["url"])
        self.assertEqual(display["category"],"profile")


if __name__ == "__main__":
    unittest.main()
