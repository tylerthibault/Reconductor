"""Planning, execution and case persistence. Python standard library only.

Reconductor does not anonymize network traffic, verify identity matches, or
perform active scanning. External tools run with the user's existing network.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from . import __version__

TOOLS = {
    "sherlock": "Public username search",
    "maigret": "Public username search",
    "spiderfoot": "Passive domain OSINT",
    "theHarvester": "Public domain-source discovery",
    "exiftool": "Local file metadata inspection",
}
DEPTH_TIMEOUTS = {"light": 120, "medium": 300, "deep": 900}
CASE_ID_PATTERN = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}$")
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
DOMAIN_PATTERN = re.compile(
    r"^(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z](?:[a-z0-9-]{0,61}[a-z0-9])$",
    re.IGNORECASE,
)


class ReconductorError(Exception):
    """A user-facing validation, execution, or case error."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def home() -> Path:
    base = Path(os.environ.get("RECONDUCTOR_HOME", "~/.local/share/reconductor")).expanduser()
    return base.resolve()


def cases_root() -> Path:
    return home() / "cases"


def validate_target(kind: str, raw: str) -> str:
    if kind == "username":
        if not USERNAME_PATTERN.fullmatch(raw):
            raise ReconductorError("Username must be 1–64 characters: letters, numbers, _, -, or .; start with a letter or number.")
        return raw
    if kind == "domain":
        try:
            domain = raw.rstrip(".").encode("idna").decode("ascii").lower()
        except UnicodeError as exc:
            raise ReconductorError("Invalid internationalized domain.") from exc
        if not DOMAIN_PATTERN.fullmatch(domain):
            raise ReconductorError("Provide a domain such as example.org, not a URL, IP, or shell command.")
        return domain
    if kind == "file":
        p = Path(raw).expanduser().resolve()
        if not p.is_file():
            raise ReconductorError("Local file does not exist or is not a regular file.")
        return str(p)
    raise ReconductorError(f"Unsupported target type: {kind}")


def plan(kind: str, target: str, depth: str) -> list[dict[str, Any]]:
    if depth not in DEPTH_TIMEOUTS:
        raise ReconductorError(f"Unsupported depth: {depth}")
    target = validate_target(kind, target)
    timeout = DEPTH_TIMEOUTS[depth]
    tasks: list[dict[str, Any]] = []
    if kind == "username":
        tasks.append({"tool": "sherlock", "argv": ["sherlock", target], "timeout": timeout, "network": True})
        if depth != "light":
            tasks.append({"tool": "maigret", "argv": ["maigret", target, "--no-recursion", "--no-autoupdate"], "timeout": timeout, "network": True})
    elif kind == "domain":
        # SpiderFoot passive preset is NOT a VPN or guarantee of no target requests.
        tasks.append({"tool": "spiderfoot", "argv": ["spiderfoot", "-s", target, "-u", "passive", "-o", "json"], "timeout": timeout, "network": True})
        if depth != "light":
            tasks.append({"tool": "theHarvester", "argv": ["theHarvester", "-d", target, "-b", "crtsh,certspotter"], "timeout": timeout, "network": True})
    elif kind == "file":
        tasks.append({"tool": "sha256", "argv": [], "timeout": timeout, "network": False})
        if depth != "light":
            tasks.append({"tool": "exiftool", "argv": ["exiftool", "-json", target], "timeout": timeout, "network": False})
    return tasks


def tools_available() -> list[dict[str, str | bool]]:
    return [
        {"tool": name, "description": desc, "available": bool(shutil.which(name)),
         "path": shutil.which(name) or ""}
        for name, desc in TOOLS.items()
    ]


def preview(tasks: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"  {item['tool']} [{item['timeout']}s] " +
        ("(internal SHA-256)" if item["tool"] == "sha256" else shlex.join(item["argv"]))
        for item in tasks
    )


def _new_case(kind: str, target: str, depth: str) -> tuple[Path, dict[str, Any]]:
    root = cases_root()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    case_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    folder = root / case_id
    folder.mkdir(mode=0o700)
    (folder / "raw").mkdir(mode=0o700)
    record: dict[str, Any] = {
        "schema_version": 1, "app_version": __version__, "id": case_id,
        "target_type": kind, "target": target, "depth": depth,
        "created_at": utc_now(), "finished_at": None,
        "status": "running", "steps": [],
        "warning": "Raw tool output is unverified. No VPN/anonymity is provided by Reconductor.",
    }
    return folder, record


