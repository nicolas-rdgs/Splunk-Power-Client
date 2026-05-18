"""Core replay logic for saved searches."""

import re
from datetime import datetime, timedelta
from typing import Annotated, Any, Callable, Generator, Optional

import dateparser
import trio
from rich import box
from rich.console import RenderableType
from rich.table import Table
from rich.text import Text

from .models import (
    LocalLookupFile,
    ReplayConfig,
    ReplayJob,
    ReplaySummary,
    SplunkInstance,
    SplunkInstanceSavedSearch,
)

# =============================================================================
# Time Utilities
# =============================================================================


def parse_splunk_time(
    time_str: Annotated[str, "Splunk time string (e.g., '-2d@d', 'now')"],
    reference: Annotated[Optional[datetime], "Reference datetime"] = None,
) -> datetime:
    """
    Parse Splunk relative time strings using dateparser.

    Args:
        time_str: Splunk time string (e.g., "-2d@d", "now", "-1h")
        reference: Reference datetime for relative calculations

    Returns:
        Parsed datetime object
    """
    if reference is None:
        reference = datetime.now()

    # Handle 'now'
    if time_str.lower() == "now":
        return reference

    # Try parsing with dateparser
    parsed = dateparser.parse(
        time_str,
        settings={
            "RELATIVE_BASE": reference,
            "RETURN_AS_TIMEZONE_AWARE": False,
        },
    )

    if parsed is None:
        raise ValueError(f"Unable to parse time string: {time_str}")

    return parsed


def parse_time_span_to_seconds(
    time_span: Annotated[str, "Time span string (e.g., '1h', '30m', '1d')"],
) -> int:
    """
    Convert time span string to seconds.

    Args:
        time_span: Time span string (e.g., "1h", "30m", "1d", "2w")

    Returns:
        Number of seconds
    """
    pattern = r"^(\d+)([smhdwMy])$"
    match = re.match(pattern, time_span)

    if not match:
        raise ValueError(
            f"Invalid time span format: {time_span}. "
            "Expected format: <number><unit> (e.g., 1h, 30m, 1d)"
        )

    value = int(match.group(1))
    unit = match.group(2)

    multipliers = {
        "s": 1,
        "m": 60,
        "h": 3600,
        "d": 86400,
        "w": 604800,
        "M": 2592000,  # 30 days
        "y": 31536000,  # 365 days
    }

    return value * multipliers[unit]


def calculate_time_blocks(
    earliest: Annotated[datetime, "Start time"],
    latest: Annotated[datetime, "End time"],
    span_seconds: Annotated[int, "Duration of each block in seconds"],
) -> Generator[tuple[datetime, datetime], None, None]:
    """
    Generate non-overlapping time blocks.

    Args:
        earliest: Start time
        latest: End time
        span_seconds: Duration of each block in seconds

    Yields:
        Tuples of (block_start, block_end) datetimes
    """
    current = earliest
    span = timedelta(seconds=span_seconds)

    while current < latest:
        block_end = min(current + span, latest)
        yield (current, block_end)
        current = block_end


def format_time_window_human(
    earliest: Annotated[datetime, "Start time"],
    latest: Annotated[datetime, "End time"],
) -> str:
    """
    Format time window in human-readable format.

    Args:
        earliest: Start time
        latest: End time

    Returns:
        Human-readable duration string
    """
    delta = latest - earliest
    days = delta.days
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, _ = divmod(remainder, 60)

    parts = []
    if days > 0:
        parts.append(f"{days} day{'s' if days > 1 else ''}")
    if hours > 0:
        parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
    if minutes > 0 and days == 0:  # Only show minutes if less than a day
        parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")

    return ", ".join(parts) if parts else "0 minutes"


# =============================================================================
# Job Generation
# =============================================================================


def generate_replay_jobs(
    saved_searches: Annotated[
        list[SplunkInstanceSavedSearch], "List of saved searches to replay"
    ],
    earliest: Annotated[datetime, "Start time for replay"],
    latest: Annotated[datetime, "End time for replay"],
    time_span_seconds: Annotated[int, "Duration of each time block in seconds"],
    max_retry: Annotated[int, "Maximum retry attempts per job"],
) -> list[ReplayJob]:
    """
    Generate ReplayJob instances for all searches × time blocks.

    Args:
        saved_searches: List of saved searches to replay
        earliest: Start time for replay
        latest: End time for replay
        time_span_seconds: Duration of each time block in seconds
        max_retry: Maximum retry attempts per job

    Returns:
        List of ReplayJob instances
    """
    jobs: list[ReplayJob] = []
    job_id = 1

    time_blocks = list(calculate_time_blocks(earliest, latest, time_span_seconds))

    for saved_search in saved_searches:
        for block_start, block_end in time_blocks:
            job = ReplayJob(
                id=job_id,
                saved_search=saved_search,
                earliest_time=block_start,
                latest_time=block_end,
                max_attempts=max_retry + 1,  # max_retry + initial attempt
            )
            jobs.append(job)
            job_id += 1

    return jobs


