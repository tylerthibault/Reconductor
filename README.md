# Reconductor

**A terminal-first OSINT orchestration framework.** Run approved research tools in a predictable order, preserve their raw outputs, and organize local investigation cases.

> **v0.5.1:** No AI, web dashboard, cloud service, background daemon, or automatic third-party uploads. Network research is **dry-run by default**; only local case files are created on execution.

## Features

- Interactive numbered terminal menu; `reconductor --help` plus contextual help for every subcommand.
- **Light / Medium / Deep** presets for username, domain, and local file investigations, plus multi-clue research.
- Tool discovery (`doctor`, `tools list`) without reinstalling anything.
- Safe subprocess calls (no shell interpolation), time limits, per-tool output and exit codes.
- Local Markdown case vaults with `case.md`, `report.md`, linked notes, and raw Markdown evidence.
- Passive-only SpiderFoot preset for domain research; no port scanning or intrusive requests by design.
- Explicit confirmation required to execute **any network research**.
- Live progress for both `scan` and `investigate`: tool start, elapsed-time heartbeat, timeout and status. Use `--no-progress` to silence.
- Rules-based multi-clue research with a bounded candidate-lead queue; no LLM required.
- Local dossier separates unverified leads from operator-supplied clues and reports missing worldwide record coverage.
- Works without a local AI model. Python standard library only at runtime.

## Markdown-first research vault (v0.5)

All **new investigations** are written as Markdown files in the local case
folder. You can open the case folder directly as an Obsidian vault or browse
it with any Markdown editor. No database or Coolify instance is needed.

```text
~/.local/share/reconductor/cases/CASE_ID/
  Vault.md                 # Obsidian-friendly index and wiki-links
  case.md                  # Case status, clues, steps, structured state
  report.md                # Human-readable report
  dossier.md               # Investigation dossier, if applicable
  graph.md                 # User-created people/relationship notes
  Clues/*.md               # One Markdown note per starting clue
  Leads/*.md               # One Markdown note per candidate lead
  Observations/*.md        # Parsed public observations, if any
  People/*.md              # People manually added in the GUI, if any
  raw/*.stdout.md          # Complete decoded tool output, in code fences
  raw/*.stderr.md          # Complete decoded error output, in code fences
```

The raw Markdown evidence files include the **complete captured decoded text**
as a fenced code block, including the tool's original JSON when applicable.
SpiderFoot output also receives an optional human-readable event summary.
The readable summaries never replace the original output. Raw evidence can
contain sensitive personal information; never publish your case folders
unreviewed.

`case.md` and `graph.md` embed readable, formatted JSON *inside the
Markdown file* to preserve Reconductor's exact structured state. The UI
reads and writes these files directly; it does not create separate new
`case.json` or `graph.json` files. Reconductor-generated indexes and
metadata are regenerated, so put your personal notes in separate Markdown
files instead of modifying their generated sections.

**Older v0.1–v0.4 cases are still supported as-is.** To convert a specific
existing case, explicitly run:

```bash
reconductor migrate-markdown CASE_ID
# Or convert all older investigations:
reconductor migrate-markdown --all
```

Before removing any old case files, this command creates an independent
local backup under
`~/.local/share/reconductor/legacy-backups/CASE_ID/`.
Only after the Markdown case and evidence round-trip correctly does it
remove legacy `.json` and `.txt` files from the active case. The backup
retains the originals until you choose what to do with them.
Do not convert while an investigation is running.

## Local browser dashboard (v0.4)

Run this on the **Trace Labs OSINT VM itself**, not on Coolify:

```bash
cd ~/Documents/Reconductor
git pull
source .venv/bin/activate
python -m pip install -e .
reconductor web
```

Open **http://127.0.0.1:8765** in the VM's browser. The dashboard is
deliberately bound to `127.0.0.1` only, uses only locally bundled assets,
and has no cloud dependencies or third-party JavaScript libraries.

Confirmation stays open while you check the network acknowledgment and type `RUN`. Editing a search clue or depth invalidates the plan and requires a new preview.

