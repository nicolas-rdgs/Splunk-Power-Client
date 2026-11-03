from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich import box, console
from rich.live import Live
from rich.prompt import Prompt
from rich.table import Table
from typing_extensions import Annotated

from ..job_registry import (
    DEFAULT_JOB_TTL,
    JobBatchFile,
    JobRegistry,
    JobRegistryError,
    JobSearch,
    SubmittedJob,
    default_batch_name,
)
from ..job_tracking import (
    JobSnapshot,
    build_jobs_table,
    build_messages_table,
    elapsed_title,
    fetch_job_snapshot,
    wait_for_jobs,
)
from ..models import FileType, LocalLookupFile, SortDirection, SplunkInstance
from ..replay import sanitize_filename
from ..utils import get_instance_from_settings

console = console.Console()

app = typer.Typer(no_args_is_help=True)


# spc job log [--instance INSTANCE] JOB_SID  # print search_info.log and metrics
# - search_info / job.content.message
# spc job export [--instance INSTANCE] JOB_SID LocalPath
# spc job ls [--instance INSTANCE] [search filter]
# spc job rm [--instance INSTANCE] [search filter]   # show running jobs by default

# docs:
# - show how export job results to csv and json
# - show how to list jobs
# - show how to remove jobs by search id and another filters
#   - show how to list jobs sorted by diskUsage
#   - show how to delete the most older jobs (> xx days)
# - show the common fields api


@app.command(help="Export job results to file")
def export(
    job_sid: Annotated[str, typer.Argument(help="Job SID")],
    output: Annotated[str, typer.Argument(help="<LocalPath>")],
    instance: Annotated[
        SplunkInstance,
        typer.Option(
            callback=get_instance_from_settings,
            parser=lambda obj: obj,
            metavar="INSTANCE",
            help="Instance name",
        ),
    ] = "",
    output_format: Annotated[
        FileType, typer.Option(help="Format to export")
    ] = FileType.CSV,
):
    """ """
    job_results = instance.get_job_results(job_sid)
    target = LocalLookupFile(name=output, file_type=output_format)
    target.write(job_results)


@app.command(help="Show search_info.log")
def searchlog(
    job_sid: Annotated[str, typer.Argument(help="Job SID")],
    instance: Annotated[
        SplunkInstance,
        typer.Option(
            callback=get_instance_from_settings,
            parser=lambda obj: obj,
            metavar="INSTANCE",
            help="Instance name",
        ),
    ] = "",
):
    console.print(instance.get_job_searchlog(job_sid))


@app.command(help="List jobs")
def ls(
    search: Annotated[
        str, typer.Option(help="Search API filter")
    ] = "(dispatchState=DONE)",
    sort_key: Annotated[str, typer.Option(help="Sort by")] = "dispatch_time",
    sort_dir: Annotated[
        SortDirection, typer.Option(help="Sort direction")
    ] = SortDirection.DESC,
    limit: Annotated[int, typer.Option(help="Number of jobs to show")] = 0,
    instance: Annotated[
        SplunkInstance,
        typer.Option(
            callback=get_instance_from_settings,
            parser=lambda obj: obj,
            metavar="INSTANCE",
            help="Instance name",
        ),
    ] = "",
):
    # TODO:
    #   - ability to shows specific columns
    #   - fix get_jobs() to intercept HTTPError 404 when SID isn't accessible due to namespace constraint (or permission)
    #   - add namespace options to global (without needs to edit the instance)

    # TODO: -t, --table / -c, --columns
    #       spc jobs ls --search "" -t sid
    #       spc jobs searchlog $(spc jobs ls --search "" -t sid)

    table = Table(box=box.SIMPLE, expand=True)
    table.add_column("App")
    table.add_column("Owner")
    table.add_column("Provenance")
    table.add_column("Launched At")
    table.add_column("Expires At")
    table.add_column("SID", overflow="fold")
    table.add_column("Name", overflow="fold")
    table.add_column("Status")
    table.add_column("Run Duration")
    table.add_column("Result Count")
    table.add_column("Event Count")
    table.add_column("Size On Disk")

    for job in instance.get_jobs(
        search=search, count=limit, sort_key=sort_key, sort_dir=sort_dir
    ):
        table.add_row(
            job.namespace.app,
            job.namespace.owner,
            job.provenance,
            str(job.published),
            str(job.expires_at),
            job.sid,
            job.name,
            job.status,
            job.run_duration,
            f"{job.result_count:,}",
            f"{job.event_count:,}",
            job.size_human,
        )

    console.print(table)