def build_replay_summary(
    saved_searches: Annotated[
        list[SplunkInstanceSavedSearch], "List of saved searches"
    ],
    config: Annotated[ReplayConfig, "Replay configuration"],
) -> ReplaySummary:
    """
    Build summary for confirmation display.

    Args:
        saved_searches: List of saved searches
        config: Replay configuration

    Returns:
        ReplaySummary instance
    """
    earliest = parse_splunk_time(config.earliest_time)
    latest = parse_splunk_time(config.latest_time)
    time_span_seconds = parse_time_span_to_seconds(config.time_span)

    time_blocks = list(calculate_time_blocks(earliest, latest, time_span_seconds))
    total_jobs = len(saved_searches) * len(time_blocks)

    return ReplaySummary(
        search_count=len(saved_searches),
        total_jobs=total_jobs,
        earliest_time=earliest,
        latest_time=latest,
        time_window_human=format_time_window_human(earliest, latest),
        trigger_actions=config.trigger_actions,
        max_concurrent=config.max_concurrents,
        time_span=config.time_span,
    )


# =============================================================================
# Async Execution (using Trio)
# =============================================================================


async def dispatch_job(
    replay_job: Annotated[ReplayJob, "Job to dispatch"],
    trigger_actions: Annotated[bool, "Whether to trigger actions"],
) -> None:
    """
    Dispatch saved search with overridden time range.

    Args:
        replay_job: Job to dispatch
        trigger_actions: Whether to trigger actions
    """
    # Dispatch saved search with time override
    job = replay_job.saved_search.entity.dispatch(
        **{
            "dispatch.earliest_time": replay_job.earliest_time.strftime(
                "%Y-%m-%dT%H:%M:%S"
            ),
            "dispatch.latest_time": replay_job.latest_time.strftime(
                "%Y-%m-%dT%H:%M:%S"
            ),
            "trigger_actions": 1 if trigger_actions else 0,
        }
    )
    replay_job.sid = job.sid
    replay_job.job = job
    replay_job.start_time = datetime.now()


async def poll_job_until_done(
    replay_job: Annotated[ReplayJob, "Job to poll"],
    timeout: Annotated[int, "Timeout in seconds"],
    poll_interval: Annotated[int, "Seconds between status checks"],
    on_update: Annotated[Callable[[], None], "Callback for UI refresh"],
) -> bool:
    """
    Poll job status until done or timeout.

    Args:
        replay_job: Job to poll
        timeout: Timeout in seconds
        poll_interval: Seconds between status checks
        on_update: Callback for UI refresh

    Returns:
        True if timed out, False if completed
    """
    elapsed = 0

    while elapsed < timeout:
        await trio.sleep(poll_interval)
        elapsed += poll_interval

        # Refresh job status from Splunk (SDK handles status update)
        try:
            replay_job.job.refresh()
        except Exception:
            # Connection error might indicate Splunk restart
            replay_job.is_splunk_restarting = True
            on_update()
            return False

        on_update()

        if replay_job.job.is_done():
            return False

    # Timeout reached
    return True


async def wait_for_splunk_availability(
    instance: Annotated[SplunkInstance, "Splunk instance to check"],
) -> None:
    """
    Wait until Splunk is available again after restart.

    Args:
        instance: Splunk instance to check
    """
    while True:
        try:
            instance.info.is_available()
            break
        except Exception:
            await trio.sleep(60)


async def export_job_results(
    replay_job: Annotated[ReplayJob, "Completed job"],
    instance: Annotated[SplunkInstance, "Splunk instance"],
    file_writer: Annotated[LocalLookupFile, "File writer for results"],
) -> None:
    """
    Export results to file using persistent file writer.

    Args:
        replay_job: Completed job
        instance: Splunk instance
        file_writer: File writer for results
    """
    if replay_job.job is None or not replay_job.job.is_done():
        return

    try:
        results = instance.get_job_results(replay_job.sid)
        if results:
            file_writer.append(results)
    except Exception as e:
        replay_job.error_message = f"Export error: {str(e)}"


