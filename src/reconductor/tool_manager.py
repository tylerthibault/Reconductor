"""Allowlisted, user-approved tool installation for a local Linux Reconductor VM.

No arbitrary commands, shell=True, or unattended root operations. pipx
installs are isolated. SpiderFoot is installed from its upstream stable tag
into Reconductor's private user-owned managed-tools directory.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Callable
from uuid import uuid4

from . import core

@dataclass(frozen=True)
class Tool:
    id: str
    title: str
    description: str
    executable: str
    method: str
    package: str
    url: str
    note: str = ""


CATALOG = (
    Tool("spiderfoot", "SpiderFoot", "Broad OSINT discovery using public sources and configurable modules.",
         "spiderfoot", "managed-git", "smicallef/spiderfoot v4.0",
         "https://github.com/smicallef/spiderfoot",
         "Managed local source checkout and dedicated Python environment; installation can require extra system libraries."),
    Tool("sherlock", "Sherlock", "Possible public profile discovery across username-based websites.",
         "sherlock", "pipx", "sherlock-project", "https://github.com/sherlock-project/sherlock",
         "A command being present does not prove it launches; use Test tool to diagnose CPU or dependency errors."),
    Tool("maigret", "Maigret", "Username discovery with richer public account metadata and Markdown reports.",
         "maigret", "pipx", "maigret", "https://github.com/soxoj/maigret"),
    Tool("social-analyzer", "Social Analyzer", "Additional username candidates with heuristic website-detection ratings.",
         "social-analyzer", "pipx", "social-analyzer",
         "https://github.com/Qeeqbox-Social-Analyzer/Social-Analyzer",
         "Detection ratings are clues, not identity proof."),
    Tool("theharvester", "theHarvester", "Public domain, email, and internet infrastructure discovery.",
         "theHarvester", "pipx", "git+https://github.com/laramies/theHarvester.git@4.11.1",
         "https://github.com/laramies/theHarvester/releases/tag/4.11.1",
         "Pinned to upstream 4.11.1 (Python >=3.12), compatible with Python 3.13. "
         "Unreleased upstream code now requires Python >=3.14. "
         "This installer does not modify your system Python."),
    Tool("exiftool", "ExifTool", "Reads metadata in local files, images and documents.",
         "exiftool", "manual-apt", "libimage-exiftool-perl",
         "https://exiftool.org/",
         "Requires administrator approval: sudo apt install libimage-exiftool-perl (manual)."),
    Tool("wayback", "Wayback History", "Checks archive snapshots for explicitly provided public domains in Deep mode.",
         "", "built-in", "Reconductor built-in", "https://web.archive.org/",
         "No installation needed. Network requests go to Internet Archive when Deep research is authorized."),
)
BY_ID = {item.id: item for item in CATALOG}
MAX_ITEMS = 5
# Enrich the server's process PATH, without modifying the user's shell startup.
USER_BIN = Path.home() / ".local" / "bin"


class InstallError(ValueError):
    pass


def ensure_user_path() -> None:
    path = os.environ.get("PATH", "")
    user_bin = str(USER_BIN)
    if user_bin not in path.split(os.pathsep):
        os.environ["PATH"] = user_bin + os.pathsep + path


def executable_path(tool: Tool) -> str | None:
    if not tool.executable:
        return None
    ensure_user_path()
    return shutil.which(tool.executable)


def catalog() -> list[dict]:
    """Only reveal executable presence, not an untested claim of runtime health."""
    result = []
    for tool in CATALOG:
        path = executable_path(tool)
        result.append({
            "id": tool.id,
            "title": tool.title,
            "description": tool.description,
            "method": tool.method,
            "package": tool.package,
            "url": tool.url,
            "note": tool.note,
            "path": path or "",
            "status": "built-in" if tool.method == "built-in"
                      else "detected" if path else
                      "manual" if tool.method == "manual-apt" else "missing",
            "auto_install": tool.method in ("pipx", "managed-git") and not path and sys.platform.startswith("linux"),
            "requires_privilege": tool.method == "manual-apt",
        })
    return result


def validate_selection(raw: object) -> list[str]:
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_ITEMS:
        raise InstallError("Select one to five supported missing tools.")
    if len(set(map(str, raw))) != len(raw):
        raise InstallError("Duplicate tool selections are not allowed.")
    validated = []
    for item in raw:
        if not isinstance(item, str) or item not in BY_ID:
            raise InstallError("Unknown tool selection.")
        tool = BY_ID[item]
        if tool.method not in ("pipx", "managed-git"):
            raise InstallError(tool.title + " requires a different installation method.")
        if executable_path(tool):
            raise InstallError(tool.title + " is already on PATH; test it instead.")
        validated.append(item)
    if not sys.platform.startswith("linux"):
        raise InstallError("Managed installation is currently supported only on Linux.")
    return validated


def check_tool(tool_id: object) -> dict:
    if not isinstance(tool_id, str) or tool_id not in BY_ID:
        raise InstallError("Unknown tool.")
    tool = BY_ID[tool_id]
    if tool.method == "built-in":
        return {"id": tool_id, "status": "ready", "message": "Built into Reconductor."}
    exe = executable_path(tool)
    if not exe:
        return {"id": tool_id, "status": "missing", "message": "Executable not found on PATH."}
    try:
        result = subprocess.run(
            [exe, "--help"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, errors="replace", timeout=12,
            env=os.environ.copy(),
        )
    except subprocess.TimeoutExpired:
        return {"id": tool_id, "status": "warning", "message": "Help command timed out after 12 seconds."}
    except OSError as exc:
        return {"id": tool_id, "status": "broken", "message": str(exc)[:600]}
    message = (result.stdout or "").strip()
    return {
        "id": tool_id,
        "status": "ready" if result.returncode == 0 else "broken",
        "message": (message[-1200:] if message else "No output captured; exit status " + str(result.returncode)),
        "exit_code": result.returncode,
    }


def _command(argv: list[str], *, timeout: int, cwd: Path | None = None,
             status: Callable[[str], None] | None = None) -> None:
    if status:
        status("Running: " + " ".join(argv[:3]) + (" …" if len(argv) > 3 else ""))
    try:
        result = subprocess.run(
            argv, cwd=str(cwd) if cwd else None, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace",
            timeout=timeout, env=os.environ.copy(), check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise InstallError("Install command timed out after " + str(timeout) + " seconds.") from exc
    except OSError as exc:
        raise InstallError("Cannot execute install command: " + str(exc)[:400]) from exc
    if result.returncode:
        raise InstallError(
            "Install command failed (exit " + str(result.returncode) + "): " +
            (result.stdout or "")[-1100:]
        )


def _managed_spiderfoot(status: Callable[[str], None]) -> None:
    git = shutil.which("git")
    python = shutil.which("python3")
    if not git or not python:
        raise InstallError("SpiderFoot requires git and python3 installed on this machine.")
    root = core.home() / "managed-tools"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    final = root / "spiderfoot-v4.0"
    if final.exists():
        raise InstallError("Managed SpiderFoot folder already exists; refusing to overwrite it: " + str(final))
    temp = root / ("spiderfoot-install-" + uuid4().hex[:10])
    wrapper = USER_BIN / "spiderfoot"
    if wrapper.exists() or wrapper.is_symlink():
        raise InstallError("Executable already exists: " + str(wrapper) + ". Remove or resolve it manually.")
    try:
        status("Downloading SpiderFoot v4.0 from its official GitHub repository")
        _command([git, "clone", "--depth", "1", "--branch", "v4.0",
                  "https://github.com/smicallef/spiderfoot.git", str(temp)], timeout=240)
        status("Creating dedicated SpiderFoot Python environment")
        _command([python, "-m", "venv", str(temp / ".venv")], timeout=120)
        status("Installing SpiderFoot Python dependencies (no system pip changes)")
        _command([str(temp / ".venv" / "bin" / "python"), "-m", "pip",
                  "install", "-r", str(temp / "requirements.txt")], timeout=600, cwd=temp)
        if not (temp / "sf.py").is_file():
            raise InstallError("Official checkout did not contain sf.py.")
        temp.rename(final)
        USER_BIN.mkdir(parents=True, exist_ok=True, mode=0o700)
        import shlex
        # Static generated wrapper: path values escaped, never substituted from user input.
        script = (
            "#!/bin/sh\nexec " +
            shlex.quote(str(final / ".venv" / "bin" / "python")) + " " +
            shlex.quote(str(final / "sf.py")) + ' "$@"\n'
        )
        wrapper.write_text(script, encoding="utf-8")
        wrapper.chmod(0o700)
        status("SpiderFoot user-local launcher created at " + str(wrapper))
    finally:
        if temp.exists():
            shutil.rmtree(temp)


def install_one(tool_id: str, status: Callable[[str], None]) -> dict:
    if tool_id not in BY_ID:
        raise InstallError("Unknown tool.")
    tool = BY_ID[tool_id]
    if tool.method not in ("pipx", "managed-git"):
        raise InstallError("Automatic installer is not available for " + tool.title)
    if executable_path(tool):
        return {"id": tool_id, "state": "skipped", "message": "Already detected; not overwritten."}
    ensure_user_path()
    if tool.method == "managed-git":
        _managed_spiderfoot(status)
    else:
        pipx = shutil.which("pipx")
        if not pipx:
            raise InstallError("pipx is required. Install pipx from your Debian package manager, then retry.")
        status("Installing " + tool.title + " with pipx (isolated application environment)")
        _command([pipx, "install", tool.package], timeout=600, status=status)
    if not executable_path(tool):
        raise InstallError(tool.title + " installation ended without a usable launcher. Check ~/.local/bin and your PATH.")
    health = check_tool(tool_id)
    status("Launch test: " + health["status"])
    return {
        "id": tool_id,
        "state": "installed" if health["status"] == "ready" else "warning",
        "message": "Installed and help command worked." if health["status"] == "ready"
                   else "Executable found but it may not launch: " + health["message"][:400],
    }


def run_batch(tools: list[str], progress: Callable[[dict], None]) -> list[dict]:
    outcome = []
    for index, tool_id in enumerate(tools, start=1):
        tool = BY_ID[tool_id]
        progress({"kind": "started", "id": tool_id, "index": index, "total": len(tools),
                  "message": "Starting installation of " + tool.title})
        try:
            result = install_one(tool_id, lambda message: progress({
                "kind": "progress", "id": tool_id, "message": message[:350]
            }))
        except (InstallError, OSError) as exc:
            result = {"id": tool_id, "state": "failed", "message": str(exc)[:900]}
        outcome.append(result)
        progress({"kind": "finished", **result})
    return outcome
