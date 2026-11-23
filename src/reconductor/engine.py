"""Bounded, deterministic investigation engine for Reconductor.

All network execution requires explicit opt-in. Discovery comes exclusively from
recognized structured SpiderFoot events; no text scraping or automatic identity joins.
"""
from __future__ import annotations

from collections import deque
import json
import re
import shutil
import time
from pathlib import Path
from typing import Any

from . import core

NAME_RE = re.compile(r"^[^<>\x00-\x1f]{3,160}$")
EMAIL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._%+\-]{0,63}@[^@\s]+$")
BUDGETS = {
    "light": {"tasks": 2, "leads": 0, "hops": 0},
    "medium": {"tasks": 8, "leads": 3, "hops": 1},
    "deep": {"tasks": 16, "leads": 8, "hops": 2},
}
COVERAGE = {
    "digital_footprint": "Partial: available local tools; individual sources vary",
    "business_records": "Not searched: no jurisdiction adapter installed",
    "property_records": "Not searched: no jurisdiction adapter installed",
    "court_records": "Not searched: no jurisdiction adapter installed",
}


def normalize(kind: str, raw: str) -> str:
    """Validate a provided clue or candidate without invoking a shell."""
    if not isinstance(raw, str):
        raise core.ReconductorError("Clues must be strings.")
    raw = raw.strip()
    if kind in ("username", "domain"):
        return core.validate_target(kind, raw)
    if kind == "name":
        if not NAME_RE.fullmatch(raw) or len(raw.split()) < 2 or not any(ch.isalpha() for ch in raw):
            raise core.ReconductorError("Provide a first and last name, up to 160 characters.")
        return " ".join(raw.split())
    if kind == "email":
        if not EMAIL_RE.fullmatch(raw) or len(raw) > 254:
            raise core.ReconductorError("Invalid email clue.")
        local, domain = raw.rsplit("@", 1)
        return local + "@" + core.validate_target("domain", domain)
    raise core.ReconductorError(f"Unsupported clue type: {kind}")


def normalize_clues(
    names: list[str] | None = None,
    usernames: list[str] | None = None,
    emails: list[str] | None = None,
    domains: list[str] | None = None,
) -> list[dict[str, Any]]:
    clues: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for kind, values in (
        ("name", names or []),
        ("username", usernames or []),
        ("email", emails or []),
        ("domain", domains or []),
    ):
        for value in values:
            normalized = normalize(kind, value)
            key = (kind, normalized.casefold())
            if key not in seen:
                seen.add(key)
                clues.append({
                    "kind": kind, "value": normalized, "hops": 0,
                    "origin": "operator", "status": "operator_supplied",
                })
    if not clues:
        raise core.ReconductorError("Supply at least one --name, --username, --email, or --domain.")
    return clues


def tasks_for(clue: dict[str, Any], depth: str) -> list[dict[str, Any]]:
    kind, value = clue["kind"], clue["value"]
    timeout = core.DEPTH_TIMEOUTS[depth]
    if kind in ("name", "email"):
        return [{"tool": "spiderfoot", "argv": ["spiderfoot", "-s", value, "-u", "passive", "-o", "json"],
                 "timeout": timeout, "network": True}]
    return core.plan(kind, value, depth)


def preview(clues: list[dict[str, Any]], depth: str, location: str | None = None) -> str:
    if depth not in BUDGETS:
        raise core.ReconductorError("Depth must be light, medium, or deep.")
    lines = ["Initial research plan (new leads may be discovered only during execution):"]
    max_tasks = BUDGETS[depth]["tasks"]
    count = 0
    for clue in clues:
        if count >= max_tasks:
            break
        lines.append(f"  {clue['kind']}: {clue['value']}")
        for task in tasks_for(clue, depth):
            if count >= max_tasks:
                break
            lines.append("    " + core.preview([task]).strip())
            count += 1
    lines.append(f"Budget: {max_tasks} tool runs; {BUDGETS[depth]['leads']} discovered leads; {BUDGETS[depth]['hops']} follow-up hops")
    if location:
        lines.append("Location is contextual only; geographic record adapters are not installed.")
    lines.append("No worldwide business, property, or court record searches in this release.")
    return "\n".join(lines)


