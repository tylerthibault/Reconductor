"""Operator review of unverified tool observations, saved as Markdown.

A manual confirmation is an operator assessment, never automated proof that
an account belongs to a named person. Reviews do not change raw source files.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
from pathlib import Path

from . import markdown_store as store

FINDING_ID_RE = re.compile(r"^finding:[0-9a-f]{20}$")
DECISIONS = {"matches", "not_a_match", "unreviewed"}


def load(folder: Path) -> dict:
    path = folder / "reviews.md"
    if not path.is_file():
        return {}
    try:
        obj = store.parse_block(path)
    except (OSError, ValueError) as exc:
        raise ValueError("Cannot read saved observation reviews.") from exc
    items = obj.get("reviews", {})
    if not isinstance(items, dict):
        raise ValueError("Invalid review data.")
    return {
        key: value for key, value in items.items()
        if isinstance(key, str) and FINDING_ID_RE.fullmatch(key)
        and isinstance(value, dict)
        and value.get("decision") in DECISIONS
    }


def save(folder: Path, reviews: dict) -> None:
    content = [
        "# Observation review decisions", "",
        "> [!warning] These are operator decisions, NOT independent identity verification.", "",
        "Reviews apply only to this investigation. Original evidence remains unchanged.", "",
        "## Current review decisions", "",
    ]
    for ident, item in sorted(reviews.items()):
        content.append(
            "- " + ident + ": **" + store.safe(item.get("decision", "unreviewed")) +
            "** — " + store.safe(item.get("updated_at", "unknown time"))
        )
    if not reviews:
        content.append("No observations reviewed yet.")
    content.extend(["", "## Application state", "", store.block({"reviews": reviews}), ""])
    store.write_private(folder / "reviews.md", "\n".join(content))


def set_review(folder: Path, finding_id: str, decision: str, findings: list[dict]) -> dict:
    if not isinstance(finding_id, str) or not FINDING_ID_RE.fullmatch(finding_id):
        raise ValueError("Invalid finding identifier.")
    if decision not in DECISIONS:
        raise ValueError("Choose Matches, Not a match, or Unreviewed.")
    if finding_id not in {item["id"] for item in findings}:
        raise ValueError("Finding is not part of this investigation.")
    items = load(folder)
    if decision == "unreviewed":
        items.pop(finding_id, None)
    else:
        items[finding_id] = {
            "decision": decision,
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "basis": "operator_review",
        }
    save(folder, items)
    return {"id": finding_id, "decision": decision}


def apply(findings: list[dict], items: dict) -> list[dict]:
    result = []
    for value in findings:
        copied = dict(value)
        review = items.get(value["id"], {})
        copied["review"] = review.get("decision", "unreviewed")
        copied["review_basis"] = "operator" if copied["review"] != "unreviewed" else ""
        result.append(copied)
    return result
