from pathlib import Path
from typing import Annotated, Optional

import trio
import typer
from rich import console

from ..models import FileType, ReplayConfig, SplunkInstance, SplunkInstanceSavedSearch
from ..replay import (
    build_confirmation_table,
    build_replay_row,
    build_replay_summary,
    build_summary_footer,
    generate_replay_jobs,
    get_replay_table_columns,
    parse_splunk_time,
    parse_time_span_to_seconds,
    run_replay,
)
from ..table_views import ScrollingTableConfig, ScrollingTableView
from ..utils import get_instance_from_settings

app = typer.Typer(
    no_args_is_help=True,
)

console = console.Console()

"""
spc searches ls
    liste les savedsearches d'une instance

    -f, --filter
    -l, --limit

spc searches rm
    supprime les savedsearches d'une instance

    -f, --filter
    --force

spc searches set
    ajouter ou modifier une option d'une ou plusieurs saved searches

    -f, --filter
    arguments:
        key=value


spc searches import/export
    import ou export des savedsearches depuis ou vers le savedsearches.conf
    utile quand une instance n'est pas joignable sur le réseau et qu'on nous partage un savedsearches.conf

    arg: input_file

    --ns-app
    --ns-owner
    

spc searches run
    exécute une query depuis le terminal
    adhoc only?

    --earliest-time <>, --latest-time <>
    --max-concurrents <int>
    --max-retry <int> 
    --timeout <int>
    --time-span <value>
    --output <dir>
    --output-format json, csv, raw, xlsx

    
spc searches replay
    exécute une ou plusieurs saved searches existantes et activées
    les recherches sont lancées en parallèle dans splunk et contrôlées toutes les secondes de leur état

    si time-span n'est pas spécifié, la saved search sera joué qu'une seule fois
    occurrences = nb_searches * ((latest-time - earliest-time) / time-span)

    -f, --filter 
    --earliest-time <>, --latest-time <>
    --time-span <value>
    --trigger-actions <bool>
    --max-concurrents <int>
    --max-retry <int> 
    --timeout <int>
    --output <dir>
    --output-format json, csv, raw, xlsx


spc searches reschedule
    permet de programmer une ou plusieurs savedsearches sans modifier leur cron

    -f, --filter 
    --skip-disabled
    --time <str> ; 1s / 1h / timestamp etc

    
spc searches clone
    copie une liste de savedsearch de la même instance en modifiant le titre avec le prefix ou suffix
    preserve le namespace origin

    -f, --filter
    --prefix <str>, --suffix <str>
    --disabled <bool>
    
    --ns-app
    --ns-owner 


spc searches cp 's://instance1/owner/app/my savedsearch*' 's://instance2/owner/app'
    copie une liste de savedsearch d'une instance a une autre

"""


