"""Human-readable progress on stderr, without polluting JSON/report stdout.

Elapsed time is not a percentage: external tools do not report progress reliably.
"""
from __future__ import annotations

import sys
from typing import Any, TextIO


class TerminalProgress:
    def __init__(self, stream: TextIO | None = None) -> None:
        self.stream = stream if stream is not None else sys.stderr
        self.is_tty = bool(getattr(self.stream, "isatty", lambda: False)())
        self._active = False
        self._index = 0
        self._maximum = 0
        self._last_log = 0

    def _line(self, message: str) -> None:
        if self.is_tty and self._active:
            self.stream.write("\r\x1b[2K")
            self._active = False
        print(message, file=self.stream, flush=True)

    @staticmethod
    def _time(seconds: float) -> str:
        total = max(0, int(seconds))
        return f"{total // 60:02d}:{total % 60:02d}"

    def __call__(self, event: dict[str, Any]) -> None:
        kind = event.get("event")
        if kind == "case_started":
            self._maximum = int(event["maximum"])
            self._line(f"[Reconductor] Case {event['case_id']} created; up to {self._maximum} tool runs.")
        elif kind == "step_started":
            self._index = int(event["index"])
            self._maximum = int(event["maximum"])
            self._last_log = 0
            self._line(f"[{self._index}/{self._maximum} max] Starting {event['tool']} (timeout {int(event['timeout'])}s)")
        elif kind == "heartbeat":
            elapsed = int(event["elapsed"])
            message = (
                f"  ... {event['tool']} still running "
                f"{self._time(event['elapsed'])} / {self._time(event['timeout'])} timeout"
            )
            if self.is_tty:
                self.stream.write("\r\x1b[2K" + message)
                self.stream.flush()
                self._active = True
            elif elapsed >= self._last_log + 15:
                self._last_log = elapsed
                self._line(message)
        elif kind == "lead_discovered":
            self._line(f"  + New unverified {event['kind']} lead ({event['count']}/{event['maximum']})")
        elif kind == "step_finished":
            self._line(
                f"[{event['index']}/{self._maximum} max] {event['tool']}: "
                f"{event['state']} in {self._time(event['duration'])}"
            )
        elif kind == "case_finished":
            self._line(f"[Reconductor] Case {event['case_id']}: {event['status']}")
