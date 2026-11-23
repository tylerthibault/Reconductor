"""Read only existing local case output and derive reviewable evidence.

No identity attribution is performed. Parsing a tool's mention of a profile
never makes that profile the subject's verified account.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit, urlunsplit
from typing import Any

from . import core
from . import markdown_store as store

MAX_TEXT = 1_500_000
MAX_EVENTS = 350
MAX_FINDINGS = 150
URL_RE = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)
KEYWORDS = ("username", "user name", "profile", "account", "domain", "internet name", "website", "url", "social")
SENSITIVE = ("password", "address", "phone", "date of birth", "ssn", "credit card", "private", "credential")

SFURL_RE = re.compile(r"<SFURL>\s*(https?://[^<\s]+)\s*</SFURL>", re.IGNORECASE)
CATEGORY_RE = re.compile(r"\s*\(Category:\s*([^)]+)\)", re.IGNORECASE)


def _display_fields(typ: str, raw: str) -> dict[str, str | None]:
    """Convert tool-specific markers into labels, without making identity claims."""
    name = typ.casefold().strip()
    tag = SFURL_RE.search(raw)
    url = _url(tag.group(1)) if tag else (_url(raw) if raw.startswith(("https://", "http://")) else None)
    cleaned = re.sub(r"<SFURL>.*?</SFURL>", "", raw, flags=re.IGNORECASE | re.DOTALL).strip()
    category = CATEGORY_RE.search(cleaned)
    site_category = category.group(1).strip()[:60] if category else ""
    cleaned = CATEGORY_RE.sub("", cleaned).strip().strip(":-").strip()
    if "account on external site" in name or "social media profile" in name:
        site = cleaned or (urlsplit(url).hostname if url else "Unidentified website")
        return {
            "category": "profile", "display_name": site[:100],
            "description": (site_category.capitalize() + " category" if site_category else "Public profile candidate"),
            "url": url,
        }
    if "username" in name or "user name" in name:
        return {
            "category": "username", "display_name": cleaned[:100],
            "description": "A username observed by a research tool",
            "url": url,
        }
    if name == "reported public url":
        host = urlsplit(url).hostname if url else None
        return {
            "category": "profile", "display_name": (host or "Reported URL")[:100],
            "description": "Public URL mentioned in tool output",
            "url": url,
        }
    return {
        "category": "other", "display_name": cleaned[:100],
        "description": typ[:100],
        "url": url,
    }



def _text(folder: Path, relative: str | None, limit: int = MAX_TEXT) -> str:
    if not relative or not isinstance(relative, str):
        return ""
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or len(path.parts) != 2 or path.parts[0] != "raw":
        return ""
    resolved = (folder / path).resolve()
    if folder.resolve() not in resolved.parents or not resolved.is_file():
        return ""
    try:
        return store.read_capture(resolved, limit)
    except (OSError, ValueError):
        return ""


def _url(value: str) -> str | None:
    candidate = value.strip().rstrip(".,;)]}'")
    if len(candidate) > 1600:
        return None
    try:
        parts = urlsplit(candidate)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return None
        if parts.username or parts.password:
            return None
        # Do not display secret-bearing query strings or fragments.
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    except ValueError:
        return None


def _identifier(*items: str) -> str:
    return hashlib.sha256("|".join(items).encode("utf-8", "replace")).hexdigest()[:20]


def extract(folder: Path, record: dict[str, Any]) -> list[dict[str, Any]]:
    """Conservatively show tool observations, without assuming common identity."""
    findings: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    def add(tool: str, typ: str, value: str, ref: str, source: str = "") -> None:
        if not isinstance(value, str) or not value.strip() or len(findings) >= MAX_FINDINGS:
            return
        if any(word in typ.casefold() for word in SENSITIVE):
            return
        value = value.strip()[:500]
        display = _display_fields(typ, value)
        url = display["url"]
        key = (tool, typ.casefold(), (url or value).casefold())
        if key in seen:
            return
        seen.add(key)
        findings.append({
            "id": "finding:" + _identifier(tool, typ, url or value),
            "type": typ[:80], "value": value, "url": url,
            "display_name": display["display_name"],
            "description": display["description"],
            "category": display["category"],
            "tool": tool, "evidence": ref, "source": source[:300],
            "verification": "unverified", "basis": "tool_observation",
        })

    for step in record.get("steps", [])[:30]:
        tool = step.get("tool", "")
        ref = step.get("stdout_file", "")
        raw = _text(folder, ref)
        if not raw:
            continue
        if tool == "spiderfoot":
            try:
                data = json.loads(raw)
            except (TypeError, ValueError):
                data = []
            if isinstance(data, list):
                for event in data[:MAX_EVENTS]:
                    if not isinstance(event, dict):
                        continue
                    typ = str(event.get("type", ""))
                    value = event.get("data", "")
                    if not isinstance(value, str) or len(value) > 500:
                        continue
                    if any(word in typ.casefold() for word in KEYWORDS):
                        add(tool, typ, value, ref, str(event.get("source", "")))
                    elif value.startswith(("https://", "http://")) and any(word in typ.casefold() for word in ("link", "site")):
                        add(tool, "Public link", value, ref, str(event.get("source", "")))
        elif tool in ("maigret", "sherlock"):
            for match in URL_RE.finditer(raw[:MAX_TEXT]):
                url = _url(match.group(0))
                if url:
                    add(tool, "Reported public URL", url, ref)
                if len(findings) >= MAX_FINDINGS:
                    break
    return findings


def step_previews(folder: Path, record: dict[str, Any]) -> list[dict[str, Any]]:
    output = []
    for step in record.get("steps", [])[:40]:
        output.append({
            "tool": step.get("tool", "?"),
            "state": step.get("state", "?"),
            "exit_code": step.get("exit_code"),
            "duration_seconds": step.get("duration_seconds"),
            "clue": step.get("clue", ""),
            "stdout_file": step.get("stdout_file"),
            "stderr_file": step.get("stderr_file"),
            "stdout": _text(folder, step.get("stdout_file"), 4500),
            "stderr": _text(folder, step.get("stderr_file"), 4500),
        })
    return output


def load_annotations(folder: Path) -> dict[str, Any]:
    try:
        return store.load_graph(folder)
    except (FileNotFoundError, ValueError, OSError):
        return {"people": [], "links": []}


def graph_data(record: dict[str, Any], findings: list[dict[str, Any]], annotations: dict[str, Any]) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    ids: set[str] = set()

    def node(id: str, label: str, kind: str, status: str, **kwargs: Any) -> None:
        if id in ids:
            return
        ids.add(id)
        nodes.append({"id": id, "label": label[:90], "kind": kind, "status": status, **kwargs})

    def edge(src: str, dst: str, label: str, status: str) -> None:
        if src in ids and dst in ids and src != dst:
            edges.append({"source": src, "target": dst, "label": label, "status": status})

    root = "case:root"
    names = [x.get("value", "") for x in record.get("clues", []) if x.get("kind") == "name"]
    node(root, names[0] if names else record.get("target", "Investigation"), "subject", "operator_supplied")
    for clue in record.get("clues", [])[:16]:
        id = "clue:" + _identifier(str(clue.get("kind")), str(clue.get("value")))
        node(id, str(clue.get("value", "")), "clue", "operator_supplied", source="Operator")
        edge(root, id, "supplied clue", "operator_supplied")
    for lead in record.get("leads", [])[:35]:
        id = "lead:" + _identifier(str(lead.get("kind")), str(lead.get("value")))
        node(id, str(lead.get("value", "")), "lead", "unverified", evidence=lead.get("origin", ""))
        edge(root, id, "possible lead", "unverified")
    for finding in findings[:80]:
        node(finding["id"], finding.get("display_name") or finding.get("value", ""), "finding", "unverified",
             evidence=finding.get("evidence"), url=finding.get("url"), tool=finding.get("tool"))
        edge(root, finding["id"], "tool observation", "unverified")
    for person in annotations.get("people", [])[:80]:
        if isinstance(person, dict) and isinstance(person.get("id"), str):
            node(person["id"], str(person.get("name", "Person")), "person", "user_added",
                 note=str(person.get("note", ""))[:500])
    for link in annotations.get("links", [])[:150]:
        if isinstance(link, dict):
            edge(str(link.get("source")), str(link.get("target")),
                 str(link.get("label", "possible association"))[:80], "user_added")
    return {"nodes": nodes, "edges": edges,
            "disclaimer": "Graph edges represent supplied clues, tool observations, or user-entered associations—not verified identities."}
