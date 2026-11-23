# Reconductor

**A terminal-first OSINT orchestration framework.** Run approved research tools in a predictable order, preserve their raw outputs, and organize local investigation cases.

> **v0.1:** No AI, web dashboard, cloud service, background daemon, or automatic third-party uploads. Network research is **dry-run by default**; only local case files are created on execution.

## Features

- `reconductor --help` plus contextual help for every subcommand.
- **Light / Medium / Deep** presets for username, domain, and local file investigations.
- Tool discovery (`doctor`, `tools list`) without reinstalling anything.
- Safe subprocess calls (no shell interpolation), time limits, per-tool output and exit codes.
- Local case folders with `case.json`, `report.md`, and raw tool logs.
- Passive-only SpiderFoot preset for domain research; no port scanning or intrusive requests by design.
- Explicit confirmation required to execute **any network research**.
- Works without a local AI model. Python standard library only at runtime.

## Installation (Trace Labs / Debian)

```bash
sudo apt update
sudo apt install -y git python3 python3-venv
git clone https://github.com/tylerthibault/Reconductor.git
cd Reconductor
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
reconductor --help
reconductor doctor
```

Use `source .venv/bin/activate` when starting a new terminal, or execute `.venv/bin/reconductor` directly. Do **not** run as root. The command detects existing tools from your `PATH`; it does not install Sherlock, Maigret, SpiderFoot, theHarvester, or ExifTool.

## Examples

```bash
# Inspect commands and tool availability
reconductor --help
reconductor scan --help
reconductor tools list
reconductor doctor

# Preview exact commands without making external requests
reconductor scan username example_user --depth medium
reconductor scan domain example.org --depth deep
reconductor scan file ~/Downloads/test.jpg --depth light

# Execute local-only file inspection
reconductor scan file ~/Downloads/test.jpg --execute

# Network execution requires two explicit flags
reconductor scan username example_user --depth light --execute --acknowledge-exposure
reconductor scan domain example.org --depth medium --execute --acknowledge-exposure

# Browse local cases
reconductor cases list
reconductor cases show CASE_ID
reconductor report CASE_ID
```

## Depth presets

| Target | Light | Medium | Deep |
|---|---|---|---|
| Username | Sherlock | Sherlock + Maigret | Sherlock + Maigret, extended time budget |
| Domain | SpiderFoot passive | SpiderFoot passive + theHarvester | Same passive tools, extended time budget |
| File | SHA-256 | SHA-256 + ExifTool | Same local analyses, extended time budget |

These are **effort budgets**, not accuracy or identity-confidence ratings. More results do not imply a verified match. Tools absent from PATH are logged as skipped; no hidden auto-install is performed.

## Privacy and ethics

**This project is not an anonymity solution.** Tools make outbound requests using whatever network route the Trace Labs VM currently has. A VPN/Tor browser, isolated network, DNS rules and a tested kill switch are separate setup tasks. Never assume they are active because Reconductor is installed.

Run public-source lookups only within the scope of applicable law, site terms, and your authorization. Active scanning is not included. Do not use output for employment, credit, housing, or similar eligibility screening without the required compliance framework. Never treat matching usernames as proof of common ownership.

Results are stored by default in `~/.local/share/reconductor/cases` with restrictive permissions. Override using `RECONDUCTOR_HOME`. Do not commit cases, credentials, or collected personal information to this repository.

See [Command Reference](docs/commands.md) and [Privacy & Safety](docs/privacy.md).

## Development

```bash
python -m unittest discover -s tests -v
python -m reconductor --help
```

Licensed under MIT. This project is independent from the upstream OSINT tools it invokes. Each tool retains its own license.
