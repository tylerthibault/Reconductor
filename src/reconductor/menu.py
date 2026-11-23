"""Interactive terminal menu for human-led Reconductor investigations.

Uses the existing planning and execution functions; does not add a second
execution engine or weaken live-network confirmation requirements.
"""
from __future__ import annotations

from pathlib import Path

from . import __version__, core, engine
from .progress import TerminalProgress


def _ask(prompt: str) -> str:
    return input(prompt).strip()


def _header() -> None:
    print()
    print("=" * 54)
    print(f"  RECONDUCTOR  v{__version__}")
    print("  Multi-tool OSINT investigation framework")
    print("=" * 54)


def _select_depth() -> str | None:
    print("\nInvestigation depth")
    print("  [1] Light  - short investigation, no automatic follow-ups")
    print("  [2] Medium - up to 8 tool runs and 3 candidate leads")
    print("  [3] Deep   - up to 16 tool runs and 8 candidate leads")
    print("  [B] Back")
    while True:
        selected = _ask("Choose depth [1/2/3/B]: ").lower()
        if selected in ("b", "back", "q"):
            return None
        if selected in ("1", "2", "3"):
            return {"1": "light", "2": "medium", "3": "deep"}[selected]
        print("Please choose 1, 2, 3, or B.")


def _confirm_execution(*, network: bool) -> bool:
    if network:
        print("\nNETWORK PRIVACY WARNING")
        print("These tools contact external sources using the VM's current connection.")
        print("Reconductor provides NO VPN, Tor, DNS-leak protection, or kill switch.")
        print("Names, usernames, or domains may be sent to external services.")
        if _ask("Run live network research? [y/N]: ").lower() != "y":
            return False
        return _ask("Type RUN to acknowledge network exposure: ") == "RUN"
    print("\nLocal file inspection does not initiate OSINT network searches.")
    return _ask("Run local file inspection? [y/N]: ").lower() == "y"


def _new_investigation() -> None:
    print("\nNEW INVESTIGATION")
    print("  [1] Person / multiple clues")
    print("  [2] Username")
    print("  [3] Domain / website")
    print("  [4] Local file")
    print("  [B] Back")
    choice = _ask("Select target type: ").lower()
    if choice in ("b", "back", ""):
        return
    if choice not in ("1", "2", "3", "4"):
        print("Unknown investigation type.")
        return

    if choice == "4":
        raw_file = _ask("Local file path: ")
        if not raw_file:
            print("No file provided.")
            return
        target = core.validate_target("file", raw_file)
        depth = _select_depth()
        if depth is None:
            return
        print("\nPREVIEW (nothing has run yet)")
        print(core.preview(core.plan("file", target, depth)))
        if not _confirm_execution(network=False):
            print("Cancelled; no tools executed.")
            return
        folder, record = core.execute(
            "file", target, depth, on_progress=TerminalProgress(),
        )
        _finished(folder, record)
        return

    if choice == "1":
        print("\nEnter any clues you know. Press Enter to skip a field.")
        name = _ask("First and last name (optional): ")
        username = _ask("Username (optional): ")
        email = _ask("Email (optional): ")
        domain = _ask("Domain (optional): ")
        location = _ask("Location context (optional): ") or None
    elif choice == "2":
        name, email, domain, location = "", "", "", None
        username = _ask("Username: ")
    else:
        name, email, username, location = "", "", "", None
        domain = _ask("Domain (example.org): ")

    clues = engine.normalize_clues(
        names=[name] if name else [],
        usernames=[username] if username else [],
        emails=[email] if email else [],
        domains=[domain] if domain else [],
    )
    depth = _select_depth()
    if depth is None:
        return
    print("\nPREVIEW (nothing has run yet)")
    print(engine.preview(clues, depth, location))
    if not _confirm_execution(network=True):
        print("Cancelled; no network requests made.")
        return
    folder, record = engine.run(
        clues, depth, location=location, acknowledge_exposure=True,
        on_progress=TerminalProgress(),
    )
    _finished(folder, record)