The dashboard can browse existing cases, surface reviewable SpiderFoot
structured events and public URLs found in Maigret/Sherlock stdout,
display STDERR diagnostic messages, and create new investigations.
It provides an interactive draggable relationship graph, the ability to add
person nodes and draw manually labeled connections, and real-time
investigation status.

All graph associations are unverified until corroborated by a human.
Manual graph annotations are saved privately in each case folder's
`graph.json`, never uploaded to GitHub. Existing legacy cases are left untouched unless you explicitly migrate them.

**Scope notes:** The dashboard extracts only certain recognizable evidence
types from upstream outputs; incomplete parsing is not proof of no findings.
It does not yet provide verified identity resolution, person-location
matching, or official worldwide public-record adapters.
The application is not accessible over the LAN; use your existing RDP
session to view its browser, rather than opening a public network port.

`reconductor web --no-browser` avoids automatically launching a browser.
`reconductor web --port 8766` selects another local port. Ctrl+C stops it.

## Interactive terminal menu (v0.3)

Launch `reconductor` from a terminal to open a simple numbered menu:

```text
  RECONDUCTOR
  [1] New investigation
  [2] Previous cases
  [3] Installed tools
  [4] System diagnostics
  [H] Help
  [Q] Quit
```

The menu collects starting clues, selects Light/Medium/Deep depth, previews
the planned tool commands, and **asks for explicit confirmation** before any
network research. While tools execute, the terminal prints live elapsed-time
indicators and status. You can reopen saved case reports and review help.

`reconductor menu` explicitly launches the menu even from a non-interactive
invocation. Normal automation commands (`reconductor investigate`,
`reconductor scan`, `reconductor report`) remain unchanged.
Running `reconductor` without arguments in a piped/non-interactive session
prints the CLI help instead.

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

## Rules-based investigations (v0.2)

Provide any combination of known clues. Reconductor selects installed tools
based on clue type, executes them only when you explicitly opt in, and may
follow structured SpiderFoot `Username` events into Sherlock/Maigret searches.
Candidate leads remain **unverified associations**, never identity matches.

```bash
# Preview a name + username + location investigation (no network activity)
reconductor investigate --name "Jane Doe" --username janedoe --location "London, UK" --depth medium

# Preview deeper research from multiple clues
reconductor investigate --name "Jane Doe" --email jane@example.org --domain example.org --depth deep

# Execute only after you have independently reviewed network egress/privacy
reconductor investigate --name "Jane Doe" --depth medium --execute --acknowledge-exposure

# View case and dossier locally (replace CASE_ID)
reconductor cases list
reconductor report CASE_ID
```

Live execution now prints a running indicator to the terminal. For example:

```text
[Reconductor] Case 20261123T123456Z-abcdef12 created; up to 8 tool runs.
[1/8 max] Starting spiderfoot (timeout 300s)
  ... spiderfoot still running 00:20 / 05:00 timeout
[1/8 max] spiderfoot: completed in 00:35
```

Elapsed time is **not a completion percentage**. Raw tool output is still written
to the local case folder, not streamed to your screen. Use `--no-progress`
to suppress informational messages when scripting.

Research budgets, including deduplication and hop limits:

| Depth | Maximum tool runs | New candidate leads | Follow-up hops |
|---|---:|---:|---:|
| Light | 2 | 0 | 0 |
| Medium | 8 | 3 | 1 |
| Deep | 16 | 8 | 2 |

SpiderFoot's passive module setting is not a promise of no outbound traffic
or perfect anonymity. Tools may require their own configuration.

**Worldwide framework, limited coverage:** the person investigation currently
uses SpiderFoot for names and emails, Sherlock/Maigret for usernames, and
SpiderFoot/theHarvester for domains. Official business, property, and court
record adapters are **not installed** and these dossier sections explicitly
show "Not searched." `--location` is stored only as contextual information;
it does **not** filter queries or validate an identity. There is currently no
cross-tool entity resolution or verified identity attribution.

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
