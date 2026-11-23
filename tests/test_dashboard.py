"""Local dashboard tests; no external services or live investigations."""
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer

from reconductor import cli, core, findings, webapp


class FindingsTests(unittest.TestCase):
    def test_read_existing_raw_results_without_identity_attribution(self):
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root);(folder/"raw").mkdir()
            spider=[
                {"type":"Username","data":"janedoe","source":"public source"},
                {"type":"Internet Name","data":"example.org","source":"example.org"},
                {"type":"Phone Number","data":"555-555-5555"},
            ]
            (folder/"raw/01-spiderfoot.stdout.txt").write_text(json.dumps(spider))
            (folder/"raw/02-maigret.stdout.txt").write_text("Found https://example.org/users/janedoe?token=secret")
            (folder/"raw/03-sherlock.stderr.txt").write_text("simulated error")
            record={"steps":[
                {"tool":"spiderfoot","stdout_file":"raw/01-spiderfoot.stdout.txt"},
                {"tool":"maigret","stdout_file":"raw/02-maigret.stdout.txt"},
                {"tool":"sherlock","stderr_file":"raw/03-sherlock.stderr.txt","state":"failed"},
            ],"clues":[{"kind":"name","value":"Jane Doe"}],"leads":[],"target":"Jane Doe"}
            extracted=findings.extract(folder,record)
            self.assertTrue(any(f["value"]=="janedoe" for f in extracted))
            self.assertFalse(any(f["value"]=="555-555-5555" for f in extracted))
            self.assertTrue(any(f["url"]=="https://example.org/users/janedoe" for f in extracted))
            self.assertTrue(all(f["verification"]=="unverified" for f in extracted))
            self.assertEqual(findings._text(folder,"../sensitive"),"")
            self.assertEqual(findings._text(folder,"raw/../../passwd"),"")
            graph=findings.graph_data(record,extracted,{"people":[],"links":[]})
            self.assertTrue(any(n["kind"]=="finding" for n in graph["nodes"]))
            self.assertFalse(any(n["status"]=="verified" for n in graph["nodes"]))


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.env=mock.patch.dict(os.environ,{"RECONDUCTOR_HOME":self.tmp.name})
        self.env.start()
        self.folder,self.case=core._new_case("investigation","Jane Doe","medium")
        self.case.update({"clues":[{"kind":"name","value":"Jane Doe","origin":"operator"}],
                          "leads":[],"coverage":{"court_records":"Not searched"}, "steps":[],
                          "status":"completed"})
        core._persist(self.folder,self.case)
        self.state=webapp.DashboardState(0)
        self.server=ThreadingHTTPServer(("127.0.0.1",0),webapp.handler_for(self.state))
        self.state.port=self.server.server_address[1]
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.base="http://127.0.0.1:"+str(self.state.port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.env.stop()
        self.tmp.cleanup()

    def req(self,path,body=None,authorized=True,extra=None):
        headers=dict(extra or {})
        if body is not None:
            headers["Content-Type"]="application/json"
            if authorized:
                headers["X-Reconductor-Token"]=self.state.token
                headers["Origin"]=self.base
        request=Request(self.base+path,data=None if body is None else json.dumps(body).encode(),
                        headers=headers,method="POST" if body is not None else "GET")
        with urlopen(request,timeout=3) as response:
            content=response.read()
        return json.loads(content) if path.startswith("/api/") else content

    def test_local_session_and_list_cases(self):
        self.assertEqual(self.req("/api/session")["token"],self.state.token)
        cases=self.req("/api/cases")["cases"]
        self.assertEqual(cases[0]["id"],self.case["id"])
        detail=self.req("/api/cases/"+self.case["id"])
        self.assertEqual(detail["case"]["status"],"completed")
        self.assertEqual(detail["graph"]["nodes"][0]["kind"],"subject")

    def test_static_assets_served_locally(self):
        self.assertIn(b"RECONDUCTOR",self.req("/"))
        self.assertIn(b"Relationship",self.req("/app.js"))
        self.assertIn(b".sidebar",self.req("/styles.css"))

    def test_rejects_wrong_host(self):
        with self.assertRaises(HTTPError) as raised:
            self.req("/api/cases",extra={"Host":"bad.example.org"})
        self.assertEqual(raised.exception.code,403)

    def test_post_requires_session_token(self):
        with self.assertRaises(HTTPError) as raised:
            self.req("/api/preview",{"names":["Jane Doe"],"depth":"light"},authorized=False)
        self.assertEqual(raised.exception.code,403)

    def test_preview_does_not_execute(self):
        with mock.patch("reconductor.webapp.engine.run") as runner:
            result=self.req("/api/preview",{"names":["Jane Doe"],"depth":"medium"})
            self.assertIn("spiderfoot",result["plan"])
            runner.assert_not_called()

    def test_live_job_requires_acknowledgment(self):
        with self.assertRaises(HTTPError) as raised:
            self.req("/api/jobs",{"names":["Jane Doe"],"depth":"medium"})
        self.assertEqual(raised.exception.code,400)

    def test_add_person_and_manual_link_persisted(self):
        cid=self.case["id"]
        person=self.req("/api/cases/"+cid+"/people",{"name":"Alex Sample","note":"Possible colleague"})["person"]
        self.assertTrue(person["id"].startswith("person:"))
        self.req("/api/cases/"+cid+"/links",{"source":"case:root","target":person["id"],"label":"possible association"})
        d=self.req("/api/cases/"+cid)
        self.assertTrue(any(n["id"]==person["id"] for n in d["graph"]["nodes"]))
        self.assertTrue(any(e["status"]=="user_added" for e in d["graph"]["edges"]))
        self.assertEqual((self.folder/"graph.json").stat().st_mode & 0o777,0o600)

    def test_cli_web_command_help(self):
        args=cli.parser().parse_args(["web","--no-browser","--port","8767"])
        self.assertEqual(args.port,8767)
        self.assertTrue(args.no_browser)


if __name__=="__main__":
    unittest.main()