async def run_single_job(
    replay_job: Annotated[ReplayJob, "Job to run"],
    instance: Annotated[SplunkInstance, "Splunk instance"],
    config: Annotated[ReplayConfig, "Replay configuration"],
    file_writers: Annotated[dict[str, LocalLookupFile], "File writers by search title"],
    on_update: Annotated[Callable[[], None], "Callback for UI refresh"],
) -> None:
    """
    Full job lifecycle: availability check, dispatch, poll, export.

    On Splunk restart: wait for availability, re-run job from scratch.

    Args:
        replay_job: Job to run
        instance: Splunk instance
        config: Replay configuration
        file_writers: File writers by search title
        on_update: Callback for UI refresh
    """
    while replay_job.attempts < replay_job.max_attempts:
        replay_job.attempts += 1
        replay_job.is_timeout = False  # Reset timeout flag
        on_update()

        try:
            # Check Splunk availability before dispatch
            try:
                instance.info.is_available()
            except Exception:
                replay_job.is_splunk_restarting = True
                on_update()
                await wait_for_splunk_availability(instance)
                replay_job.is_splunk_restarting = False
                on_update()

            # Dispatch job - Splunk SDK handles status from here
            await dispatch_job(replay_job, config.trigger_actions)
            on_update()

            # Poll until done, timeout, or Splunk restart
            timed_out = await poll_job_until_done(
                replay_job, config.timeout, config.poll_interval, on_update
            )

            if replay_job.job and replay_job.job.is_done():
                # Status comes from Splunk (COMPLETED, DONE, etc.)
                if config.output_dir and replay_job.saved_search.title in file_writers:
                    await export_job_results(
                        replay_job,
                        instance,
                        file_writers[replay_job.saved_search.title],
                    )
                break  # Success, exit retry loop

            elif replay_job.is_splunk_restarting:
                # Wait for Splunk and re-run (don't increment attempts for restart)
                replay_job.attempts -= 1
                await wait_for_splunk_availability(instance)
                replay_job.is_splunk_restarting = False
                on_update()
                continue  # Re-run job

            elif timed_out:
                # Set timeout flag and cancel job
                replay_job.is_timeout = True
                if replay_job.job:
                    replay_job.job.cancel()
                on_update()
                continue  # Retry

        except Exception as e:
            replay_job.error_message = str(e)
            on_update()
            break


async def run_single_job_with_limiter(
    replay_job: Annotated[ReplayJob, "Job to run"],
    instance: Annotated[SplunkInstance, "Splunk instance"],
    config: Annotated[ReplayConfig, "Replay configuration"],
    file_writers: Annotated[dict[str, LocalLookupFile], "File writers by search title"],
    on_update: Annotated[Callable[[], None], "Callback for UI refresh"],
    limiter: Annotated[trio.CapacityLimiter, "Concurrency limiter"],
) -> None:
    """
    Run single job with concurrency limiting.

    Args:
        replay_job: Job to run
        instance: Splunk instance
        config: Replay configuration
        file_writers: File writers by search title
        on_update: Callback for UI refresh
        limiter: Trio CapacityLimiter for max concurrency
    """
    async with limiter:
        await run_single_job(replay_job, instance, config, file_writers, on_update)


async def run_replay(
    replay_jobs: Annotated[list[ReplayJob], "Jobs to replay"],
    instance: Annotated[SplunkInstance, "Splunk instance"],
    config: Annotated[ReplayConfig, "Replay configuration"],
    on_update: Annotated[Callable[[], None], "Callback for UI refresh"],
) -> None:
    """
    Main orchestrator using Trio with CapacityLimiter for parallelism.

    Args:
        replay_jobs: Jobs to replay
        instance: Splunk instance
        config: Replay configuration
        on_update: Callback for UI refresh
    """
    # Create file writers if output specified
    file_writers: dict[str, LocalLookupFile] = {}

    if config.output_dir:
        config.output_dir.mkdir(parents=True, exist_ok=True)

        for search_title in {j.saved_search.title for j in replay_jobs}:
            filename = (
                sanitize_filename(search_title) + "." + config.output_format.value
            )
            filepath = config.output_dir / filename
            writer = LocalLookupFile(name=str(filepath))
            writer.acquire_lock()
            file_writers[search_title] = writer

    try:
        # CapacityLimiter for max concurrent jobs
        limiter = trio.CapacityLimiter(config.max_concurrents)

        async with trio.open_nursery() as nursery:
            for job in replay_jobs:
                nursery.start_soon(
                    run_single_job_with_limiter,
                    job,
                    instance,
                    config,
                    file_writers,
                    on_update,
                    limiter,
                )
    finally:
        # Close all file writers
        for writer in file_writers.values():
            writer.release_lock()


