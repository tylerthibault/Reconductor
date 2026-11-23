"""Independent Markdown relationship workspaces with shared person profiles.

This module is intentionally separate from the OSINT case engine. All edges are
explicit, user-entered assertions and are scoped to one workspace. Sharing a
person profile never imports relationships from another workspace.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from . import core
from . import markdown_store as md

IDENT = re.compile(r"^(w|p|g|r)-[0-9a-f]{32}$")
GROUP_TYPES = ("family", "organization", "workplace", "school", "community", "other")
RELATIONS = ("connected to", "member of", "works at", "attends", "volunteers at",
             "friend of", "related to", "knows", "coworker of", "other")
MAX_PEOPLE = 250
MAX_GROUPS = 100
MAX_EDGES = 800


class NetworkError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _text(value: Any, field: str, length: int, required: bool = True) -> str:
    if not isinstance(value, str):
        raise NetworkError(f"{field} must be text.")
    result = value.strip()
    if (required and not result) or len(result) > length or any(ord(c) < 32 for c in result):
        raise NetworkError(f"{field} must be {'1–' if required else '0–'}{length} characters on one line.")
    return result


def _id(value: Any, prefix: str) -> str:
    if not isinstance(value, str) or not IDENT.fullmatch(value) or not value.startswith(prefix + "-"):
        raise NetworkError(f"Invalid {prefix} identifier.")
    return value


def root() -> Path:
    return core.home() / "networks"


def _workspace_path(workspace_id: str) -> Path:
    return root() / "Workspaces" / _id(workspace_id, "w") / "Workspace.md"


def _person_path(person_id: str) -> Path:
    return root() / "People" / (_id(person_id, "p") + ".md")


def _load(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise NetworkError(f"{label} not found.")
    try:
        data = md.parse_block(path)
    except (ValueError, OSError) as exc:
        raise NetworkError(f"Cannot read {label} Markdown state.") from exc
    return data


def _save_person(person: dict[str, Any]) -> None:
    name = md.safe(person["name"])
    text = [
        "---", "reconductor: shared-person", "format: markdown-v1", "---", "",
        "# " + name, "",
        "> [!note] Shared profile. Updating this person changes their display in every network workspace.", "",
        "**Display name:** " + name, "",
        "## Shared profile notes", "",
        md.safe(person.get("details", "")) or "No shared notes.", "",
        "## Application state", "",
        "This file's structured block is managed by Reconductor.", "",
        md.block(person), "",
    ]
    md.write_private(_person_path(person["id"]), "\n".join(text))


def _save_workspace(ws: dict[str, Any]) -> None:
    folder = _workspace_path(ws["id"]).parent
    lines = [
        "---", "reconductor: relationship-workspace", "format: markdown-v1", "---", "",
        "# " + md.safe(ws["name"]), "",
        "**Purpose:** " + (md.safe(ws.get("description", "")) or "Not specified"), "",
        "> [!warning] Connections are user-entered. People sharing an organization are not necessarily acquainted.", "",
        "## People in this workspace", "",
    ]
    for person_id in ws["people"]:
        person = get_person(person_id)
        lines.append("- [[People/" + person_id + "|" + md.safe(person["name"]) + "]]")
    if not ws["people"]:
        lines.append("No people added yet.")
    lines.extend(["", "## Local groups", ""])
    for group in ws["groups"]:
        lines.append("- [[Workspaces/" + ws["id"] + "/Groups/" + group["id"] + "|" +
                     md.safe(group["name"]) + "]] (" + group["kind"] + ")")
    if not ws["groups"]:
        lines.append("No groups added yet.")
    lines.extend(["", "## Relationships", "",
                  "See [[Workspaces/" + ws["id"] + "/Graph|Network graph notes]].", "",
                  "## Application state", "",
                  "Reconductor manages the structured state below. Keep it intact if editing this note.", "",
                  md.block(ws), ""])
    md.write_private(folder / "Workspace.md", "\n".join(lines))

    by_id = {g["id"]: g["name"] for g in ws["groups"]}
    by_id.update({p: get_person(p)["name"] for p in ws["people"]})
    graph = ["# Relationship graph — " + md.safe(ws["name"]), "",
             "> [!warning] These are only explicitly entered links, not verified identity matches.", "",
             "## People", ""]
    for person_id in ws["people"]:
        graph.append("- [[People/" + person_id + "|" + md.safe(by_id[person_id]) + "]]")
    graph.extend(["", "## Organizations and other groups", ""])
    for group in ws["groups"]:
        group_path = folder / "Groups" / (group["id"] + ".md")
        # Group notes are workspace-local, not shared across workspaces.
        if not group_path.exists():
            md.write_private(group_path, "\n".join([
                "# " + md.safe(group["name"]), "",
                "**Type:** " + group["kind"], "",
                "**Notes:** " + md.safe(group.get("details", "")), "",
                "[[Workspaces/" + ws["id"] + "/Workspace|Back to workspace]]", "",
            ]))
        graph.append("- [[Workspaces/" + ws["id"] + "/Groups/" + group["id"] +
                     "|" + md.safe(group["name"]) + "]]")
    graph.extend(["", "## Explicit relationships", ""])
    for relation in ws["edges"]:
        src, dst = relation["source"], relation["target"]
        def link(ident: str) -> str:
            location = ("People/" + ident if ident.startswith("p-")
                        else "Workspaces/" + ws["id"] + "/Groups/" + ident)
            return "[[" + location + "|" + md.safe(by_id.get(ident, ident)) + "]]"
        graph.append("- " + link(src) + " — **" + md.safe(relation["type"]) +
                     "** → " + link(dst) +
                     (" (" + md.safe(relation.get("note")) + ")" if relation.get("note") else ""))
    if not ws["edges"]:
        graph.append("No relationships entered.")
    graph.extend(["", "People linked to the same group form a visual cluster, **not** an inferred "
                  "person-to-person relationship.", ""])
    md.write_private(folder / "Graph.md", "\n".join(graph))


def create_workspace(name: str, description: str = "") -> dict[str, Any]:
    name = _text(name, "Workspace name", 90)
    description = _text(description, "Description", 350, required=False)
    if len(list_workspaces()) >= 60:
        raise NetworkError("Maximum of 60 workspaces reached.")
    workspace = {
        "id": "w-" + uuid4().hex, "name": name, "description": description,
        "created_at": _now(), "people": [], "groups": [], "edges": [],
        "positions": {},
    }
    _save_workspace(workspace)
    return workspace


def get_workspace(workspace_id: str) -> dict[str, Any]:
    return _load(_workspace_path(workspace_id), "Workspace")


def list_workspaces() -> list[dict[str, Any]]:
    folder = root() / "Workspaces"
    if not folder.exists():
        return []
    items: list[dict[str, Any]] = []
    for file in folder.glob("w-*/Workspace.md"):
        try:
            data = _load(file, "Workspace")
            if _id(data.get("id"), "w") != file.parent.name:
                continue
            items.append({"id": data["id"], "name": data.get("name", ""),
                          "description": data.get("description", ""),
                          "created_at": data.get("created_at", ""),
                          "people_count": len(data.get("people", [])),
                          "groups_count": len(data.get("groups", []))})
        except NetworkError:
            continue
    return sorted(items, key=lambda item: item["created_at"], reverse=True)[:60]


def create_person(name: str, details: str = "") -> dict[str, Any]:
    person = {
        "id": "p-" + uuid4().hex,
        "name": _text(name, "Person name", 90),
        "details": _text(details, "Shared profile notes", 500, required=False),
        "created_at": _now(),
    }
    _save_person(person)
    return person


def get_person(person_id: str) -> dict[str, Any]:
    return _load(_person_path(person_id), "Person")


def update_person(person_id: str, name: str, details: str = "") -> dict[str, Any]:
    person = get_person(person_id)
    person["name"] = _text(name, "Person name", 90)
    person["details"] = _text(details, "Shared profile notes", 500, required=False)
    _save_person(person)
    # Refresh readable names in each workspace, without changing any edges.
    for ws in list_workspaces():
        if person_id in get_workspace(ws["id"])["people"]:
            _save_workspace(get_workspace(ws["id"]))
    return person


def list_people() -> list[dict[str, Any]]:
    folder = root() / "People"
    if not folder.exists():
        return []
    result = []
    for file in folder.glob("p-*.md"):
        try:
            person = _load(file, "Person")
            if person.get("id") != file.stem:
                continue
            result.append(person)
        except NetworkError:
            continue
    return sorted(result, key=lambda x: (x["name"].lower(), x["id"]))


def attach_person(workspace_id: str, person_id: str) -> dict[str, Any]:
    ws = get_workspace(workspace_id)
    get_person(person_id)
    if person_id not in ws["people"]:
        if len(ws["people"]) >= MAX_PEOPLE:
            raise NetworkError("Workspace person limit reached.")
        ws["people"].append(person_id)
        _save_workspace(ws)
    return ws


def create_group(workspace_id: str, name: str, kind: str, details: str = "") -> dict[str, Any]:
    ws = get_workspace(workspace_id)
    if kind not in GROUP_TYPES:
        raise NetworkError("Choose a supported group type.")
    if len(ws["groups"]) >= MAX_GROUPS:
        raise NetworkError("Workspace group limit reached.")
    group = {
        "id": "g-" + uuid4().hex,
        "name": _text(name, "Group name", 90), "kind": kind,
        "details": _text(details, "Group notes", 300, required=False),
    }
    ws["groups"].append(group)
    _save_workspace(ws)
    return group


def create_link(workspace_id: str, source: str, target: str, relation: str, note: str = "") -> dict[str, Any]:
    ws = get_workspace(workspace_id)
    if relation not in RELATIONS:
        raise NetworkError("Unsupported relationship type.")
    allowed = set(ws["people"]) | {g["id"] for g in ws["groups"]}
    if source not in allowed or target not in allowed or source == target:
        raise NetworkError("Both distinct nodes must belong to this workspace.")
    note = _text(note, "Relationship note", 300, required=False)
    for edge in ws["edges"]:
        if (edge["source"], edge["target"], edge["type"]) == (source, target, relation):
            return edge
    if len(ws["edges"]) >= MAX_EDGES:
        raise NetworkError("Workspace relationship limit reached.")
    item = {"id": "r-" + uuid4().hex, "source": source, "target": target,
            "type": relation, "note": note, "created_at": _now(), "origin": "manual"}
    ws["edges"].append(item)
    _save_workspace(ws)
    return item


def set_position(workspace_id: str, node_id: str, x: float, y: float) -> dict[str, Any]:
    ws = get_workspace(workspace_id)
    valid = set(ws["people"]) | {g["id"] for g in ws["groups"]}
    if node_id not in valid:
        raise NetworkError("Node does not belong to this workspace.")
    if (not isinstance(x, (float, int)) or isinstance(x, bool)
        or not isinstance(y, (float, int)) or isinstance(y, bool)
        or not math.isfinite(x) or not math.isfinite(y) or abs(x) > 10000 or abs(y) > 10000):
        raise NetworkError("Position must contain two finite coordinates.")
    ws.setdefault("positions", {})[node_id] = {"x": round(x, 2), "y": round(y, 2)}
    _save_workspace(ws)
    return ws["positions"][node_id]


def person_memberships(person_id: str) -> list[dict[str, Any]]:
    """Only called by the explicit 'view other workspaces' UI action."""
    get_person(person_id)
    return [
        {"id": ws["id"], "name": ws["name"], "description": ws["description"]}
        for ws in list_workspaces() if person_id in get_workspace(ws["id"])["people"]
    ]


def workspace_view(workspace_id: str) -> dict[str, Any]:
    ws = get_workspace(workspace_id)
    nodes = [
        {"id": ident, "kind": "person", "label": person["name"],
         "details": person.get("details", "")}
        for ident in ws["people"] for person in [get_person(ident)]
    ]
    nodes.extend({
        "id": group["id"], "kind": "group", "group_kind": group["kind"],
        "label": group["name"], "details": group.get("details", "")
    } for group in ws["groups"])

    # Cluster membership is inferred solely from explicitly entered person/group
    # edges within this workspace. No person-to-person relationships are created.
    clusters = []
    for group in ws["groups"]:
        members = [
            edge["source"] if edge["source"].startswith("p-") else edge["target"]
            for edge in ws["edges"]
            if group["id"] in (edge["source"], edge["target"])
            and (edge["source"].startswith("p-") or edge["target"].startswith("p-"))
        ]
        unique_members = list(dict.fromkeys(members))
        if unique_members:
            clusters.append({"group_id": group["id"], "group_name": group["name"],
                             "kind": group["kind"], "members": unique_members,
                             "count": len(unique_members)})
    return {
        "workspace": {key: value for key, value in ws.items() if key != "positions"},
        "nodes": nodes,
        "edges": ws["edges"],
        "clusters": sorted(clusters, key=lambda item: -item["count"]),
        "positions": ws.get("positions", {}),
        "disclaimer": "Clusters show shared explicit group connections, not proof people know one another.",
    }
