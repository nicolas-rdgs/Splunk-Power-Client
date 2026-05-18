from typing import Annotated

import typer
from rich import box, console
from rich.live import Live
from rich.table import Table

from ..models import SplunkInstance
from ..utils import get_instance_from_settings

app = typer.Typer(
    no_args_is_help=True,
)

console = console.Console()


@app.command(help="Refresh entities")
def debug_refresh(
    entity: Annotated[
        str, typer.Option(help="Specific entity to refresh, comma separated.")
    ] = "",
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
    console.print(f"[bold]Instance:[/bold] {instance.name}")

    table = Table(box=box.SIMPLE)
    table.add_column("Entity")
    table.add_column("Refreshing")

    if entity:
        entity = entity.split(",")
    else:
        entity = []

    endpoint_to_refresh = instance.get_refreshable_entities(entity)
    with Live(table, refresh_per_second=4):
        for endpoint in endpoint_to_refresh:
            short_entity = "/".join(endpoint.split("/")[4:7])
            try:
                instance.service.post(endpoint, output_mode="json")
                table.add_row(f"Refreshing {short_entity}", "[green]OK[/]")
            except Exception as e:
                console.print(f"[red]Error refreshing {short_entity}: {e}[/red]")


@app.command(help="Restart Instance")
def restart(
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
    # show processing table
    # with timeout et status
    # pass to 100% when the splunk has restarted
    # maybe need to use rich.Progress with manual update
    timeout = 60 * 60 * 5

    instance.service.restart(timeout=timeout)
