# Command reference

## Local web dashboard

`reconductor web` runs the localhost-only case dashboard at
`http://127.0.0.1:8765`. Requires no Coolify and no cloud inference.
The application provides New Investigation, Case History, Observations,
Evidence & Tool Diagnostics, and an editable Relationship Map.

The map includes operator-supplied clues, candidate leads, observed public
links, and user-added person nodes. Manually drawn associations are saved in
`graph.json` under the local case folder and never assert confirmed identity.

`reconductor web --no-browser` suppresses automatic browser opening;
`reconductor web --port PORT` chooses a different localhost port.

## Interactive terminal menu

Run `reconductor` in an interactive terminal, or use
`reconductor menu` explicitly. Choose New Investigation to enter a full
name, username, email, domain or local file, choose a depth, preview planned
commands, then decide whether to execute.

No network call runs without two deliberate confirmations: `y` and the
exact text `RUN`. Local file inspection requires a separate `y` confirmation.

The menu also provides Previous Cases, Installed Tools, Diagnostics, Help,
and Quit. The existing command-line interface is preserved for scripting.
The bare command prints help when stdin/stdout are not terminals.

## Entry points

- `reconductor --help` — global commands
- `reconductor --version` — release version
- `reconductor doctor` — local installation check, no internet test
- `reconductor tools list` — show supported tools on `PATH`
- `reconductor scan --help` — investigation syntax
- `reconductor cases --help` — local case management
- `reconductor report --help` — saved reports

## Rules-based investigate

`reconductor investigate --help` explains how to pass repeatable `--name`, `--username`, `--email`, and `--domain` clues. An optional `--location` is case context only.

Dry run is default. A live investigation requires `--execute --acknowledge-exposure`. A deterministic queue chooses tools for each clue and only auto-follows SpiderFoot structured username events and related subdomains. All discovered usernames are unverified candidates. Budgets: Light 2 calls/0 new leads, Medium 8 calls/3 leads/1 hop, Deep 16 calls/8 leads/2 hops. Duplicate clues are skipped.

New case reports include `dossier.md`, `report.md`, `case.json`, and `raw/` evidence files. Official government and worldwide record lookups are not integrated and appear as 'Not searched.'

## Live progress

Both `reconductor scan ... --execute` and
`reconductor investigate ... --execute` show tool start, heartbeat
(elapsed time vs. timeout), finished/failed/skipped status and discovered
candidate-lead counts. The heartbeat updates every five seconds in a
terminal. A non-interactive session gets periodic log lines. Progress is
printed on **stderr**, leaving command output and saved case reports separate.
Use `--no-progress` with either command to disable the indicator.

SpiderFoot does not provide a reliable percentage; progress is based on
wall-clock time and completed steps only.

## Scan

```text
reconductor scan {username,domain,file} TARGET [--depth {light,medium,deep}]
                                            [--execute] [--acknowledge-exposure]
```

Without `--execute`, prints the plan only. No case is created and no research tool is called.

`--execute` actually runs the plan. For username/domain scans, a separate `--acknowledge-exposure` flag is required. This is an explicit confirmation, **not** a privacy test. File scans run offline without the acknowledgment.

All tools run serially with per-tool timeouts (light 120 seconds, medium 300, deep 900). Unavailable tools are reported as skipped. A nonzero exit code is recorded rather than ignored.

The command exits 0 if all steps succeed, 2 for invalid arguments or confirmation, 3 for incomplete execution, or 130 if interrupted.

## Cases

`reconductor cases list` prints local case IDs. Use `reconductor cases show CASE_ID` and `reconductor report CASE_ID` for findings. JSON metadata is available with `reconductor report CASE_ID --json`.

Files:

```text
~/.local/share/reconductor/cases/CASE_ID/
  case.json
  report.md
  raw/
    01-tool.stdout.txt
    01-tool.stderr.txt
```

Set `RECONDUCTOR_HOME` to move case storage. Do not put it in a Git checkout or synchronized cloud folder.

## Current limitations

No verified cross-source identity correlation, official worldwide registry adapters, PDF export, daemon, scheduling, GUI, local LLM or cloud AI. Tool flags may vary between distro releases. Check `tool --help` when a command returns a nonzero exit code. SpiderFoot is invoked with its passive preset, not with active infrastructure scanning.