def _finished(folder: Path, record: dict) -> None:
    print("\nINVESTIGATION SAVED")
    print(f"  Case ID: {record['id']}")
    print(f"  Status: {record['status']}")
    print(f"  Tool runs: {len(record['steps'])}")
    if "leads" in record:
        print(f"  Candidate leads (unverified): {len(record['leads'])}")
    print(f"  Folder: {folder}")
    print(f"  Report: {folder / ('dossier.md' if 'leads' in record else 'report.md')}")
    print("Use 'Previous cases' in the main menu to review this case.")


def _cases_menu() -> None:
    cases = core.list_cases()
    if not cases:
        print("\nNo cases saved yet.")
        return
    print("\nPREVIOUS CASES (newest first)")
    shown = cases[:20]
    for index, case in enumerate(shown, 1):
        target = str(case.get("target", "Unknown")).replace("\n", " ")
        print(f"  [{index}] {case['id']}  {case.get('status', '?')}  {target[:60]}")
    if len(cases) > len(shown):
        print(f"  Showing 20 of {len(cases)}. Use 'reconductor cases list' for all.")
    chosen = _ask("Case number to open, or B to go back: ").lower()
    if chosen in ("b", "back", ""):
        return
    if not chosen.isdigit() or not (1 <= int(chosen) <= len(shown)):
        print("Invalid case selection.")
        return
    folder, record = core.get_case(shown[int(chosen) - 1]["id"])
    print(f"\nCase: {record['id']}")
    print(f"Target: {record.get('target', 'Unknown')}")
    print(f"Status: {record.get('status', '?')}")
    print(f"Depth: {record.get('depth', '?')}")
    for step in record.get("steps", []):
        print(f"  {step.get('tool', 'unknown')}: {step.get('state', 'unknown')}")
    print(f"Stored at: {folder}")
    if _ask("Display saved report? [y/N]: ").lower() == "y":
        report = folder / "report.md"
        if report.is_file():
            print("\n" + report.read_text(encoding="utf-8"))
        else:
            print("This case has no saved report yet.")


def _tools_menu() -> None:
    print("\nINSTALLED OSINT TOOLS")
    for entry in core.tools_available():
        status = "INSTALLED" if entry["available"] else "MISSING"
        print(f"  {entry['tool']:<14} {status:<10} {entry['path'] or '-'}")
        print(f"    {entry['description']}")
    print("Tools are installed separately; Reconductor does not install them.")


def _doctor() -> None:
    print(f"\nReconductor {__version__}")
    print(f"Case storage: {core.cases_root()}")
    _tools_menu()
    print("\nCAUTION: This VM's VPN, DNS, and kill switch have not been verified.")


def _help() -> None:
    print("\nHELP")
    print("Select an option by typing its number, then pressing Enter.")
    print("New Investigation asks for the clues you know and shows a dry-run plan.")
    print("Nothing contacts the internet until you explicitly approve execution.")
    print("Depth controls how many searches and candidate leads Reconductor follows.")
    print("Candidate matches are NOT verified identities.")
    print("\nUseful terminal commands:")
    print("  reconductor --help")
    print("  reconductor investigate --help")
    print("  reconductor scan --help")
    print("  reconductor doctor")
    print("  reconductor cases list")
    print("  reconductor report CASE_ID")


def run_menu() -> int:
    """Start interactive mode; EOF and interrupt exit cleanly."""
    try:
        while True:
            _header()
            print("  [1] New investigation")
            print("  [2] Previous cases")
            print("  [3] Installed tools")
            print("  [4] System diagnostics")
            print("  [H] Help")
            print("  [Q] Quit")
            choice = _ask("\nChoose an option: ").lower()
            if choice in ("q", "quit", "0"):
                print("Exiting Reconductor.")
                return 0
            try:
                if choice == "1":
                    _new_investigation()
                elif choice == "2":
                    _cases_menu()
                elif choice == "3":
                    _tools_menu()
                elif choice == "4":
                    _doctor()
                elif choice in ("h", "help", "?"):
                    _help()
                else:
                    print("Invalid selection. Choose 1-4, H, or Q.")
            except (core.ReconductorError, OSError, ValueError) as exc:
                print(f"Error: {exc}")
                print("Returned to the main menu.")
    except EOFError:
        print("\nExiting Reconductor (input closed).")
        return 0
    except KeyboardInterrupt:
        print("\nReconductor interrupted. Saved case files are retained.")
        return 130
