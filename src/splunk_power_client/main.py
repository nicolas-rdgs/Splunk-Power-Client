import random
from typing import Annotated, Optional

import typer
import typer.completion
from rich import box
from rich.console import Console
from rich.table import Table
from typer._completion_shared import Shells

from . import __version__
from .commands.configs import app as app_configs
from .commands.control import app as app_control
from .commands.ingest import app as app_ingest
from .commands.instances import app as app_instances
from .commands.jobs import app as app_jobs
from .commands.lookups import app as app_lookups
from .commands.searches import app as app_searches
from .commands.secrets import app as app_secrets
from .commands.users import app as app_users
from .models import SPCCommonOptions, SplunkInstance
from .utils import get_instance_from_settings, splunk_funny_quotes

app = typer.Typer(
    add_completion=False,
    pretty_exceptions_enable=False,
    no_args_is_help=True,
)
app_completion = typer.Typer(
    no_args_is_help=True, help="Generate and install completion scripts."
)

console = Console()


@app_completion.command(
    help="Show completion for the specified shell, to copy or customize it.",
)
def show(ctx: typer.Context, shell: Shells) -> None:
    typer.completion.show_callback(ctx, None, shell)


@app_completion.command(help="Install completion for the specified shell.")
def install(ctx: typer.Context, shell: Shells) -> None:
    typer.completion.install_callback(ctx, None, shell)


app.add_typer(app_completion, name="completion")
app.add_typer(app_instances, name="instances", help="Manage Splunk Instances")
app.add_typer(
    app_lookups,
    name="lookups",
    help="Get, Push or Delete lookups",
)
app.add_typer(app_jobs, name="jobs", help="Allows you to perform actions on jobs")
app.add_typer(
    app_ingest, name="ingest", help="Allows you to ingest data into Splunk quickly"
)
app.add_typer(
    app_searches,
    name="searches",
    help="Reschedule, replay or execute saved searches in oneshot",
)
app.add_typer(
    app_configs, name="configs", help="Allows you to change Splunk configs quickly"
)
app.add_typer(app_users, name="users", help="Create, update or delete users")
app.add_typer(app_secrets, name="secrets", help="Manage Splunk secrets")
app.add_typer(app_control, name="controls", help="Splunk Server controls")


@app.command(help="Get instance informations")
def info(
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
    table = Table(
        title=f"{instance.name.capitalize()}'s Instance Informations",
        box=box.SIMPLE,
    )
    table.add_column("Info")
    table.add_column("Value")
    for key, value in instance.info.model_dump(
        exclude={
            "service": True,
            "search_head_cluster_members": True,
            "current_context": {
                "tz": True,
                "capabilities": True,
            },
        }
    ).items():
        if (
            key.startswith("is_search_head_cluster_")
            and not instance.info.is_search_head_cluster
        ):
            continue
        if key == "health_info":
            if value == "green":
                value = ":green_heart:"
            elif value == "yellow":
                value = ":yellow_heart:"
            elif value == "red":
                value = ":broken_heart:"
            else:
                value = ":person_shrugging:"
        elif key == "current_context":
            value = (
                f"User: {value.get('username')} Roles: {', '.join(value.get('roles'))}"
            )

        if isinstance(value, list):
            value = ", ".join(value)
        elif value is False:
            value = ":x:"
        elif value is True:
            value = ":white_check_mark:"
        elif value is None:
            value = ":x:"
        elif value == "ready":
            value = "[green]ready[/]"
        elif value == "failed":
            value = "[red]failed[/]"

        key = "[bold]" + " ".join(list(map(str.capitalize, key.split("_")))) + "[/bold]"
        table.add_row(key, str(value))

    if instance.info.is_search_head_cluster:
        sh_cluster_table = Table(box=box.SIMPLE)
        sh_cluster_table.add_column("Name")
        sh_cluster_table.add_column("Status")
        sh_cluster_table.add_column("Is Captain?")
        sh_cluster_table.add_column("Need restart?")
        sh_cluster_table.add_column("Last HeartBeat")

        for member in instance.info.search_head_cluster_members:
            sh_cluster_table.add_row(
                member.label,
                member.status,
                ":white_check_mark:" if member.is_captain else ":x:",
                ":white_check_mark:" if member.advertise_restart_required else ":x:",
                str(member.last_heartbeat),
            )

        table.add_row("[bold]SHC Members[/bold]", sh_cluster_table)

    table.add_row(
        "[bold]Instance Namespace[/bold]",
        f"[green]Owner[/green]={instance.namespace.owner} / "
        + f"[green]App[/green]={instance.namespace.app} / "
        + f"[green]Sharing[/green]={instance.namespace.sharing}",
    )
    console.print(table)


@app.command(help="IPython shell")
def shell(
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
    import IPython

    IPython.start_ipython(
        argv=["--ext", "autoreload", "--InteractiveShellApp.exec_lines=%autoreload 2"],
        user_ns={
            "instance": instance,
            "json": __import__("json"),
            "print": __import__("rich").print,
        },
    )


def version_callback(value: bool):
    if value:
        print(f"SPC Version: {__version__}")
        raise typer.Exit()


@app.callback(help=f"Splunk Power Client (SPC)> {random.choice(splunk_funny_quotes)}")
def main(
    ctx: typer.Context,
    namespace_app: Annotated[
        Optional[str],
        typer.Option(
            "--namespace-app",
            help="Namespace app",
            rich_help_panel="Global Options",
        ),
    ] = None,
    namespace_owner: Annotated[
        Optional[str],
        typer.Option(
            "--namespace-owner",
            help="Namespace owner",
            rich_help_panel="Global Options",
        ),
    ] = None,
    version: Annotated[
        Optional[bool], typer.Option("--version", callback=version_callback)
    ] = None,
):
    # TODO:
    # - [x] add namespace fields as global options
    # - [ ] add verbose/debug option to change logger level
    ctx.obj = SPCCommonOptions(
        namespace_app=namespace_app,
        namespace_owner=namespace_owner,
    )


# def main():
#    typer.completion.completion_init()
#    sys.exit(app())
