"""Private, standard-library-only local web dashboard for Reconductor.

Binds ONLY to 127.0.0.1. Case data never leaves this machine unless an
operator explicitly starts the existing internet-facing investigation engine.
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading
import uuid
import webbrowser
from urllib.parse import urlsplit

from . import core, engine, findings, networks, reviews, tool_manager
from . import markdown_store as store


STATIC = Path(__file__).resolve().parent / "static"


class DashboardState:
    def __init__(self, port: int) -> None:
        self.port = port
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.RLock()
        self.jobs: dict[str, dict] = {}
        self.active_job: str | None = None
        self.active_install: str | None = None
        self.install_jobs: dict[str, dict] = {}

    def run_install(self, job_id: str, tool_ids: list[str]) -> None:
        def on_event(event: dict) -> None:
            with self.lock:
                job = self.install_jobs[job_id]
                job["events"].append(event)
                job["events"] = job["events"][-120:]
        try:
            results = tool_manager.run_batch(tool_ids, on_event)
            with self.lock:
                self.install_jobs[job_id]["results"] = results
                self.install_jobs[job_id]["status"] = (
                    "finished" if all(x["state"] in ("installed", "skipped") for x in results)
                    else "partial"
                )
        except BaseException as exc:
            with self.lock:
                self.install_jobs[job_id]["status"] = "failed"
                self.install_jobs[job_id]["error"] = str(exc)[:400]
        finally:
            with self.lock:
                if self.active_install == job_id:
                    self.active_install = None

    def run_job(self, job_id: str, clues: list[dict], depth: str, location: str | None) -> None:
        def progress(event: dict) -> None:
            with self.lock:
                job = self.jobs[job_id]
                if event.get("event") == "case_started":
                    job["case_id"] = event.get("case_id")
                job["events"].append(event)
                if len(job["events"]) > 200:
                    job["events"] = job["events"][-200:]
        try:
            folder, case = engine.run(
                clues, depth, location=location, acknowledge_exposure=True,
                on_progress=progress,
            )
            with self.lock:
                self.jobs[job_id]["status"] = "finished"
                self.jobs[job_id]["result"] = case["status"]
                self.jobs[job_id]["case_id"] = case["id"]
        except BaseException as exc:
            with self.lock:
                self.jobs[job_id]["status"] = "failed"
                self.jobs[job_id]["error"] = str(exc)[:500]
        finally:
            with self.lock:
                if self.active_job == job_id:
                    self.active_job = None


def _read_graph(folder: Path) -> dict:
    return findings.load_annotations(folder)


def _save_graph(folder: Path, data: dict) -> None:
    record = core.get_case(folder.name)[1]
    refs = store.sync_vault(folder, record, findings.extract(folder, record), data)
    store.write_graph(folder, data, refs)


def handler_for(state: DashboardState):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ReconductorLocal"
        sys_version = ""

        def log_message(self, fmt, *args):
            # Avoid writing case identifiers or research clues to terminal logs.
            return

        def _headers(self, status: int, mime: str, length: int) -> None:
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "connect-src 'self'; img-src 'self' data:; "
                "object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
            )
            self.end_headers()

        def _send(self, payload, status=200) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._headers(status, "application/json; charset=utf-8", len(body))
            self.wfile.write(body)

        def _error(self, status: int, message: str) -> None:
            self._send({"error": message}, status)

        def _host_ok(self) -> bool:
            host = (self.headers.get("Host") or "").lower()
            return host in {f"127.0.0.1:{state.port}", f"localhost:{state.port}"}

        def _post_ok(self) -> bool:
            if self.headers.get("X-Reconductor-Token") != state.token:
                return False
            origin = self.headers.get("Origin")
            if origin and origin not in {
                f"http://127.0.0.1:{state.port}", f"http://localhost:{state.port}"
            }:
                return False
            return self.headers.get("Content-Type", "").split(";")[0].strip() == "application/json"

        def _json_body(self) -> dict:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 65536:
                raise ValueError("Request must be between 1 and 65536 bytes.")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("Expected JSON object.")
            return data

        def _case_details(self, case_id: str) -> dict:
            folder, record = core.get_case(case_id)
            observations = reviews.apply(
                findings.extract(folder, record), reviews.load(folder)
            )
            return {
                "case": record,
                "findings": observations,
                "steps": findings.step_previews(folder, record),
                "graph": findings.graph_data(record, observations, _read_graph(folder)),
            }

        def do_GET(self):
            if not self._host_ok():
                return self._error(403, "Localhost access only.")
            path = urlsplit(self.path).path
            if path in ("/", "/index.html", "/app.js", "/styles.css",
                        "/network.html", "/network.js", "/network.css",
                        "/tools.html", "/tools.js", "/tools.css"):
                name = "index.html" if path == "/" else path.lstrip("/")
                file = STATIC / name
                if not file.is_file():
                    return self._error(404, "Static asset not found.")
                body = file.read_bytes()
                mime = {"index.html": "text/html", "app.js": "text/javascript",
                        "styles.css": "text/css", "network.html": "text/html",
                        "network.js": "text/javascript", "network.css": "text/css",
                        "tools.html": "text/html", "tools.js": "text/javascript",
                        "tools.css": "text/css"}[name] + "; charset=utf-8"
                self._headers(200, mime, len(body))
                return self.wfile.write(body)
            if path == "/api/tools":
                return self._send({"tools": tool_manager.catalog(),
                                   "platform": "linux" if tool_manager.sys.platform.startswith("linux") else "unsupported"})
            if path.startswith("/api/tools/jobs/"):
                job_id = path.removeprefix("/api/tools/jobs/")
                with state.lock:
                    job = state.install_jobs.get(job_id)
                    return self._send({"job": dict(job)} if job else {"error": "Install job not found."},
                                      200 if job else 404)
            if path == "/api/network-workspaces":
                return self._send({"workspaces": networks.list_workspaces()})
            if path == "/api/network-people":
                return self._send({"people": networks.list_people()})
            if path.startswith("/api/network-workspaces/"):
                parts = path.strip("/").split("/")
                if len(parts) == 3:
                    try:
                        return self._send(networks.workspace_view(parts[2]))
                    except networks.NetworkError:
                        return self._error(404, "Workspace not found.")
            if path.startswith("/api/network-people/"):
                parts = path.strip("/").split("/")
                if len(parts) == 4 and parts[3] == "memberships":
                    try:
                        return self._send({"memberships": networks.person_memberships(parts[2])})
                    except networks.NetworkError:
                        return self._error(404, "Person not found.")
            if path == "/api/session":
                return self._send({"token": state.token, "local_only": True})
            if path == "/api/cases":
                cases = []
                for case in core.list_cases()[:100]:
                    cases.append({
                        "id": case.get("id"), "target": case.get("target"),
                        "depth": case.get("depth"), "status": case.get("status"),
                        "created_at": case.get("created_at"),
                        "steps": len(case.get("steps", [])),
                        "leads": len(case.get("leads", [])),
                    })
                return self._send({"cases": cases})
            if path.startswith("/api/cases/"):
                fragments = path.split("/")
                if len(fragments) == 4:
                    try:
                        return self._send(self._case_details(fragments[3]))
                    except core.ReconductorError:
                        return self._error(404, "Case not found.")
            if path.startswith("/api/jobs/"):
                ident = path[len("/api/jobs/"):]
                with state.lock:
                    job = state.jobs.get(ident)
                    return self._send({"job": dict(job)} if job else {"error": "Job not found."},
                                      200 if job else 404)
            return self._error(404, "Not found.")

        def do_POST(self):
            if not self._host_ok():
                return self._error(403, "Localhost access only.")
            if not self._post_ok():
                return self._error(403, "Missing local session token or invalid origin.")
            try:
                body = self._json_body()
                path = urlsplit(self.path).path
                if path == "/api/tools/check":
                    return self._send(tool_manager.check_tool(body.get("tool")))
                if path == "/api/tools/install":
                    if body.get("acknowledge_changes") is not True or body.get("confirm") != "INSTALL":
                        return self._error(400, "Confirm third-party downloads and enter INSTALL.")
                    selected = tool_manager.validate_selection(body.get("tools"))
                    with state.lock:
                        if state.active_install or state.active_job:
                            return self._error(409, "Another installation or investigation is already running.")
                        install_id = uuid.uuid4().hex
                        state.install_jobs[install_id] = {
                            "id": install_id, "status": "running", "tools": selected,
                            "events": [], "results": [], "error": None,
                        }
                        state.active_install = install_id
                    thread = threading.Thread(
                        target=state.run_install, args=(install_id, selected),
                        name="reconductor-tool-install", daemon=True,
                    )
                    thread.start()
                    return self._send({"job_id": install_id}, 202)
                if path == "/api/network-workspaces":
                    with state.lock:
                        workspace = networks.create_workspace(body.get("name"), body.get("description", ""))
                    return self._send({"workspace": workspace}, 201)
                if path.startswith("/api/network-workspaces/"):
                    parts = path.strip("/").split("/")
                    if len(parts) == 4:
                        workspace_id, action = parts[2], parts[3]
                        with state.lock:
                            if action == "people":
                                workspace = networks.get_workspace(workspace_id)
                                if len(workspace["people"]) >= networks.MAX_PEOPLE:
                                    raise networks.NetworkError("Workspace person limit reached.")
                                person = networks.create_person(
                                    body.get("name"), body.get("details", "")
                                )
                                networks.attach_person(workspace_id, person["id"])
                                return self._send({"person": person}, 201)
                            if action == "members":
                                ws = networks.attach_person(workspace_id, body.get("person_id"))
                                return self._send({"workspace_id": ws["id"], "person_id": body.get("person_id")})
                            if action == "groups":
                                group = networks.create_group(
                                    workspace_id, body.get("name"),
                                    body.get("kind"), body.get("details", "")
                                )
                                return self._send({"group": group}, 201)
                            if action == "links":
                                edge = networks.create_link(
                                    workspace_id, body.get("source"), body.get("target"),
                                    body.get("type"), body.get("note", "")
                                )
                                return self._send({"edge": edge}, 201)
                            if action == "positions":
                                position = networks.set_position(
                                    workspace_id, body.get("node_id"),
                                    body.get("x"), body.get("y")
                                )
                                return self._send({"position": position})
                if path.startswith("/api/network-people/"):
                    parts = path.strip("/").split("/")
                    if len(parts) == 3:
                        with state.lock:
                            person = networks.update_person(parts[2], body.get("name"),
                                                            body.get("details", ""))
                        return self._send({"person": person})
                if path in ("/api/preview", "/api/jobs"):
                    clues = engine.normalize_clues(
                        names=body.get("names"), usernames=body.get("usernames"),
                        emails=body.get("emails"), domains=body.get("domains"),
                    )
                    depth = body.get("depth", "medium")
                    location = body.get("location") or None
                    plan = engine.preview(clues, depth, location)
                    if path == "/api/preview":
                        return self._send({"plan": plan})
                    if body.get("acknowledge_exposure") is not True or body.get("confirm") != "RUN":
                        return self._error(400, "Live research requires explicit network acknowledgment.")
                    with state.lock:
                        if state.active_job is not None or state.active_install is not None:
                            return self._error(409, "Another investigation or tool installation is running.")
                        job_id = uuid.uuid4().hex
                        state.jobs[job_id] = {
                            "id": job_id, "status": "running",
                            "case_id": None, "events": [], "error": None,
                        }
                        state.active_job = job_id
                    thread = threading.Thread(
                        target=state.run_job, args=(job_id, clues, depth, location),
                        name="reconductor-investigation", daemon=True,
                    )
                    thread.start()
                    return self._send({"job_id": job_id}, 202)
                if path.startswith("/api/cases/"):
                    parts = path.split("/")
                    if len(parts) != 5:
                        return self._error(404, "Unknown route.")
                    folder, record = core.get_case(parts[3])
                    action = parts[4]
                    with state.lock:
                        if action == "reviews":
                            change = reviews.set_review(
                                folder, body.get("finding_id"), body.get("decision"),
                                findings.extract(folder, record),
                            )
                            return self._send({"review": change})
                        annotations = _read_graph(folder)
                        if action == "people":
                            name = body.get("name")
                            note = body.get("note", "")
                            if (not isinstance(name, str) or not 1 <= len(name.strip()) <= 90
                                    or not isinstance(note, str) or len(note) > 500):
                                return self._error(400, "Name required (1–90 chars); note max 500.")
                            if len(annotations["people"]) >= 80:
                                return self._error(400, "Maximum manually added people reached.")
                            person = {"id": "person:" + uuid.uuid4().hex,
                                      "name": name.strip(), "note": note.strip()}
                            annotations["people"].append(person)
                            _save_graph(folder, annotations)
                            return self._send({"person": person}, 201)
                        if action == "links":
                            src, dst = body.get("source"), body.get("target")
                            label = body.get("label", "possible association")
                            if label not in ("possible association", "public association", "known contact"):
                                return self._error(400, "Unsupported relationship label.")
                            graph = findings.graph_data(
                                record, findings.extract(folder, record), annotations
                            )
                            ids = {node["id"] for node in graph["nodes"]}
                            if src not in ids or dst not in ids or src == dst:
                                return self._error(400, "Choose two different existing nodes.")
                            if len(annotations["links"]) >= 150:
                                return self._error(400, "Maximum user links reached.")
                            link = {"source": src, "target": dst, "label": label}
                            if link not in annotations["links"]:
                                annotations["links"].append(link)
                                _save_graph(folder, annotations)
                            return self._send({"link": link}, 201)
                return self._error(404, "Not found.")
            except (ValueError, TypeError, KeyError, core.ReconductorError, tool_manager.InstallError) as exc:
                return self._error(400, str(exc)[:300])
            except OSError:
                return self._error(500, "Unable to read or save local case.")

    return Handler


def serve(port: int = 8765, open_browser: bool = True) -> None:
    if not 1 <= port <= 65535:
        raise ValueError("Port must be from 1 to 65535.")
    tool_manager.ensure_user_path()
    state = DashboardState(port)
    server = ThreadingHTTPServer(("127.0.0.1", port), handler_for(state))
    server.daemon_threads = True
    url = f"http://127.0.0.1:{port}"
    print(f"Reconductor local dashboard: {url}")
    print("Bound to localhost only; not available on your LAN or the internet.")
    print("Press Ctrl+C to stop.")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
    finally:
        server.server_close()