# =============================================================================
# UI Helpers
# =============================================================================


def sanitize_filename(
    name: Annotated[str, "Filename to sanitize"],
) -> str:
    """
    Sanitize filename by replacing invalid characters with underscores.

    Args:
        name: Filename to sanitize

    Returns:
        Sanitized filename
    """
    return re.sub(r'[<>:"/\\|?*\s]', "_", name).lower()


def format_elapsed_time(
    job: Annotated[ReplayJob, "Replay job"],
) -> str:
    """
    Format elapsed time with spinner for running jobs.

    Args:
        job: Replay job

    Returns:
        Formatted elapsed time string
    """
    if job.start_time is None:
        return "-"

    elapsed = datetime.now() - job.start_time
    total_seconds = int(elapsed.total_seconds())

    if total_seconds < 60:
        return f"{total_seconds}s"
    elif total_seconds < 3600:
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        return f"{minutes}m {seconds}s"
    else:
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        return f"{hours}h {minutes}m"


def build_confirmation_table(
    saved_searches: Annotated[
        list[SplunkInstanceSavedSearch], "Saved searches for confirmation"
    ],
) -> Table:
    """
    Build Rich table for saved search confirmation.

    Args:
        saved_searches: Saved searches to display

    Returns:
        Rich Table
    """
    table = Table(
        title="Saved Searches to Replay",
        box=box.SIMPLE,
        show_header=True,
        header_style="bold",
    )

    table.add_column("#", justify="right", style="dim")
    table.add_column("Title")
    table.add_column("App")
    table.add_column("Owner")
    table.add_column("Cron Schedule")
    table.add_column("Enabled", justify="center")

    for i, ss in enumerate(saved_searches, 1):
        enabled_text = (
            Text("Yes", style="green") if not ss.disabled else Text("No", style="red")
        )
        table.add_row(
            str(i),
            ss.title,
            ss.namespace.app,
            ss.namespace.owner,
            ss.cron_schedule or "-",
            enabled_text,
        )

    return table


def build_summary_footer(
    summary: Annotated[ReplaySummary, "Replay summary"],
) -> str:
    """
    Build summary text for footer.

    Args:
        summary: Replay summary

    Returns:
        Formatted summary string
    """
    trigger_text = "Yes" if summary.trigger_actions else "No"

    return (
        f"Searches: {summary.search_count} | "
        f"Total Jobs: {summary.total_jobs} | "
        f"Time Window: {summary.time_window_human} | "
        f"Time Span: {summary.time_span} | "
        f"Max Concurrent: {summary.max_concurrent} | "
        f"Trigger Actions: {trigger_text}"
    )


def get_replay_table_columns() -> list[dict[str, Any]]:
    """
    Get column definitions for replay progress table.

    Returns:
        List of column definitions
    """
    return [
        {"header": "ID", "justify": "right", "style": "dim"},
        {"header": "Status", "justify": "center"},
        {"header": "Name"},
        {"header": "SID", "style": "dim"},
        {"header": "Earliest"},
        {"header": "Latest"},
        {"header": "Elapsed", "justify": "right"},
        {"header": "Results", "justify": "right"},
        {"header": "Attempts", "justify": "center"},
    ]


def build_replay_row(
    job: Annotated[ReplayJob, "Replay job"],
) -> tuple[RenderableType, ...]:
    """
    Build row for a single replay job.

    Args:
        job: Replay job

    Returns:
        Tuple of renderable cells
    """
    # Status with color
    status = job.display_status
    if status == "COMPLETED" or status == "DONE":
        status_text = Text(status, style="green")
    elif status == "FAILED" or status == "TIMEOUT":
        status_text = Text(status, style="red")
    elif status == "RUNNING":
        status_text = Text(status, style="yellow")
    elif status == "SPLUNK IS RESTARTING":
        status_text = Text(status, style="orange1")
    elif status == "PENDING":
        status_text = Text(status, style="dim")
    else:
        status_text = Text(status, style="blue")

    # Result count
    if job.job and job.job.is_done():
        try:
            result_count = str(job.job["resultCount"])
        except Exception:
            result_count = "-"
    else:
        result_count = "..."

    return (
        str(job.id),
        status_text,
        job.title,
        job.sid or "-",
        job.earliest_time.strftime("%Y-%m-%d %H:%M"),
        job.latest_time.strftime("%Y-%m-%d %H:%M"),
        format_elapsed_time(job),
        result_count,
        f"{job.attempts}/{job.max_attempts}",
    )
