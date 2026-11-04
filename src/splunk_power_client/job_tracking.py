"""Status snapshots, wait loop and Rich rendering for tracked search jobs.

The wait loop takes the fetch / sleep / clock functions as arguments so it can
be tested without a Splunk instance.
"""

import time
from datetime import datetime
from typing import Any, Callable, Iterable, Mapping, Optional

from pydantic import BaseModel, Field
from rich import box
from rich.table import Table
from rich.text import Text

from .job_registry import SubmittedJob

DONE_STATES = {"DONE", "COMPLETED"}
CANCEL_STATES = {
    "CANCELLED",
    "INTERNAL_CANCEL",
    "USER_CANCEL",
    "BAD_INPUT_CANCEL",
    "QUIT",
}
# States set by spc itself, not by Splunk
NOT_FOUND = "NOT_FOUND"
TIMEOUT = "TIMEOUT"
UNREACHABLE = "UNREACHABLE"
TERMINAL_STATES = DONE_STATES | CANCEL_STATES | {"FAILED", NOT_FOUND, TIMEOUT}

_STATE_STYLES = {
    "QUEUED": "dim",
    "PARSING": "cyan",
    "RUNNING": "yellow",
    "FINALIZING": "cyan",
    "PAUSE": "blue",
    "DONE": "green",
    "COMPLETED": "green",
    "FAILED": "bold red",
    NOT_FOUND: "bold red",
    TIMEOUT: "red",
    UNREACHABLE: "orange1",
}


class JobSnapshot(BaseModel):
    """State of one job at a given time."""

    label: str
    sid: str
    state: str = "QUEUED"
    progress: float = 0.0
    result_count: Optional[int] = None
    event_count: Optional[int] = None
    run_duration: Optional[float] = None
    messages: list[str] = Field(default_factory=list)
    error: str = ""

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    @property
    def is_success(self) -> bool:
        return self.state in DONE_STATES


def _to_int(value: Any) -> Optional[int]:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_job_messages(raw: Any) -> list[str]:
    """Normalize Splunk job messages to ``["LEVEL: text", ...]``.

    Atom/XML responses give ``{"warn": "text" | [..], "error": ...}``,
    JSON responses give ``[{"type": "WARN", "text": "..."}]``.
    """
    messages: list[str] = []
    if isinstance(raw, Mapping):
        for level, texts in raw.items():
            if isinstance(texts, str):
                texts = [texts]
            for text in texts or []:
                messages.append(f"{str(level).upper()}: {text}")
    elif isinstance(raw, (list, tuple)):
        for item in raw:
            if isinstance(item, Mapping):
                level = str(item.get("type", "INFO")).upper()
                messages.append(f"{level}: {item.get('text', '')}")
            elif item:
                messages.append(str(item))
    elif raw:
        messages.append(str(raw))
    return messages


def snapshot_from_content(label: str, sid: str, content: Mapping) -> JobSnapshot:
    """Build a snapshot from the ``content`` of a Splunk job entity."""
    messages = parse_job_messages(content.get("messages"))
    state = str(content.get("dispatchState", "QUEUED"))
    error = ""
    if state == "FAILED" or str(content.get("isFailed", "0")) in ("1", "true"):
        state = "FAILED"
        error = next(
            (m for m in messages if m.startswith(("ERROR", "FATAL"))),
            messages[0] if messages else "",
        )
    return JobSnapshot(
        label=label,
        sid=sid,
        state=state,
        progress=_to_float(content.get("doneProgress")) or 0.0,
        result_count=_to_int(content.get("resultCount")),
        event_count=_to_int(content.get("eventCount")),
        run_duration=_to_float(content.get("runDuration")),
        messages=messages,
        error=error,
    )