def _spiderfoot_candidates(raw: str, clue: dict[str, Any], output_ref: str, limit: int) -> list[dict[str, Any]]:
    """Only exact event classes may generate bounded unverified research leads.

    SpiderFoot's CLI JSON is a list of event dicts. Its 'type' contains a
    human-readable event label, so accept narrowly defined names only.
    """
    if not raw or limit <= 0:
        return []
    try:
        events = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(events, list):
        return []
    found: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for event in events[:2000]:
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("type", "")).strip().casefold()
        data = event.get("data")
        if not isinstance(data, str):
            continue
        kind = None
        if event_type in ("username", "user name"):
            kind = "username"
        elif clue["kind"] == "domain" and event_type in ("internet name", "internet hostname", "hostname", "internet_name"):
            kind = "domain"
        if kind is None:
            continue
        try:
            value = normalize(kind, data)
        except core.ReconductorError:
            continue
        if kind == "domain":
            # No automatic pivot outside the operator-supplied domain.
            original_domain = clue["value"]
            if not value.endswith("." + original_domain):
                continue
        key = (kind, value.casefold())
        if key in seen or (kind == clue["kind"] and value.casefold() == clue["value"].casefold()):
            continue
        seen.add(key)
        found.append({
            "kind": kind, "value": value, "hops": clue["hops"] + 1,
            "origin": output_ref, "status": "unverified_candidate",
            "source_tool": "spiderfoot",
            "source_module": str(event.get("module", ""))[:120],
            "source_reference": str(event.get("source", ""))[:300],
        })
        if len(found) >= limit:
            break
    return found


def _dossier(folder: Path, record: dict[str, Any]) -> None:
    lines = [
        f"# Reconductor Investigation {record['id']}", "",
        f"**Status:** {record['status']}  ",
        f"**Depth:** {record['depth']}  ",
        f"**Location context:** {record.get('location') or 'Not provided'}  ",
        "**Identity conclusion:** Not established by automated searches", "",
        "## Starting clues", "",
    ]
    for clue in record["clues"]:
        lines.append(f"- {clue['kind']}: {clue['value']}")
    lines.extend(["", "## Discovered leads (NOT verified identities)", ""])
    if record["leads"]:
        for lead in record["leads"]:
            lines.append(f"- {lead['kind']}: {lead['value']} — {lead['status']}; evidence: {lead['origin']}")
    else:
        lines.append("No supported structured leads were extracted.")
    lines.extend(["", "## Tool execution", "",
                  "| Tool | Clue | Result | Raw evidence |",
                  "| --- | --- | --- | --- |"])
    for step in record["steps"]:
        lines.append(f"| {step['tool']} | {step['clue_kind']} | {step['state']} | {step['stdout_file']} |")
    lines.extend(["", "## Geographic coverage and record categories", ""])
    for kind, status in record["coverage"].items():
        lines.append(f"- **{kind.replace('_', ' ').title()}:** {status}")
    lines.extend([
        "", "## Caveats", "",
        "- Potentially matching usernames and profiles are **not** verified as belonging to the subject.",
        "- Raw results may contain incorrect, stale, or third-party information; corroborate manually.",
        "- No automated criminal-record conclusions or judgments are generated.",
        "- Exact residential addresses, full birth dates, and other sensitive details are not extracted into this dossier.",
        "- Country-specific business, property and court adapters are not yet implemented.",
        "- Outbound requests use this machine's current network; no VPN, Tor or kill switch is supplied.",
        "", "## Investigation limits", "",
        f"- Tool executions: {len(record['steps'])}/{record['budget']['tasks']}",
        f"- New candidate leads: {len(record['leads'])}/{record['budget']['leads']}",
        "",
    ])
    core._write_private(folder / "dossier.md", "\n".join(lines))
    core._write_private(folder / "report.md", "\n".join(lines))


