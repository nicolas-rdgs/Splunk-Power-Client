from typing import Optional

import typer
from rich import box, console
from rich.prompt import Prompt
from rich.table import Table
from typing_extensions import Annotated

from ..models import FileType, LocalLookupFile, SortDirection, SplunkInstance
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
