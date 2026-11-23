"""Reconductor terminal interface, with offline previews by default."""
from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from . import core
from . import engine
from . import menu
from .progress import TerminalProgress


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="reconductor",
        description="Local-first OSINT tool orchestrator. Network searches are dry-run by default.",
        epilog="Use 'reconductor COMMAND --help' for details. No VPN or anonymity is provided.",
    )
    root.add_argument("--version", action="version", version=f"Reconductor {__version__}")
    commands = root.add_subparsers(dest="command", title="commands")

    commands.add_parser("menu", help="Open the interactive terminal menu.")
    web = commands.add_parser("web", help="Start private local browser dashboard (no Coolify).")
    web.add_argument("--port", type=int, default=8765, help="Localhost TCP port (default: 8765).")
    web.add_argument("--no-browser", action="store_true", help="Do not open a browser automatically.")


    commands.add_parser("doctor", help="Check installed tools and show privacy warnings.")

    tools = commands.add_parser("tools", help="Inspect supported external tools.")
    tools_sub = tools.add_subparsers(dest="tools_action", required=True)
    tools_sub.add_parser("list", help="List tools, descriptions, and command locations.")

    scan = commands.add_parser("scan", help="Preview or execute a multi-tool investigation.")
    scan.add_argument("type", choices=["username", "domain", "file"], help="Type of starting clue.")
    scan.add_argument("target", help="Username, domain, or local filesystem path.")
    scan.add_argument(
        "--depth", choices=["light", "medium", "deep"], default="light",
        help="Research effort preset (default: light).",
    )
    scan.add_argument(
        "--execute", action="store_true",
        help="Run the planned commands; otherwise only print the plan.",
    )
    scan.add_argument(
        "--no-progress", action="store_true",
        help="Suppress progress messages on stderr.",
    )
    scan.add_argument(
        "--acknowledge-exposure", action="store_true",
        help="Required with --execute for network research. Does not provide anonymity.",
    )


    investigate = commands.add_parser(
        "investigate", help="Rules-based, multi-clue investigation with bounded lead follow-ups."
    )
    investigate.add_argument("--name", dest="names", action="append", help="Full name (repeatable).")
    investigate.add_argument("--username", dest="usernames", action="append", help="Public username (repeatable).")
    investigate.add_argument("--email", dest="emails", action="append", help="Known email address (repeatable).")
    investigate.add_argument("--domain", dest="domains", action="append", help="Known domain (repeatable).")
    investigate.add_argument("--location", help="City/region/country as context only; not yet queried.")
    investigate.add_argument(
        "--depth", choices=["light", "medium", "deep"], default="light",
        help="Maximum number of tool calls and follow-up leads."
    )
    investigate.add_argument("--execute", action="store_true", help="Run the plan instead of previewing it.")
    investigate.add_argument("--no-progress", action="store_true", help="Suppress progress messages on stderr.")
    investigate.add_argument(
        "--acknowledge-exposure", action="store_true",
        help="Required for live research; does not enable anonymity or VPN protections."
    )

    cases = commands.add_parser("cases", help="Inspect cases stored on this computer.")
    cases_sub = cases.add_subparsers(dest="cases_action", required=True)
    cases_sub.add_parser("list", help="List local cases (newest first).")
    show = cases_sub.add_parser("show", help="View case summary and per-tool statuses.")
    show.add_argument("case_id", help="Case ID from 'cases list'.")

    report = commands.add_parser("report", help="Print the saved report for a local case.")
    report.add_argument("case_id", help="Case ID from 'cases list'.")
    report.add_argument("--json", action="store_true", help="Show machine-readable case JSON.")
    return root


def print_tools() -> None:
    print("Supported OSINT tools (installed separately):")
    for entry in core.tools_available():
        status = "OK" if entry["available"] else "MISSING"
        print(f"  {entry['tool']:<14} {status:<8} {entry['path'] or '-'}")
        print(f"    {entry['description']}")