@app.command(help="Search savedsearches.")
def ls(
    search: Annotated[
        str, typer.Option(help="Search query to filter lookups", show_default=False)
    ],
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
    ss: list[SplunkInstanceSavedSearch] = list(
        instance.get_saved_searches(search=search)
    )
    console.print(ss)
    # console.print(ss.model_dump(exclude=["instance", "service"]))
    for s in ss:
        console.print(s.title)
        console.print(s.model_dump(exclude=["instance", "entity"], exclude_none=True))

    console.print(f"Total: {len(ss)}")


@app.command(name="cp", help="Copy searches from one instance to another.")
def cp(
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
    pass


@app.command(help="Remove savedsearches.")
def rm(
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
    pass


@app.command(help="Set savedsearches options.")
def set(
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
    pass


@app.command(name="import", help="Import search from a savedsearches.conf file.")
def import_from_savedsearches_conf(
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
    pass


@app.command(name="export", help="Export search to a savedsearches.conf file.")
def export_to_savedsearches_conf(
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
    pass


@app.command(name="run", help="Run a search.")
def run(
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
    pass


@app.command(name="replay", help="Replay saved searches over a time range.")
def replay(
    search: Annotated[
        str,
        typer.Option(
            "--search-filters",
            "-s",
            help="Filter saved searches by name",
            show_default=False,
        ),
    ] = "",
    earliest_time: Annotated[
        str,
        typer.Option("--earliest-time", "-e", help="Start time for replay"),
    ] = "-2d@d",
    latest_time: Annotated[
        str,
        typer.Option("--latest-time", "-l", help="End time for replay"),
    ] = "now",
    time_span: Annotated[
        str,
        typer.Option("--time-span", "-t", help="Time window for each job occurrence"),
    ] = "1h",
    max_concurrents: Annotated[
        int,
        typer.Option("--max-concurrents", "-c", help="Maximum parallel jobs"),
    ] = 3,
    max_retry: Annotated[
        int,
        typer.Option("--max-retry", "-r", help="Maximum retry attempts per job"),
    ] = 2,
    timeout: Annotated[
        int,
        typer.Option("--timeout", help="Job timeout in seconds"),
    ] = 300,
    output: Annotated[
        Optional[Path],
        typer.Option("--output", "-o", help="Output directory for results"),
    ] = None,
    output_format: Annotated[
        FileType,
        typer.Option("--output-format", "-f", help="Export format"),
    ] = FileType.JSON,
    trigger_actions: Annotated[
        bool,
        typer.Option(
            "--trigger-actions/--no-trigger-actions",
            help="Enable/disable trigger actions",
        ),
    ] = False,
    instance: Annotated[
        SplunkInstance,
        typer.Option(
            callback=get_instance_from_settings,
            parser=lambda obj: obj,
            metavar="INSTANCE",
            help="Instance name",
        ),
    ] = "",
) -> None:
    """Replay saved searches over a time range with parallel execution."""
    # Fetch saved searches matching filter
    saved_searches: list[SplunkInstanceSavedSearch] = list(
        instance.get_saved_searches(search=search)
    )

    if not saved_searches:
        console.print("[yellow]No saved searches found matching the filter.[/yellow]")
        raise typer.Exit(code=0)

    # Build replay configuration
    config = ReplayConfig(
        earliest_time=earliest_time,
        latest_time=latest_time,
        time_span=time_span,
        max_concurrents=max_concurrents,
        max_retry=max_retry,
        timeout=timeout,
        output_dir=output,
        output_format=output_format,
        trigger_actions=trigger_actions,
    )

    # Build summary
    summary = build_replay_summary(saved_searches, config)

    # Display confirmation table
    confirmation_table = build_confirmation_table(saved_searches)
    console.print(confirmation_table)

    # Display summary footer
    footer = build_summary_footer(summary)
    console.print(f"\n[bold]{footer}[/bold]\n")

    # Ask for confirmation
    if not typer.confirm("Do you want to proceed with replay?"):
        console.print("[yellow]Replay cancelled.[/yellow]")
        raise typer.Exit(code=0)

    # Parse time values and generate jobs
    earliest_dt = parse_splunk_time(config.earliest_time)
    latest_dt = parse_splunk_time(config.latest_time)
    time_span_seconds = parse_time_span_to_seconds(config.time_span)

    replay_jobs = generate_replay_jobs(
        saved_searches=saved_searches,
        earliest=earliest_dt,
        latest=latest_dt,
        time_span_seconds=time_span_seconds,
        max_retry=config.max_retry,
    )

    console.print(f"\n[green]Starting replay with {len(replay_jobs)} jobs...[/green]\n")

    # Create ScrollingTableView for progress display
    table_config = ScrollingTableConfig(
        window_size=15,
        show_progress_bar=True,
        title="Replay Progress",
        subtitle=footer,
    )

    columns = get_replay_table_columns()

    with ScrollingTableView(
        items=replay_jobs,
        columns=columns,
        row_builder=build_replay_row,
        config=table_config,
    ) as table_view:
        # Run async replay with Trio
        def on_update() -> None:
            table_view.refresh()

        trio.run(run_replay, replay_jobs, instance, config, on_update)

    # Final summary
    completed = sum(
        1
        for j in replay_jobs
        if j.job and j.job.is_done() and j.display_status in ("COMPLETED", "DONE")
    )
    failed = sum(1 for j in replay_jobs if j.display_status == "FAILED")
    timed_out = sum(1 for j in replay_jobs if j.is_timeout)

    console.print("\n[bold]Replay completed![/bold]")
    console.print(f"  Completed: [green]{completed}[/green]")
    console.print(f"  Failed: [red]{failed}[/red]")
    console.print(f"  Timed out: [yellow]{timed_out}[/yellow]")

    if output:
        console.print(f"\n  Results exported to: [blue]{output}[/blue]")


@app.command(name="reschedule", help="Reschedule a search.")
def reschedule(
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
    pass


@app.command(name="clone", help="Clone searches.")
def clone(
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
    pass


@app.command()
def parse():
    # allow user to test its search before saving it (scripting or cicd)
    # https://docs.splunk.com/Documentation/Splunk/9.4.2/RESTREF/RESTsearch#search.2Fv2.2Fparser
    ...
