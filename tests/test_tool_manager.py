"""Allowlisted tool installation workflows, with no actual downloads or OS changes."""
from __future__ import annotations

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

from reconductor import tool_manager, webapp


class ManagerTests(unittest.TestCase):
    def test_catalog_distinguishes_detected_and_available(self):
        with mock.patch.object(tool_manager, "executable_path", return_value=None):
            items = {x["id"]: x for x in tool_manager.catalog()}
        self.assertEqual(items["wayback"]["status"], "built-in")
        self.assertEqual(items["exiftool"]["status"], "manual")
        self.assertFalse(items["exiftool"]["auto_install"])
        self.assertTrue(items["maigret"]["auto_install"])
        self.assertTrue(items["spiderfoot"]["auto_install"])
        with mock.patch.object(tool_manager, "executable_path", return_value="/home/osint/.local/bin/sherlock"):
            present = {x["id"]: x for x in tool_manager.catalog()}["sherlock"]
            self.assertEqual(present["status"], "detected")
            self.assertNotEqual(present["status"], "ready")  # presence != launch test
            self.assertFalse(present["auto_install"])

    def test_allowlist_and_user_consent_validation(self):
        with mock.patch.object(tool_manager, "executable_path", return_value=None):
            self.assertEqual(tool_manager.validate_selection(["maigret","spiderfoot"]),
                             ["maigret","spiderfoot"])
            for bad in (["exiftool"], ["wayback"], ["my-sh"], ["maigret","maigret"],[],
                        ["maigret"]*6):
                with self.subTest(bad=bad):
                    with self.assertRaises(tool_manager.InstallError):
                        tool_manager.validate_selection(bad)
            with self.assertRaises(tool_manager.InstallError):
                tool_manager.validate_selection("maigret")
        with mock.patch.object(tool_manager, "executable_path", return_value="/path/to/maigret"):
            with self.assertRaises(tool_manager.InstallError):
                tool_manager.validate_selection(["maigret"])

    def test_pipx_install_invoked_without_shell(self):
        commands = []
        with mock.patch.object(tool_manager, "executable_path", side_effect=[None,"/fake/maigret"]), \
             mock.patch.object(tool_manager.shutil,"which",return_value="/usr/bin/pipx"), \
             mock.patch.object(tool_manager, "check_tool",return_value={"status":"ready","message":"ok"}), \
             mock.patch.object(tool_manager, "_command", side_effect=lambda argv, **kwargs: commands.append(argv)):
            result=tool_manager.install_one("maigret",lambda message: None)
        self.assertEqual(result["state"],"installed")
        self.assertEqual(commands,[["/usr/bin/pipx","install","maigret"]])

    def test_check_reports_broken_executable(self):
        fake=mock.Mock(returncode=1,stdout="Traceback: NumPy X86_V2 unsupported")
        with mock.patch.object(tool_manager,"executable_path",return_value="/home/test/bin/sherlock"), \
             mock.patch.object(tool_manager.subprocess,"run",return_value=fake) as runner:
            checked=tool_manager.check_tool("sherlock")
        self.assertEqual(checked["status"],"broken")
        self.assertIn("NumPy",checked["message"])
        self.assertEqual(runner.call_args.args[0],["/home/test/bin/sherlock","--help"])

    def test_batch_continues_if_one_install_fails(self):
        events = []
        def fake(ident,report):
            if ident == "maigret":
                raise tool_manager.InstallError("missing pipx")
            return {"id":ident,"state":"installed","message":"okay"}
        with mock.patch.object(tool_manager,"install_one",side_effect=fake):
            result=tool_manager.run_batch(["maigret","spiderfoot"],events.append)
        self.assertEqual([x["state"] for x in result],["failed","installed"])
        self.assertEqual(len([x for x in events if x["kind"]=="finished"]),2)


class ManagerApiTests(unittest.TestCase):
    def setUp(self):
        self.home=tempfile.TemporaryDirectory()
        self.env=mock.patch.dict(os.environ,{"RECONDUCTOR_HOME":self.home.name})
        self.env.start()
        self.state=webapp.DashboardState(0)
        self.server=ThreadingHTTPServer(("127.0.0.1",0),webapp.handler_for(self.state))
        self.state.port=self.server.server_address[1]
        self.base="http://127.0.0.1:"+str(self.state.port)
        self.worker=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.worker.start()

    def tearDown(self):
        self.server.shutdown();self.server.server_close()
        self.worker.join(timeout=3)
        self.env.stop();self.home.cleanup()

    def request(self,path,body=None,approved=True):
        headers={}
        if body is not None:
            headers["Content-Type"]="application/json"
            if approved:
                headers["X-Reconductor-Token"]=self.state.token
                headers["Origin"]=self.base
        q=Request(self.base+path,headers=headers,
                  data=json.dumps(body).encode() if body is not None else None,
                  method="POST" if body is not None else "GET")
        with urlopen(q,timeout=5) as response:
            content=response.read()
        return json.loads(content) if path.startswith("/api/") else content

    def test_catalog_and_ui_static(self):
        self.assertIn(b"TOOL MANAGER",self.request("/tools.html"))
        self.assertIn(b"installSelected",self.request("/tools.js"))
        self.assertIn(b"tool-entry",self.request("/tools.css"))
        items=self.request("/api/tools")["tools"]
        self.assertTrue(any(item["id"]=="spiderfoot" for item in items))
        self.assertTrue(any(item["id"]=="wayback" for item in items))

    def test_install_cannot_run_without_confirmation_or_token(self):
        with mock.patch.object(tool_manager,"executable_path",return_value=None), \
             mock.patch.object(tool_manager,"run_batch",return_value=[]) as runner:
            for body in ({"tools":["maigret"]},
                         {"tools":["maigret"],"confirm":"INSTALL"},
                         {"tools":["maigret"],"confirm":"INSTALL","acknowledge_changes":False}):
                with self.assertRaises(HTTPError) as raised:
                    self.request("/api/tools/install",body)
                self.assertEqual(raised.exception.code,400)
            with self.assertRaises(HTTPError) as raised:
                self.request("/api/tools/install",{
                    "tools":["maigret"],"confirm":"INSTALL","acknowledge_changes":True
                },approved=False)
            self.assertEqual(raised.exception.code,403)
            runner.assert_not_called()

    def test_selected_batch_starts_job_and_reports_result(self):
        with mock.patch.object(tool_manager,"executable_path",return_value=None), \
             mock.patch.object(tool_manager,"run_batch",return_value=[
                 {"id":"maigret","state":"installed","message":"okay"}
             ]) as runner:
            result=self.request("/api/tools/install",{
                "tools":["maigret"],"confirm":"INSTALL","acknowledge_changes":True
            })
            self.assertTrue(result["job_id"])
            job_id=result["job_id"]
            # Worker is threaded; may complete before or after the GET.
            import time
            for _ in range(30):
                job=self.request("/api/tools/jobs/"+job_id)["job"]
                if job["status"] != "running":break
                time.sleep(0.03)
            self.assertEqual(job["status"],"finished")
            self.assertEqual(job["results"][0]["state"],"installed")
            runner.assert_called_once()


if __name__=="__main__":
    unittest.main()
