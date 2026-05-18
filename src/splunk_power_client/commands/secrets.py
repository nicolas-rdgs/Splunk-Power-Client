from typing import Annotated, Optional

import typer
from rich import box, console
from rich.prompt import Prompt
from rich.table import Table

from ..models import (
    SortDirection,
    SplunkInstance,
)
from ..utils import get_instance_from_settings

app = typer.Typer(no_args_is_help=True)


console = console.Console()

# spc secrets ls
# spc secrets rm
# spc secrets set --realm <realm> --username <username> --password <password>
# spc secrets get --realm <realm> --username <username>


@app.command(help="List secrets")
def ls(
    search: Annotated[str, typer.Option(help="Search API filter")] = "",
    sort_key: Annotated[str, typer.Option(help="Sort by")] = "Updated",
    sort_dir: Annotated[
        SortDirection, typer.Option(help="Sort direction")
    ] = SortDirection.DESC,
    limit: Annotated[int, typer.Option(help="Number of jobs to show")] = -1,
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
    table = Table(box=box.SIMPLE)
    table.add_column("App", highlight=True)
    table.add_column("Owner")
    table.add_column("Realm", overflow="fold")
    table.add_column("Username", overflow="fold")
    table.add_column("Password", overflow="fold")
    table.add_column("Updated At")

    for secret in instance.get_secrets(
        search=search, sort_key=sort_key, sort_dir=sort_dir, limit=limit
    ):
        table.add_row(
            secret.namespace.app,
            secret.namespace.owner,
            secret.realm,
            secret.username,
            secret.password,
            str(secret.updated),
        )

    console.print(table)


@app.command(help="Create or Update a secret")
def set(
    realm: Annotated[str, typer.Option(help="Realm")],
    username: Annotated[str, typer.Option(help="Username")],
    password: Annotated[Optional[str], typer.Option(help="Password")] = None,
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
    try:
        if password is None:
            password = Prompt.ask("Password", password=True)

        secret = next(
            instance.get_secrets(search=f"realm={realm} AND username={username}")
        )
        secret.password = password
        secret.update()
        console.print(
            f"[green][+] Updated[/] secret for realm={realm}, username={username}"
        )
    except StopIteration:
        secret = instance.create_secret(
            realm=realm, username=username, password=password
        )
        console.print(
            f"[green]Created[/] new secret for realm={realm}, username={username}"
        )


@app.command(help="Get a specific secret")
def get(
    realm: Annotated[str, typer.Option(help="Realm")] = "",
    username: Annotated[str, typer.Option(help="Username")] = "",
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
    try:
        search = []
        if realm:
            search.append(f"realm={realm}")
        if username:
            search.append(f"username={username}")
        search = " AND ".join(search)
        secret = next(instance.get_secrets(search=search))
        console.print("[green]Found[/] secret:")
        console.print(f"  Realm: {secret.realm}")
        console.print(f"  Username: {secret.username}")
        console.print(f"  Password: {secret.password}")
        console.print(f"  App: {secret.namespace.app}")
        console.print(f"  Owner: {secret.namespace.owner}")
        console.print(f"  Updated: {secret.updated}")
    except StopIteration:
        console.print(
            f"[red][!] Secret not found[/] for realm={realm}, username={username}"
        )


@app.command(help="Remove a list of secrets")
def rm(
    search: Annotated[str, typer.Option(help="Search API filter")] = "",
    force: Annotated[
        Optional[bool],
        typer.Option(help="Force deletion without confirmation", show_default=False),
    ] = None,
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
    deleted_count = 0
    for secret in instance.get_secrets(search=search):
        try:
            if force or typer.confirm(
                f"Are you sure you want to delete secret for realm={secret.realm}, username={secret.username}?"
            ):
                secret.delete()

                console.print(
                    f"[red]Deleted[/] secret for realm={secret.realm}, username={secret.username}"
                )
                deleted_count += 1
        except Exception as e:
            import traceback

            print(traceback.print_exc())

            console.print(
                f"[red]Failed[/] to delete secret for realm={secret.realm}, username={secret.username}: {e}"
            )

    if deleted_count == 0:
        console.print("[yellow]No secrets found matching the search criteria[/]")
    else:
        console.print(f"[green]Successfully deleted {deleted_count} secret(s)[/]")