@app.command(help="Remove a list of jobs")
def rm(
    job_sid: Annotated[
        Optional[str], typer.Argument(help="Job SID", show_default=False)
    ] = None,
    search: Annotated[str, typer.Option(help="Search API filter")] = "",
    instance: Annotated[
        SplunkInstance,
        typer.Option(
            callback=get_instance_from_settings,
            parser=lambda obj: obj,
            metavar="INSTANCE",
            help="Instance name",
        ),
    ] = "",
    force: Annotated[
        Optional[bool],
        typer.Option(help="Force deletion without confirmation", show_default=False),
    ] = None,
):
    table = Table(box=box.SIMPLE)
    table.add_column("App")
    table.add_column("Owner")
    table.add_column("Provenance")
    table.add_column("Launched At")
    table.add_column("SID", overflow="fold")
    table.add_column("Name", overflow="fold")
    table.add_column("Status")
    table.add_column("Size On Disk")

    if job_sid:
        instance.service.jobs.delete(job_sid)
    elif search:
        jobs_to_delete = list(instance.get_jobs(count=0, search=search))

        console.print(f"You are about to delete {len(jobs_to_delete)} jobs.")

        while not force or True:
            confirm = Prompt.ask(
                prompt="Are you sure you want to delete these jobs? [y/n/l]",
                choices=["y", "n", "l"],
                case_sensitive=False,
                default="n",
            )

            if confirm.lower().startswith("l"):
                for job in jobs_to_delete:
                    table.add_row(
                        job.namespace.app,
                        job.namespace.owner,
                        job.provenance,
                        str(job.published),
                        job.sid,
                        job.name,
                        job.status,
                        job.size_human,
                    )
                console.print(table)
            elif confirm.lower().startswith("n"):
                typer.echo("Abort")
                raise typer.Exit(1)
            else:
                break

        table.rows.clear()
        table.add_column("Deleted?")

        for job in jobs_to_delete:
            job.entity.delete()
            table.add_row(
                job.namespace.app,
                job.namespace.owner,
                job.provenance,
                str(job.published),
                job.sid,
                job.name,
                job.status,
                job.size_human,
                "[green]OK[/green]",
            )

        console.print(table)

    else:
        typer.echo("No job SID or search filter provided")
        raise typer.Exit(1)


# =============================================================================
# Ad hoc jobs: submit / status / wait / batches
# =============================================================================

InstanceOption = Annotated[
    SplunkInstance,
    typer.Option(
        callback=get_instance_from_settings,
        parser=lambda obj: obj,
        metavar="INSTANCE",
        help="Instance name",
    ),
]


def _registry() -> JobRegistry:
    return JobRegistry()


def _tracked_jobs(
    registry: JobRegistry, batch: Optional[str], sids: Optional[list[str]]
) -> list[SubmittedJob]:
    """Jobs to track: given SIDs, a batch, or the most recent batch by default."""
    try:
        if sids:
            known = {job.sid: job for job in registry.get(batch=batch, sids=sids)}
            # A SID that was not submitted with spc is still tracked, by its SID
            return [
                known.get(sid) or SubmittedJob(label=sid, sid=sid, batch="-")
                for sid in sids
            ]
        batch = batch or registry.latest_batch()
        if not batch:
            raise typer.BadParameter(
                "No job in the registry, submit one with `spc jobs submit`",
                param_hint="--batch",
            )
        jobs = registry.get(batch=batch)
    except JobRegistryError as error:
        raise typer.BadParameter(str(error))
    if not jobs:
        raise typer.BadParameter(f"Batch *{batch}* not found", param_hint="--batch")
    return jobs