def main(argv: list[str] | None = None) -> int:
    args_parser = parser()
    args = args_parser.parse_args(argv)
    if not args.command:
        if sys.stdin.isatty() and sys.stdout.isatty():
            return menu.run_menu()
        args_parser.print_help()
        return 0
    try:
        if args.command == "menu":
            return menu.run_menu()
        if args.command == "web":
            from .webapp import serve
            serve(port=args.port, open_browser=not args.no_browser)
            return 0
        if args.command == "doctor":
            print(f"Reconductor {__version__}")
            print(f"Case location: {core.cases_root()}")
            print_tools()
            print("\nPRIVACY: This app does not enable VPN, Tor, private DNS, or a kill switch.")
            print("External OSINT tools use your VM's existing network connection.")
            print("Verify isolation before live lookups.")
            return 0
        if args.command == "tools":
            print_tools()
            return 0
        if args.command == "scan":
            target = core.validate_target(args.type, args.target)
            tasks = core.plan(args.type, target, args.depth)
            print(f"Target: {target}")
            print(f"Depth: {args.depth}")
            print("Plan:")
            print(core.preview(tasks))
            if not args.execute:
                print("\nDRY RUN: no commands executed and no network requests made.")
                print("To run: add --execute; for external research also add --acknowledge-exposure.")
                return 0
            folder, case = core.execute(
                args.type, target, args.depth,
                acknowledge_exposure=args.acknowledge_exposure,
                on_progress=None if args.no_progress else TerminalProgress(),
            )
            print(f"\nCase: {case['id']}")
            print(f"Status: {case['status']}")
            print(f"Saved locally at: {folder}")
            for step in case["steps"]:
                print(f"  {step['tool']}: {step['state']} (exit={step['exit_code']})")
            return 0 if case["status"] == "completed" else 3
        if args.command == "investigate":
            clues = engine.normalize_clues(args.names, args.usernames, args.emails, args.domains)
            print(engine.preview(clues, args.depth, args.location))
            if not args.execute:
                print("\nDRY RUN: no tools executed and no network requests made.")
                print("Add --execute --acknowledge-exposure to run this research.")
                return 0
            folder, case = engine.run(
                clues, args.depth, location=args.location,
                acknowledge_exposure=args.acknowledge_exposure,
                on_progress=None if args.no_progress else TerminalProgress(),
            )
            print(f"\nInvestigation: {case['id']}")
            print(f"Status: {case['status']}")
            print(f"Discovered candidate leads: {len(case['leads'])} (unverified)")
            print(f"Tool runs: {len(case['steps'])}")
            print(f"Dossier: {folder / 'dossier.md'}")
            for step in case["steps"]:
                print(f"  {step['tool']} [{step['clue_kind']}]: {step['state']}")
            return 0 if case["status"] == "completed" else 3
        if args.command == "cases":
            if args.cases_action == "list":
                cases = core.list_cases()
                if not cases:
                    print("No local cases yet.")
                for case in cases:
                    print(f"{case['id']}  {case['status']:<11} {case['target_type']:<8} {case['target']}")
                return 0
            folder, case = core.get_case(args.case_id)
            print(f"ID: {case['id']}")
            print(f"Target: {case['target_type']} — {case['target']}")
            print(f"Depth: {case['depth']}    Status: {case['status']}")
            print(f"Location: {folder}")
            for step in case["steps"]:
                print(f"  {step['tool']}: {step['state']}")
            return 0
        if args.command == "report":
            folder, case = core.get_case(args.case_id)
            if args.json:
                print(json.dumps(case, indent=2, ensure_ascii=False))
            else:
                report_path = folder / "report.md"
                if not report_path.is_file():
                    core.write_report(folder, case)
                print(report_path.read_text(encoding="utf-8"))
            return 0
    except core.ReconductorError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nInterrupted; any partial case data is retained locally.", file=sys.stderr)
        return 130
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
