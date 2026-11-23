"""Markdown-first case storage and Obsidian-compatible note links.

All new case data and tool output are .md files. Structured dictionaries are
stored in a readable fenced JSON block inside Markdown, not a separate .json.
Legacy cases remain accessible and may be converted explicitly with backups.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any

START = "<!-- reconductor:state:start -->"
END = "<!-- reconductor:state:end -->"
RAW_START = "<!-- reconductor:raw:start -->"
RAW_END = "<!-- reconductor:raw:end -->"


def write_private(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name("." + path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def safe(value: Any) -> str:
    return str(value if value is not None else "").replace("\r", " ").replace("\n", " ").strip()


def quote(value: Any) -> str:
    return safe(value).replace("|", "\\|")


def block(value: dict) -> str:
    data = json.dumps(value, indent=2, ensure_ascii=False)
    fence = "~" * max(3, max((len(x.group()) for x in re.finditer(r"~+", data)), default=0) + 1)
    return "\n".join([START, fence + "json", data, fence, END])


def parse_block(path: Path) -> dict:
    source = path.read_text(encoding="utf-8")
    if START not in source or END not in source:
        raise ValueError("Missing Reconductor metadata block")
    content = source.split(START, 1)[1].split(END, 1)[0].strip()
    opener, sep, rest = content.partition("\n")
    fence = opener.split("json", 1)[0]
    if not sep or not fence.startswith("~~~") or not rest.endswith("\n" + fence):
        raise ValueError("Malformed Reconductor metadata block")
    value = json.loads(rest[:-(len(fence) + 1)])
    if not isinstance(value, dict):
        raise ValueError("Metadata must be an object")
    return value


def write_case(folder: Path, record: dict) -> None:
    lines = ["---", "reconductor: case", "format: markdown-v1", "---", "",
             "# Investigation " + safe(record.get("id")), "",
             "- **Target:** " + safe(record.get("target")),
             "- **Status:** " + safe(record.get("status")),
             "- **Depth:** " + safe(record.get("depth")),
             "- **Started:** " + safe(record.get("created_at")), "",
             "> [!warning] Unverified search results are not confirmed identities.", "",
             "## Starting clues", ""]
    for clue in record.get("clues", []):
        lines.append("- **" + safe(clue.get("kind")) + ":** " + safe(clue.get("value")))
    if not record.get("clues"):
        lines.append("- " + safe(record.get("target_type")) + ": " + safe(record.get("target")))
    lines.extend(["", "## Candidate leads (unverified)", ""])
    for lead in record.get("leads", []):
        lines.append("- " + safe(lead.get("kind")) + ": " + safe(lead.get("value")) +
                     " — evidence: " + safe(lead.get("origin")))
    if not record.get("leads"):
        lines.append("No candidate leads yet.")
    lines.extend(["", "## Tool execution", "", "| Tool | Status | Evidence |",
                  "| --- | --- | --- |"])
    for step in record.get("steps", []):
        ref = step.get("stdout_file")
        link = "[[" + str(Path(ref).with_suffix("").as_posix()) + "|stdout]]" if ref else "Pending"
        lines.append("| " + quote(step.get("tool")) + " | " + quote(step.get("state")) + " | " + link + " |")
    lines.extend(["", "## Vault links", "", "- [[Vault|Investigation index]]",
                  "- [[report|Report]]", "- [[graph|Relationship notes]]", "",
                  "## Application data", "",
                  "Reconductor stores its complete machine-readable state below as formatted JSON "
                  "inside this Markdown file. Keep the block intact.", "", block(record), ""])
    write_private(folder / "case.md", "\n".join(lines))


def load_case(folder: Path) -> dict:
    path = folder / "case.md"
    if path.exists():
        return parse_block(path)
    return json.loads((folder / "case.json").read_text(encoding="utf-8"))


def capture_name(relative: str) -> str:
    return str(Path(relative).with_suffix(".md"))


def capture_path(folder: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or len(path.parts) != 2 or path.parts[0] != "raw":
        raise ValueError("Evidence path must be directly below raw/")
    result = folder / path
    if result.parent.resolve() != (folder / "raw").resolve() or not result.resolve().is_relative_to((folder / "raw").resolve()):
        raise ValueError("Evidence path escapes raw directory")
    return result


def _spiderfoot_summary(text: str) -> list[str]:
    try:
        events = json.loads(text)
    except ValueError:
        return []
    if not isinstance(events, list):
        return []
    allowed = {"username", "user name", "internet name", "internet hostname",
               "website", "social media profile"}
    lines = ["## Recognized unverified observations", "",
             "| Type | Value | Source |", "| --- | --- | --- |"]
    count = 0
    for event in events[:1000]:
        if not isinstance(event, dict) or safe(event.get("type")).lower() not in allowed:
            continue
        value = event.get("data")
        if not isinstance(value, str):
            continue
        lines.append("| " + quote(event.get("type"))[:65] + " | " +
                     quote(value)[:200] + " | " + quote(event.get("module"))[:60] + " |")
        count += 1
        if count >= 100:
            lines.append("| ... | Remaining original events below | |")
            break
    return lines + [""] if count else []


def write_capture(path: Path, tool: str, stream: str, raw: str) -> None:
    """Wrap every character of decoded stdout/stderr in a Markdown code fence."""
    if stream not in ("stdout", "stderr"):
        raise ValueError("Invalid stream")
    fence = "~" * max(3, max((len(x.group()) for x in re.finditer(r"~+", raw)), default=0) + 1)
    lines = ["---", "reconductor: evidence", "format: markdown-v1", "---", "",
             "# " + safe(tool) + " — " + stream, "",
             "> [!warning] Raw tool data is unverified and may contain sensitive information.", ""]
    if tool == "spiderfoot" and stream == "stdout":
        lines.extend(_spiderfoot_summary(raw))
    lines.extend(["## Original captured output", "",
                  "The code block below preserves the full decoded output, including errors.", "",
                  RAW_START, fence + ("json" if tool == "spiderfoot" and stream == "stdout" else "text")])
    # Insert one separator newline after raw, removed on reading.
    write_private(path, "\n".join(lines) + "\n" + raw + "\n" + fence + "\n" + RAW_END + "\n")


def read_capture(path: Path, limit: int | None = None) -> str:
    if path.suffix != ".md":
        with path.open("rb") as f:
            return f.read(limit or -1).decode("utf-8", errors="replace")
    text = path.read_text(encoding="utf-8")
    if RAW_START not in text or RAW_END not in text:
        raise ValueError("Unknown Markdown evidence format")
    body = text.split(RAW_START, 1)[1].split(RAW_END, 1)[0].removeprefix("\n")
    opener, sep, rest = body.partition("\n")
    fence = opener.split("json", 1)[0].split("text", 1)[0]
    if not sep or len(fence) < 3 or not fence.startswith("~~~") or not rest.endswith("\n" + fence + "\n"):
        raise ValueError("Malformed raw evidence fence")
    captured = rest[:-(len(fence) + 2)]
    return captured if limit is None else captured.encode("utf-8")[:limit].decode("utf-8", errors="replace")


def load_graph(folder: Path) -> dict:
    path = folder / "graph.md"
    if path.exists():
        data = parse_block(path)
    elif (folder / "graph.json").exists():
        data = json.loads((folder / "graph.json").read_text(encoding="utf-8"))
    else:
        data = {}
    return {"people": data.get("people", []) if isinstance(data.get("people"), list) else [],
            "links": data.get("links", []) if isinstance(data.get("links"), list) else []}


def slug(kind: str, value: Any) -> str:
    visible = re.sub(r"[^a-z0-9]+", "-", safe(value).lower()).strip("-")[:35] or "item"
    digest = hashlib.sha256((kind + "|" + str(value)).encode("utf-8")).hexdigest()[:12]
    return kind + "/" + visible + "-" + digest


def sync_vault(folder: Path, record: dict, observations: list[dict] | None = None,
               graph: dict | None = None) -> dict[str, str]:
    """Create linked notes, preserving existing user-edited notes."""
    from . import findings  # deferred to avoid dependency cycle
    refs = {"case:root": "Vault"}
    index = ["# Investigation vault: " + safe(record.get("target")), "",
             "> [!warning] Possible matches remain UNVERIFIED.", "",
             "- [[case|Case metadata]]", "- [[report|Report]]",
             "- [[graph|Relationship notes]]"]
    if (folder / "dossier.md").exists():
        index.append("- [[dossier|Dossier]]")
    for heading, field, category, nodekind in (
        ("Starting clues", "clues", "Clues", "clue"),
        ("Discovered leads (unverified)", "leads", "Leads", "lead"),
    ):
        index.extend(["", "## " + heading, ""])
        for item in record.get(field, []):
            kind, value = str(item.get("kind", "")), str(item.get("value", ""))
            ref = slug(category, kind + "-" + value)
            refs[nodekind + ":" + findings._identifier(kind, value)] = ref
            index.append("- [[" + ref + "|" + safe(kind) + ": " + safe(value) + "]]")
            path = folder / (ref + ".md")
            if not path.exists():
                origin = item.get("origin", "operator")
                evidence = ""
                if isinstance(origin, str) and origin.startswith("raw/") and origin.endswith(".md"):
                    evidence = "\n- **Evidence:** [[" + str(Path(origin).with_suffix("")) + "]]"
                write_private(path, "# " + safe(value) + "\n\n- **Kind:** " + safe(kind) +
                              "\n- **Status:** " + ("Operator-supplied" if nodekind == "clue" else "UNVERIFIED CANDIDATE") +
                              "\n- **Origin:** " + safe(origin) + evidence + "\n- [[Vault|Investigation index]]\n")
    index.extend(["", "## Observations (unverified)", ""])
    for obs in (observations or [])[:150]:
        ref = slug("Observations", obs.get("id"))
        refs[str(obs.get("id"))] = ref
        index.append("- [[" + ref + "|" + safe(obs.get("type")) + ": " + safe(obs.get("display_name") or obs.get("value"))[:90] + "]]")
        path = folder / (ref + ".md")
        if not path.exists():
            origin = obs.get("evidence", "")
            evidence = ("[[" + str(Path(origin).with_suffix("")) + "]]") if isinstance(origin, str) and origin.startswith("raw/") else "Unavailable"
            write_private(path, "# " + safe(obs.get("type")) + ": " + safe(obs.get("display_name") or obs.get("value")) +
                          "\n\n- **Status:** UNVERIFIED\n- **Tool:** " + safe(obs.get("tool")) +
                          "\n- **Evidence:** " + evidence + "\n- [[Vault|Investigation index]]\n")
    index.extend(["", "## Raw tool output", ""])
    for step in record.get("steps", []):
        for key in ("stdout_file", "stderr_file", "report_file"):
            file = step.get(key)
            if isinstance(file, str) and file.endswith(".md"):
                index.append("- [[" + str(Path(file).with_suffix("")) + "|" +
                             safe(step.get("tool")) + " " + key.removesuffix("_file") + "]]")
    index.extend(["", "## Manually added people", ""])
    for p in (graph or {}).get("people", []):
        if not isinstance(p, dict):
            continue
        ref = slug("People", p.get("id"))
        refs[str(p.get("id"))] = ref
        index.append("- [[" + ref + "|" + safe(p.get("name")) + "]]")
        path = folder / (ref + ".md")
        if not path.exists():
            write_private(path, "# " + safe(p.get("name")) +
                          "\n\n- **Status:** Manually added; unverified\n- **Note:** " +
                          safe(p.get("note")) + "\n- [[graph|Relationship notes]]\n")
    index.extend(["", "## Your notes", "",
                  "Create additional Markdown notes here. This index is generated and may be refreshed.", ""])
    write_private(folder / "Vault.md", "\n".join(index))
    if not (folder / "graph.md").exists():
        write_graph(folder, graph or {"people": [], "links": []}, refs)
    return refs


def write_graph(folder: Path, graph: dict, refs: dict[str, str] | None = None) -> None:
    refs = refs or {}
    lines = ["---", "reconductor: graph", "format: markdown-v1", "---", "",
             "# Relationship map", "",
             "> [!warning] UNVERIFIED: these links are user-entered, not automatically verified.", "",
             "## People", ""]
    for p in graph.get("people", []):
        ref = refs.get(p.get("id"))
        text = "[[" + ref + "|" + safe(p.get("name")) + "]]" if ref else safe(p.get("name"))
        lines.append("- " + text + " — " + safe(p.get("note")))
    lines.extend(["", "## Relationships", ""])
    for link in graph.get("links", []):
        src, dst = str(link.get("source", "")), str(link.get("target", ""))
        left = "[[" + refs[src] + "]]" if src in refs else src
        right = "[[" + refs[dst] + "]]" if dst in refs else dst
        lines.append("- " + left + " → **" + safe(link.get("label")) + "** → " + right)
    lines.extend(["", "## Machine-readable graph state", "", block(graph), ""])
    write_private(folder / "graph.md", "\n".join(lines))


def migrate_case(folder: Path, record: dict, backup_root: Path) -> tuple[bool, Path | None]:
    """Explicit conversion, retaining copies of every legacy file in backups."""
    if (folder / "case.md").exists():
        return False, None
    legacy = folder / "case.json"
    if not legacy.is_file():
        raise FileNotFoundError("No legacy case.json file found")
    backup = backup_root / folder.name
    if backup.exists():
        raise FileExistsError("Legacy backup exists; refusing to overwrite it")
    originals = [legacy]
    for step in record.get("steps", []):
        for key in ("stdout_file", "stderr_file"):
            ref = step.get(key)
            if isinstance(ref, str) and ref.endswith(".txt"):
                path = capture_path(folder, ref)
                if path.is_file() and path not in originals:
                    originals.append(path)
    for extra in (folder / "raw").glob("*.txt"):
        if extra.is_file() and extra not in originals:
            originals.append(extra)
    for name in ("graph.json", "report.md", "dossier.md"):
        path = folder / name
        if path.is_file():
            originals.append(path)
    backup.mkdir(parents=True, exist_ok=False, mode=0o700)
    for original in originals:
        copied = backup / original.relative_to(folder)
        copied.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copy2(original, copied)
        os.chmod(copied, 0o600)
    for old_file in originals:
        if old_file.parent == folder / "raw" and old_file.suffix == ".txt":
            stem = old_file.stem
            tool = next((str(step.get("tool", "unknown")) for step in record.get("steps", [])
                         if old_file.name in (str(step.get("stdout_file", "")).split("/")[-1],
                                              str(step.get("stderr_file", "")).split("/")[-1])), "unknown")
            stream = "stderr" if stem.endswith(".stderr") else "stdout"
            new = old_file.with_suffix(".md")
            raw = old_file.read_text(encoding="utf-8", errors="replace")
            write_capture(new, tool, stream, raw)
            if read_capture(new) != raw:
                raise ValueError("Raw evidence verification failed; legacy files preserved")
    for step in record.get("steps", []):
        for key in ("stdout_file", "stderr_file"):
            ref = step.get(key)
            if isinstance(ref, str) and ref.endswith(".txt"):
                step[key] = capture_name(ref)
    for lead in record.get("leads", []):
        ref = lead.get("origin")
        if isinstance(ref, str) and ref.startswith("raw/") and ref.endswith(".txt"):
            lead["origin"] = capture_name(ref)
    from . import core, engine, findings
    graph = load_graph(folder)
    observations = findings.extract(folder, record)
    refs = sync_vault(folder, record, observations, graph)
    write_graph(folder, graph, refs)
    write_case(folder, record)
    if load_case(folder) != record:
        raise ValueError("Case state verification failed; original files preserved")
    if "leads" in record:
        engine._dossier(folder, record)
    else:
        core.write_report(folder, record)
    sync_vault(folder, record, observations, graph)
    # Originals have already been backed up separately; remove legacy only after verification.
    for original in originals:
        if original.suffix in (".txt", ".json") and original.is_file():
            original.unlink()
    return True, backup