def _write_private(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    os.chmod(path, 0o600)


def _persist(folder: Path, record: dict[str, Any]) -> None:
    tmp = folder / ".case.json.tmp"
    _write_private(tmp, json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, folder / "case.json")


def _run_tool(
    argv: list[str], cwd: Path, timeout: int, *,
    on_tick=None, tick_seconds: float = 5.0,
) -> tuple[int, str, str, str]:
    """Run a tool without a shell; optionally report elapsed time while waiting.

    Communicate() still drains stdout/stderr, so noisy tools cannot deadlock.
    A timeout or interruption terminates the entire subprocess group.
    """
    proc = subprocess.Popen(
        argv, cwd=str(cwd), stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, errors="replace", start_new_session=True,
    )
    started = time.monotonic()
    try:
        if on_tick is None:
            stdout, stderr = proc.communicate(timeout=timeout)
            return proc.returncode, stdout, stderr, "completed"
        deadline = started + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(argv, timeout)
            try:
                stdout, stderr = proc.communicate(timeout=min(max(tick_seconds, 0.01), remaining))
                return proc.returncode, stdout, stderr, "completed"
            except subprocess.TimeoutExpired:
                if time.monotonic() >= deadline:
                    raise
                on_tick(time.monotonic() - started)
    except subprocess.TimeoutExpired:
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        stdout, stderr = proc.communicate()
        return 124, stdout, stderr, "timeout"
    except BaseException:
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        proc.communicate()
        raise


def execute(
    kind: str, raw_target: str, depth: str, *,
    acknowledge_exposure: bool = False, on_progress=None,
) -> tuple[Path, dict[str, Any]]:
    target = validate_target(kind, raw_target)
    tasks = plan(kind, target, depth)
    if any(step["network"] for step in tasks) and not acknowledge_exposure:
        raise ReconductorError(
            "Network scans require --acknowledge-exposure. This does NOT enable VPN, Tor, DNS leak protection, or a kill switch."
        )
    folder, record = _new_case(kind, target, depth)
    _persist(folder, record)
    if on_progress:
        on_progress({"event": "case_started", "case_id": record["id"], "maximum": len(tasks)})
    try:
        for index, task in enumerate(tasks, 1):
            tool = task["tool"]
            step: dict[str, Any] = {
                "tool": tool, "command": task["argv"], "started_at": utc_now(),
                "ended_at": None, "state": "pending", "exit_code": None,
                "stdout_file": None, "stderr_file": None, "duration_seconds": None,
            }
            record["steps"].append(step)
            _persist(folder, record)
            if on_progress:
                on_progress({"event": "step_started", "tool": tool, "index": index,
                             "maximum": len(tasks), "timeout": task["timeout"]})
            started = time.monotonic()
            out, err = "", ""
            if tool != "sha256" and not shutil.which(tool):
                step["state"] = "skipped_missing"
                err = f"Tool '{tool}' was not found on PATH.\n"
            elif tool == "sha256":
                digest = hashlib.sha256()
                with Path(target).open("rb") as src:
                    for chunk in iter(lambda: src.read(1024 * 1024), b""):
                        digest.update(chunk)
                out = f"SHA-256 ({target}) = {digest.hexdigest()}\n"
                step["state"] = "completed"
                step["exit_code"] = 0
            else:
                try:
                    run_options = {}
                    if on_progress:
                        run_options["on_tick"] = lambda elapsed: on_progress({
                            "event": "heartbeat", "tool": tool,
                            "elapsed": elapsed, "timeout": task["timeout"],
                        })
                    rc, out, err, state = _run_tool(
                        task["argv"], folder / "raw", int(task["timeout"]), **run_options
                    )
                    step["exit_code"] = rc
                    step["state"] = "completed" if rc == 0 else ("timeout" if state == "timeout" else "failed")
                except OSError as exc:
                    err = str(exc)
                    step["state"] = "failed"
            stem = f"{index:02d}-{tool.lower()}"
            stdout_file = folder / "raw" / f"{stem}.stdout.txt"
            stderr_file = folder / "raw" / f"{stem}.stderr.txt"
            _write_private(stdout_file, out)
            _write_private(stderr_file, err)
            step["stdout_file"] = str(stdout_file.relative_to(folder))
            step["stderr_file"] = str(stderr_file.relative_to(folder))
            step["duration_seconds"] = round(time.monotonic() - started, 2)
            step["ended_at"] = utc_now()
            _persist(folder, record)
            if on_progress:
                on_progress({"event": "step_finished", "tool": tool, "index": index,
                             "state": step["state"], "duration": step["duration_seconds"]})
    except (KeyboardInterrupt, Exception):
        record["status"] = "interrupted"
        record["finished_at"] = utc_now()
        _persist(folder, record)
        write_report(folder, record)
        raise

    completed = sum(s["state"] == "completed" for s in record["steps"])
    record["status"] = ("completed" if completed == len(record["steps"])
                        else "partial" if completed else "no_results")
    record["finished_at"] = utc_now()
    _persist(folder, record)
    write_report(folder, record)
    if on_progress:
        on_progress({"event": "case_finished", "case_id": record["id"],
                     "status": record["status"]})
    return folder, record


def write_report(folder: Path, record: dict[str, Any]) -> None:
    lines = [
        f"# Reconductor Case {record['id']}", "",
        f"- Target type: {record['target_type']}",
        f"- Target: {record['target']}",
        f"- Depth: {record['depth']}",
        f"- Status: {record['status']}",
        f"- Started (UTC): {record['created_at']}",
        f"- Finished (UTC): {record['finished_at']}", "",
        "## Tool execution", "",
        "| Tool | Status | Exit code | Raw output |",
        "| --- | --- | --- | --- |",
    ]
    for step in record["steps"]:
        lines.append(f"| {step['tool']} | {step['state']} | {step['exit_code']} | {step['stdout_file']} |")
    lines.extend([
        "", "## Interpretation", "",
        "This is an **execution report**, not a verified background check. Review the",
        "raw output and independently corroborate any possible identity matches.",
        "Missing, blocked, or timed-out results do not prove absence of information.",
        "", "## Privacy", "",
        "Reconductor did not provide network anonymity or leak protection.",
        "All output was stored locally in this case directory.", "",
    ])
    _write_private(folder / "report.md", "\n".join(lines))


def get_case(case_id: str) -> tuple[Path, dict[str, Any]]:
    if not CASE_ID_PATTERN.fullmatch(case_id):
        raise ReconductorError("Invalid case ID.")
    folder = cases_root() / case_id
    try:
        data = json.loads((folder / "case.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError) as exc:
        raise ReconductorError("Case not found or its case.json is unreadable.") from exc
    return folder, data


def list_cases() -> list[dict[str, Any]]:
    root = cases_root()
    if not root.is_dir():
        return []
    found = []
    for folder in sorted(root.iterdir(), reverse=True):
        if folder.is_dir() and CASE_ID_PATTERN.fullmatch(folder.name):
            try:
                _, case = get_case(folder.name)
                found.append(case)
            except ReconductorError:
                continue
    return found