def _warn_other_instance(jobs: list[SubmittedJob], instance: SplunkInstance) -> None:
    others = sorted(
        {j.instance for j in jobs if j.instance and j.instance != instance.name}
    )
    if others:
        console.print(
            f"[yellow]Warning: jobs submitted on {', '.join(others)}, "
            f"tracked on {instance.name}[/yellow]"
        )


def _export_results(
    instance: SplunkInstance,
    snapshots: list[JobSnapshot],
    output_dir: Path,
    output_format: FileType,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for snapshot in snapshots:
        if not snapshot.is_success:
            continue
        target = (
            output_dir / f"{sanitize_filename(snapshot.label)}.{output_format.value}"
        )
        LocalLookupFile(name=str(target)).write(instance.get_job_results(snapshot.sid))
        console.print(f"[green]Exported[/green] {snapshot.label} → {target}")


def _wait_and_report(
    instance: SplunkInstance,
    jobs: list[SubmittedJob],
    timeout: int,
    poll_interval: int,
    export_dir: Optional[Path],
    output_format: FileType,
) -> None:
    started_at = datetime.now()
    batch_names = ", ".join(sorted({job.batch for job in jobs}))

    with Live(console=console, refresh_per_second=2, transient=True) as live:

        def on_update(snapshots: list[JobSnapshot]) -> None:
            title = elapsed_title(f"Batch {batch_names}", started_at, timeout)
            live.update(build_jobs_table(snapshots, title=title))

        snapshots = wait_for_jobs(
            jobs,
            fetch=lambda job: fetch_job_snapshot(instance.service, job),
            timeout=timeout,
            poll_interval=poll_interval,
            on_update=on_update,
        )

    console.print(build_jobs_table(snapshots, title=f"Batch {batch_names}"))
    messages = build_messages_table(snapshots)
    if messages:
        console.print(messages)

    if export_dir:
        _export_results(instance, snapshots, export_dir, output_format)

    failed = [s for s in snapshots if not s.is_success]
    if failed:
        console.print(
            f"[red]{len(failed)} job(s) not DONE:[/red] "
            + ", ".join(f"{s.label} ({s.state})" for s in failed)
        )
        raise typer.Exit(1)


@app.command(help="Submit search jobs without waiting (one query or a YAML batch)")
def submit(
    query: Annotated[
        Optional[str], typer.Argument(help="SPL query", show_default=False)
    ] = None,
    file: Annotated[
        Optional[Path],
        typer.Option(
            "--file", "-f", help="YAML batch file", exists=True, dir_okay=False
        ),
    ] = None,
    earliest_time: Annotated[
        str, typer.Option("--earliest-time", "-e", help="Earliest time")
    ] = "-24h",
    latest_time: Annotated[
        str, typer.Option("--latest-time", "-l", help="Latest time")
    ] = "now",
    label: Annotated[str, typer.Option(help="Job label (single query only)")] = "job",
    batch: Annotated[
        Optional[str],
        typer.Option(help="Batch name (default: from the file, or generated)"),
    ] = None,
    job_app: Annotated[
        Optional[str],
        typer.Option("--app", help="App namespace to run the job in"),
    ] = None,
    ttl: Annotated[
        int, typer.Option(help="Job time-to-live in seconds")
    ] = DEFAULT_JOB_TTL,
    wait: Annotated[
        bool, typer.Option("--wait", help="Wait for the jobs once submitted")
    ] = False,
    timeout: Annotated[
        int, typer.Option(help="Wait timeout in seconds (with --wait)")
    ] = 3600,
    poll_interval: Annotated[
        int, typer.Option(help="Seconds between status checks (with --wait)")
    ] = 5,
    instance: InstanceOption = "",
):
    if bool(query) == bool(file):
        raise typer.BadParameter("Give either a QUERY or --file, not both")

    if file:
        try:
            batch_file = JobBatchFile.from_file(file)
        except JobRegistryError as error:
            raise typer.BadParameter(str(error), param_hint="--file")
        searches = batch_file.resolved_searches()
        batch = batch or batch_file.batch
    else:
        searches = [
            JobSearch(
                label=label,
                query=query,
                earliest=earliest_time,
                latest=latest_time,
                app=job_app,
            )
        ]
    batch = batch or default_batch_name()

    submitted: list[SubmittedJob] = []
    errors: list[str] = []
    for search in searches:
        try:
            job = instance.submit_job(
                search.query,
                earliest_time=search.earliest,
                latest_time=search.latest,
                app=search.app or job_app,
                ttl=ttl,
            )
        except Exception as error:
            errors.append(f"{search.label}: {error}")
            continue
        submitted.append(
            SubmittedJob(
                label=search.label,
                sid=job.sid,
                batch=batch,
                instance=instance.name,
                query=search.query,
                earliest=search.earliest,
                latest=search.latest,
                app=search.app or job_app,
            )
        )

    if submitted:
        _registry().add(submitted)

    table = Table(title=f"Batch {batch}", box=box.SIMPLE, header_style="bold")
    table.add_column("Label", style="bold cyan")
    table.add_column("SID", overflow="fold")
    table.add_column("Earliest")
    table.add_column("Latest")
    for job in submitted:
        table.add_row(job.label, job.sid, job.earliest, job.latest)
    console.print(table)

    if errors:
        console.print("[red]Submission failed:[/red]\n  " + "\n  ".join(errors))
    if not submitted:
        raise typer.Exit(1)

    console.print(f"Track them with: spc jobs wait --batch {batch}")
    if wait:
        _wait_and_report(
            instance, submitted, timeout, poll_interval, None, FileType.CSV
        )
    if errors:
        raise typer.Exit(1)


@app.command(help="Show the current status of submitted jobs")
def status(
    job_sids: Annotated[
        Optional[list[str]], typer.Argument(help="Job SIDs", show_default=False)
    ] = None,
    batch: Annotated[
        Optional[str], typer.Option(help="Batch name (default: last batch)")
    ] = None,
    instance: InstanceOption = "",
):
    jobs = _tracked_jobs(_registry(), batch, job_sids)
    _warn_other_instance(jobs, instance)
    snapshots = [fetch_job_snapshot(instance.service, job) for job in jobs]
    console.print(build_jobs_table(snapshots, title=f"Batch {jobs[0].batch}"))
    messages = build_messages_table(snapshots)
    if messages:
        console.print(messages)


@app.command(help="Wait for submitted jobs and show their progress live")
def wait(
    job_sids: Annotated[
        Optional[list[str]], typer.Argument(help="Job SIDs", show_default=False)
    ] = None,
    batch: Annotated[
        Optional[str], typer.Option(help="Batch name (default: last batch)")
    ] = None,
    timeout: Annotated[int, typer.Option(help="Timeout in seconds")] = 3600,
    poll_interval: Annotated[
        int, typer.Option(help="Seconds between status checks")
    ] = 5,
    export_dir: Annotated[
        Optional[Path],
        typer.Option("--export", help="Export results of DONE jobs to this directory"),
    ] = None,
    output_format: Annotated[
        FileType, typer.Option(help="Export format")
    ] = FileType.CSV,
    instance: InstanceOption = "",
):
    jobs = _tracked_jobs(_registry(), batch, job_sids)
    _warn_other_instance(jobs, instance)
    _wait_and_report(instance, jobs, timeout, poll_interval, export_dir, output_format)


@app.command(help="List the batches of submitted jobs")
def batches():
    try:
        summaries = _registry().batches()
    except JobRegistryError as error:
        raise typer.BadParameter(str(error))

    table = Table(box=box.SIMPLE, header_style="bold")
    table.add_column("Batch", style="bold cyan")
    table.add_column("Jobs", justify="right")
    table.add_column("Instance")
    table.add_column("First Submitted")
    table.add_column("Last Submitted")
    for summary in summaries:
        table.add_row(
            summary.name,
            str(summary.jobs),
            ", ".join(summary.instances) or "-",
            f"{summary.first_submitted_at:%Y-%m-%d %H:%M:%S}",
            f"{summary.last_submitted_at:%Y-%m-%d %H:%M:%S}",
        )
    console.print(table)
