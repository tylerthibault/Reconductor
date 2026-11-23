"""Small bounded Internet Archive CDX adapter for explicit, validated domains.

Used only inside a user-approved Deep investigation. Never scans names or
guesses domains, and does not download archived page contents.
"""
from __future__ import annotations

import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from . import core


def snapshots(domain: str, *, timeout: int = 18, max_rows: int = 12) -> str:
    target = core.validate_target("domain", domain)
    # Service host is constant; target appears only in a URL query parameter.
    query = urlencode({
        "url": target,
        "matchType": "host",
        "output": "json",
        "filter": "statuscode:200",
        "fl": "timestamp,original,statuscode",
        "collapse": "timestamp:4",
        "limit": str(min(max(1, max_rows), 25)),
    })
    request = Request(
        "https://web.archive.org/cdx/search/cdx?" + query,
        headers={"User-Agent": "Reconductor/0.7 (local opt-in OSINT research)"},
    )
    with urlopen(request, timeout=timeout) as response:
        raw = response.read(250_000)
    data = json.loads(raw)
    if not isinstance(data, list) or len(data) > 30:
        raise ValueError("Unexpected Internet Archive response.")
    records = []
    for entry in data[1:]:
        if not isinstance(entry, list) or len(entry) < 2:
            continue
        timestamp, origin = entry[0], entry[1]
        if (not isinstance(timestamp, str) or len(timestamp) != 14
            or not timestamp.isdigit() or not isinstance(origin, str)
            or not origin.startswith(("http://", "https://"))):
            continue
        # Do not treat URL availability as identity evidence.
        records.append({
            "type": "Historical snapshot",
            "data": "https://web.archive.org/web/" + timestamp + "/" + origin,
            "source": "Internet Archive CDX metadata",
            "timestamp": timestamp,
            "original": origin,
        })
        if len(records) >= max_rows:
            break
    return json.dumps(records, ensure_ascii=False)
