"""Markdown network workspaces, shared profiles, and local HTTP API tests."""
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

from reconductor import networks, webapp


class NetworkStorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.environment = mock.patch.dict(os.environ, {"RECONDUCTOR_HOME": self.directory.name})
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.directory.cleanup()

    def test_markdown_workspaces_and_profiles(self):
        family = networks.create_workspace("Family Network", "My family circle")
        person = networks.create_person("Person A", "Shared profile")
        networks.attach_person(family["id"], person["id"])
        group = networks.create_group(family["id"], "Our Family", "family")
        edge = networks.create_link(family["id"], person["id"], group["id"], "member of")
        ws = networks.get_workspace(family["id"])
        self.assertEqual(len(ws["people"]), 1)
        self.assertEqual(len(ws["groups"]), 1)
        self.assertEqual(len(ws["edges"]), 1)
        self.assertEqual(edge["origin"], "manual")
        self.assertTrue((networks.root()/"Workspaces"/family["id"]/"Workspace.md").is_file())
        graph = networks.root()/"Workspaces"/family["id"]/"Graph.md"
        self.assertTrue(graph.is_file())
        self.assertIn("[[People/"+person["id"], graph.read_text())
        self.assertIn("[[Workspaces/"+family["id"]+"/Groups/", graph.read_text())
        profile = networks.root()/"People"/(person["id"]+".md")
        self.assertEqual(profile.stat().st_mode&0o777,0o600)
        self.assertTrue(all(x.suffix==".md" for x in networks.root().rglob("*") if x.is_file()))
        self.assertIn("member of",graph.read_text())

    def test_independent_workspaces_and_shared_profile_sync(self):
        family = networks.create_workspace("Family")
        church = networks.create_workspace("Church")
        person = networks.create_person("Alex One")
        networks.attach_person(family["id"],person["id"])
        networks.attach_person(church["id"],person["id"])
        group = networks.create_group(family["id"],"Family hub","family")
        networks.create_link(family["id"],person["id"],group["id"],"member of")
        family_view = networks.workspace_view(family["id"])
        church_view = networks.workspace_view(church["id"])
        self.assertEqual(len(family_view["edges"]),1)
        self.assertEqual(len(church_view["edges"]),0)
        self.assertFalse("memberships" in church_view)  # viewed only on explicit request
        memberships = networks.person_memberships(person["id"])
        self.assertEqual({w["id"] for w in memberships},{family["id"],church["id"]})
        networks.update_person(person["id"],"Alex Renamed","Verified by operator")
        self.assertEqual(networks.workspace_view(family["id"])["nodes"][0]["label"],"Alex Renamed")
        self.assertEqual(networks.workspace_view(church["id"])["nodes"][0]["label"],"Alex Renamed")
        self.assertEqual(len(networks.workspace_view(church["id"])["edges"]),0)
        self.assertIn("Alex Renamed",(networks.root()/"Workspaces"/family["id"]/"Graph.md").read_text())

    def test_clustering_only_when_explicitly_connected(self):
        ws=networks.create_workspace("School and family")
        a=networks.create_person("A")
        b=networks.create_person("B")
        c=networks.create_person("C")
        for p in (a,b,c): networks.attach_person(ws["id"],p["id"])
        org=networks.create_group(ws["id"],"GCC","organization")
        networks.create_link(ws["id"],a["id"],org["id"],"works at")
        networks.create_link(ws["id"],b["id"],org["id"],"works at")
        view=networks.workspace_view(ws["id"])
        self.assertEqual(len(view["edges"]),2)
        self.assertEqual(len(view["clusters"]),1)
        self.assertEqual(view["clusters"][0]["count"],2)
        self.assertNotIn(c["id"],view["clusters"][0]["members"])
        # There is no A-to-B edge even though both share GCC.
        self.assertFalse(any({e["source"],e["target"]}=={a["id"],b["id"]} for e in view["edges"]))

    def test_cross_workspace_link_rejected(self):
        a=networks.create_workspace("A")
        b=networks.create_workspace("B")
        first=networks.create_person("First")
        second=networks.create_person("Second")
        networks.attach_person(a["id"],first["id"])
        networks.attach_person(b["id"],second["id"])
        with self.assertRaises(networks.NetworkError):
            networks.create_link(a["id"],first["id"],second["id"],"knows")
        with self.assertRaises(networks.NetworkError):
            networks.create_link(a["id"],first["id"],first["id"],"knows")
        self.assertEqual(networks.workspace_view(a["id"])["edges"],[])

    def test_position_persists_only_in_one_workspace(self):
        first=networks.create_workspace("A")
        second=networks.create_workspace("B")
        person=networks.create_person("Someone")
        for w in (first,second):networks.attach_person(w["id"],person["id"])
        networks.set_position(first["id"],person["id"],110.5,-70)
        self.assertEqual(networks.workspace_view(first["id"])["positions"][person["id"]]["x"],110.5)
        self.assertFalse(networks.workspace_view(second["id"])["positions"])
        with self.assertRaises(networks.NetworkError):
            networks.set_position(first["id"],person["id"],float("nan"),0)

    def test_rejects_invalid_names_and_ids(self):
        with self.assertRaises(networks.NetworkError):
            networks.create_workspace("  ")
        with self.assertRaises(networks.NetworkError):
            networks.create_person("Person\nwith newline")
        with self.assertRaises(networks.NetworkError):
            networks.get_workspace("../../cases")
        with self.assertRaises(networks.NetworkError):
            networks.get_person("../case")
        with self.assertRaises(networks.NetworkError):
            networks.create_group(networks.create_workspace("Test")["id"],"GCC","bad-kind")


class NetworkApiTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.environment=mock.patch.dict(os.environ,{"RECONDUCTOR_HOME":self.directory.name})
        self.environment.start()
        self.state=webapp.DashboardState(0)
        self.server=ThreadingHTTPServer(("127.0.0.1",0),webapp.handler_for(self.state))
        self.state.port=self.server.server_address[1]
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.base="http://127.0.0.1:"+str(self.state.port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.environment.stop()
        self.directory.cleanup()

    def request(self,path,body=None,authorized=True):
        headers={}
        if body is not None:
            headers["Content-Type"]="application/json"
            if authorized:
                headers["X-Reconductor-Token"]=self.state.token
                headers["Origin"]=self.base
        request=Request(self.base+path,
                        data=json.dumps(body).encode() if body is not None else None,
                        headers=headers,method="POST" if body is not None else "GET")
        with urlopen(request,timeout=5) as result:
            raw=result.read()
        return json.loads(raw) if path.startswith("/api/") else raw

    def test_static_app_and_create_reuse_cluster(self):
        self.assertIn(b"RELATIONSHIP NETWORKS",self.request("/network.html"))
        self.assertIn(b"layoutGraph",self.request("/network.js"))
        self.assertIn(b"network-map",self.request("/network.css"))
        ws1=self.request("/api/network-workspaces",{"name":"Family","description":"My circle"})["workspace"]
        ws2=self.request("/api/network-workspaces",{"name":"Church"})["workspace"]
        p1=self.request("/api/network-workspaces/"+ws1["id"]+"/people",{"name":"A"})["person"]
        p2=self.request("/api/network-workspaces/"+ws1["id"]+"/people",{"name":"B"})["person"]
        self.request("/api/network-workspaces/"+ws2["id"]+"/members",{"person_id":p1["id"]})
        group=self.request("/api/network-workspaces/"+ws1["id"]+"/groups",
                           {"name":"GCC","kind":"organization"})["group"]
        for p in (p1,p2):
            self.request("/api/network-workspaces/"+ws1["id"]+"/links",
                         {"source":p["id"],"target":group["id"],"type":"works at"})
        view1=self.request("/api/network-workspaces/"+ws1["id"])
        view2=self.request("/api/network-workspaces/"+ws2["id"])
        self.assertEqual(view1["clusters"][0]["count"],2)
        self.assertEqual(len(view1["edges"]),2)
        self.assertEqual(view2["edges"],[])
        self.assertNotIn("memberships",view1)
        membership=self.request("/api/network-people/"+p1["id"]+"/memberships")
        self.assertEqual(len(membership["memberships"]),2)
        self.request("/api/network-people/"+p1["id"],{"name":"A Updated","details":"Shared"})
        self.assertEqual(self.request("/api/network-workspaces/"+ws2["id"])["nodes"][0]["label"],"A Updated")
        self.assertEqual(self.request("/api/network-workspaces/"+ws2["id"])["edges"],[])

    def test_unauthorized_write_rejected(self):
        with self.assertRaises(HTTPError) as raised:
            self.request("/api/network-workspaces",{"name":"Unauthorized"},authorized=False)
        self.assertEqual(raised.exception.code,403)

    def test_no_research_commands_needed_for_network_operations(self):
        with mock.patch("reconductor.webapp.engine.run") as runner:
            workspace=self.request("/api/network-workspaces",{"name":"Manual only"})["workspace"]
            self.request("/api/network-workspaces/"+workspace["id"]+"/groups",
                         {"name":"School","kind":"school"})
            runner.assert_not_called()


if __name__=="__main__":
    unittest.main()
