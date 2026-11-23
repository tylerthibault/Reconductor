# Privacy and safety

Reconductor **cannot** conceal your source IP, DNS queries, browser fingerprint, login identity, traffic metadata, or API key usage. External tools use the OSINT VM's current network configuration.

## Before online execution

1. Make sure your VM is isolated from unrelated home/work systems.
2. Use a separately configured VPN/Tor environment if it is appropriate for your research.
3. Verify egress routing, DNS, IPv6 and kill-switch failure behavior independently.
4. Restrict the research scope to publicly available or authorized sources.
5. Review `reconductor scan ...` dry-run output before execution.

A `--acknowledge-exposure` flag does not verify any of these prerequisites.

## Data handling

Reconductor stores raw outputs and target identifiers **on the local machine**, in private directories. Protect and back up those files; collected data may contain sensitive details about third parties. Never push case folders or API credentials to a public repository. File investigations compute SHA-256 locally and optionally invoke local ExifTool.

The runner does not send case files to an AI service. Some invoked upstream tools may fetch updates or use third-party APIs according to their own configuration; Reconductor does not suppress or audit those requests.

## Evidence quality

A username match is not identity attribution. A missing result is not proof of absence. Reports intentionally summarize tool execution only and require independent review of sources and context.

Reconductor is not designed as a consumer reporting agency or for regulated employment, housing, lending, or similar eligibility decisions.

## Security boundaries

Subprocesses do not use a shell, and inputs are validated before execution. However, external tools and website content are untrusted. Use a least-privilege account, no `sudo`, isolated VM, and verified backups. Never run an autonomous model with unrestricted shell access to these tools.

## Automated lead expansion (v0.2)

Automated follow-ups come only from narrowly recognized structured SpiderFoot events, with explicit search budgets and provenance. Candidate profiles are **not merged** into a confirmed person's identity. A discovered username does not establish who controls it, even when several sites show that username. A possible subdomain lead must remain under the domain originally searched.

The dossier excludes exact residential addresses, full birth dates, and account information from its extracted summaries, but raw upstream tool output may still contain sensitive material. Protect the case folder and manually review outputs before sharing. Source completeness and regional record coverage are not guaranteed. 

## Markdown vault storage

New research results are stored locally as Markdown, including readable
metadata blocks and full captured tool output in code fences. This does not
sanitize or hide sensitive information in raw outputs. Obsidian vaults and
backups containing case files must remain private. Graph links and entity
notes represent unverified observations unless a researcher has independently
corroborated them. Markdown migration keeps the former JSON/TXT sources
separately in a private legacy-backups folder.