def fetch_job_snapshot(service: Any, job: SubmittedJob) -> JobSnapshot:
    """Read the current state of a job through a splunklib ``Service``.

    A job that no longer exists (expired TTL, other namespace) is NOT_FOUND,
    which is terminal. A connection error is UNREACHABLE, which is retried.
    """
    from splunklib.binding import HTTPError

    try:
        entity = service.job(job.sid)
        return snapshot_from_content(job.label, job.sid, entity.content)
    except HTTPError as error:
        if error.status == 404:
            return JobSnapshot(
                label=job.label,
                sid=job.sid,
                state=NOT_FOUND,
                error="job not found (expired or not visible from this namespace)",
            )
        return JobSnapshot(
            label=job.label, sid=job.sid, state=UNREACHABLE, error=str(error)
        )
    except Exception as error:  # network error, Splunk restarting...
        return JobSnapshot(
            label=job.label, sid=job.sid, state=UNREACHABLE, error=str(error)
        )


def wait_for_jobs(
    jobs: Iterable[SubmittedJob],
    fetch: Callable[[SubmittedJob], JobSnapshot],
    timeout: float,
    poll_interval: float,
    on_update: Optional[Callable[[list[JobSnapshot]], None]] = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> list[JobSnapshot]:
    """Poll jobs until each one is terminal or the timeout is reached.

    A failed or cancelled job is left aside and the others keep running.
    Jobs still running at the timeout are marked TIMEOUT (they are not cancelled).
    """
    jobs = list(jobs)
    snapshots = {job.sid: JobSnapshot(label=job.label, sid=job.sid) for job in jobs}
    pending = {job.sid: job for job in jobs}
    deadline = clock() + timeout

    def notify() -> None:
        if on_update:
            on_update([snapshots[job.sid] for job in jobs])

    while pending:
        for sid, job in list(pending.items()):
            snapshot = fetch(job)
            snapshots[sid] = snapshot
            if snapshot.is_terminal:
                del pending[sid]
        notify()
        if not pending:
            break
        if clock() >= deadline:
            for sid in pending:
                snapshots[sid] = snapshots[sid].model_copy(update={"state": TIMEOUT})
            notify()
            break
        sleep(poll_interval)

    return [snapshots[job.sid] for job in jobs]


# =============================================================================
# Rendering
# =============================================================================


def _format_duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return "-"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60}m"


def _format_count(value: Optional[int]) -> str:
    return f"{value:,}" if value is not None else "-"


def build_jobs_table(
    snapshots: Iterable[JobSnapshot], title: Optional[str] = None
) -> Table:
    table = Table(title=title, box=box.SIMPLE, show_header=True, header_style="bold")
    table.add_column("Label", style="bold cyan", no_wrap=True)
    table.add_column("Status", justify="center")
    table.add_column("Progress", justify="right")
    table.add_column("Results", justify="right")
    table.add_column("Events", justify="right")
    table.add_column("Run Duration", justify="right")
    table.add_column("SID", style="dim", overflow="fold")
    table.add_column("Detail", style="dim", overflow="fold")

    for snapshot in snapshots:
        style = _STATE_STYLES.get(snapshot.state, "yellow")
        if snapshot.state in CANCEL_STATES:
            style = "yellow"
        table.add_row(
            snapshot.label,
            Text(snapshot.state, style=style),
            f"{snapshot.progress:.0%}",
            _format_count(snapshot.result_count),
            _format_count(snapshot.event_count),
            _format_duration(snapshot.run_duration),
            snapshot.sid,
            snapshot.error,
        )
    return table


def build_messages_table(snapshots: Iterable[JobSnapshot]) -> Optional[Table]:
    """Job messages (e.g. the powerquery debug warnings), one row per message."""
    rows = [(s.label, m) for s in snapshots for m in s.messages]
    if not rows:
        return None
    table = Table(title="Job messages", box=box.SIMPLE, header_style="bold")
    table.add_column("Label", style="bold cyan", no_wrap=True)
    table.add_column("Message", overflow="fold")
    for label, message in rows:
        style = "red" if message.startswith(("ERROR", "FATAL")) else None
        table.add_row(label, Text(message, style=style))
    return table


def elapsed_title(prefix: str, started_at: datetime, timeout: float) -> str:
    elapsed = (datetime.now() - started_at).total_seconds()
    return f"{prefix} — {_format_duration(elapsed)} / {_format_duration(timeout)}"