def run(
    clues: list[dict[str, Any]], depth: str, *,
    location: str | None = None, acknowledge_exposure: bool = False,
    on_progress=None,
) -> tuple[Path, dict[str, Any]]:
    if depth not in BUDGETS:
        raise core.ReconductorError("Unsupported depth.")
    if not acknowledge_exposure:
        raise core.ReconductorError(
            "Network research requires --acknowledge-exposure; this does not enable a VPN or other anonymity controls."
        )
    if location is not None and (len(location) > 160 or any(ord(ch) < 32 for ch in location)):
        raise core.ReconductorError("Location is too long or contains control characters.")
    budget = BUDGETS[depth].copy()
    folder, record = core._new_case("investigation", ", ".join(x["value"] for x in clues)[:300], depth)
    record.update({
        "clues": clues, "leads": [], "location": location,
        "coverage": COVERAGE.copy(), "budget": budget,
    })
    core._persist(folder, record)
    if on_progress:
        on_progress({"event": "case_started", "case_id": record["id"],
                     "maximum": budget["tasks"]})
    queue = deque(clues)
    seen_clues: set[tuple[str, str]] = set()
    seen_tasks: set[tuple[str, str, str]] = set()
    try:
        while queue and len(record["steps"]) < budget["tasks"]:
            clue = queue.popleft()
            key = (clue["kind"], clue["value"].casefold())
            if key in seen_clues:
                continue
            seen_clues.add(key)
            for task in tasks_for(clue, depth):
                if len(record["steps"]) >= budget["tasks"]:
                    break
                task_key = (task["tool"], *key)
                if task_key in seen_tasks:
                    continue
                seen_tasks.add(task_key)
                tool = task["tool"]
                index = len(record["steps"]) + 1
                stem = f"{index:02d}-{tool.lower()}"
                rel_stdout = f"raw/{stem}.stdout.txt"
                rel_stderr = f"raw/{stem}.stderr.txt"
                step = {
                    "tool": tool, "clue_kind": clue["kind"], "clue": clue["value"],
                    "origin": clue["origin"], "state": "pending",
                    "command": task["argv"], "started_at": core.utc_now(),
                    "ended_at": None, "exit_code": None, "duration_seconds": None,
                    "stdout_file": rel_stdout, "stderr_file": rel_stderr,
                }
                record["steps"].append(step)
                core._persist(folder, record)
                if on_progress:
                    on_progress({"event": "step_started", "tool": tool, "index": index,
                                 "maximum": budget["tasks"], "timeout": task["timeout"]})
                started = time.monotonic()
                stdout, stderr = "", ""
                if not shutil.which(tool):
                    step["state"] = "skipped_missing"
                    stderr = f"{tool} not found on PATH"
                else:
                    try:
                        run_options = {}
                        if on_progress:
                            run_options["on_tick"] = lambda elapsed: on_progress({
                                "event": "heartbeat", "tool": tool,
                                "elapsed": elapsed, "timeout": task["timeout"],
                            })
                        rc, stdout, stderr, status = core._run_tool(
                            task["argv"], folder / "raw", int(task["timeout"]), **run_options
                        )
                        step["exit_code"] = rc
                        step["state"] = "completed" if rc == 0 else ("timeout" if status == "timeout" else "failed")
                    except OSError as exc:
                        stderr = str(exc)
                        step["state"] = "failed"
                core._write_private(folder / rel_stdout, stdout)
                core._write_private(folder / rel_stderr, stderr)
                step["duration_seconds"] = round(time.monotonic() - started, 2)
                step["ended_at"] = core.utc_now()
                if (tool == "spiderfoot" and step["state"] == "completed"
                        and clue["hops"] < budget["hops"] and len(record["leads"]) < budget["leads"]):
                    remaining = budget["leads"] - len(record["leads"])
                    for candidate in _spiderfoot_candidates(stdout, clue, rel_stdout, remaining):
                        candidate_key = (candidate["kind"], candidate["value"].casefold())
                        if candidate_key in seen_clues or any(
                            (item["kind"], item["value"].casefold()) == candidate_key for item in queue
                        ):
                            continue
                        record["leads"].append(candidate)
                        queue.append(candidate)
                        if on_progress:
                            on_progress({"event": "lead_discovered", "kind": candidate["kind"],
                                         "count": len(record["leads"]), "maximum": budget["leads"]})
                core._persist(folder, record)
                if on_progress:
                    on_progress({"event": "step_finished", "tool": tool,
                                 "index": index, "state": step["state"],
                                 "duration": step["duration_seconds"]})
    except BaseException:
        record["status"] = "interrupted"
        record["finished_at"] = core.utc_now()
        core._persist(folder, record)
        _dossier(folder, record)
        raise
    successes = sum(step["state"] == "completed" for step in record["steps"])
    record["status"] = (
        "completed" if successes == len(record["steps"]) and successes > 0
        else "partial" if successes else "no_results"
    )
    record["finished_at"] = core.utc_now()
    core._persist(folder, record)
    _dossier(folder, record)
    if on_progress:
        on_progress({"event": "case_finished", "case_id": record["id"],
                     "status": record["status"]})
    return folder, record
