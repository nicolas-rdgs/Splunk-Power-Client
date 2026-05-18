import re
from typing import Annotated, List, Optional

import typer
from rich import box, console
from rich.table import Table

from splunk_power_client.models import SplunkInstance, SplunkInstanceConfigFile
from splunk_power_client.utils import get_instance_from_settings

""" 

Requires admin_all_objects capability.

spc configs set -c,--config <config_file> -s,--stanza <stanza> key=value key=value
spc configs get -c,--config <config_file> -s,--stanza <stanza> 
spc configs rm -c,--config <config_file> -s,--stanza <stanza> key=value key=value
spc configs ls -c,--config <config_file> # montre juste le namesapce et fichier de conf?

pour delete une clé, faire une copie du stanza, modifier le dict, supprimer le stanza et le refaire 


instance.service.post("/services/properties/dev_settings/db:local", body={"url": "aze"}) # ca ok pour les properties avec les noms réservés comme id, url, name, etc.
ds["db:local"].update(body={"url": "23456789"}) # ca aussi

ajouter dans la doc qu'on ne peut pas supprimer un fichier de conf, il faut le supprimer manuellement sur le serveur
    IllegalOperationException: Cannot delete configuration files from the REST API.
donc vérifier si le fichier existe avant ? en principe il est déjà là
"""

# TODO: en mode debug, afficher l'état des namespace


app = typer.Typer(no_args_is_help=True)

console = console.Console()


def parse_keys_values_into_dict(keys_values: list[str]) -> dict[str, str]:
    keys_values_dict = {}
    for key_value in keys_values:
        key, value = key_value.split("=")

        keys_values_dict[key] = value
    return keys_values_dict


@app.command(name="get", help="Get a config from an instance.", no_args_is_help=True)
def get(
    config: Annotated[str, typer.Option("--config", "-c", help="Config file")],
    stanza: Annotated[
        Optional[str], typer.Option("--stanza", "-s", help="Stanza")
    ] = None,
    include_default: Annotated[
        bool,
        typer.Option(
            help="Include keys inherit from default configurations", show_default=False
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
):
    table = Table(box=box.SIMPLE, title=f"{config}'s ConfigurationFile", min_width=50)
    table.add_column("Stanza", highlight=True)
    table.add_column("Key")
    table.add_column("Value", overflow="fold")

    for config_file in instance.get_configs(name=config):
        for stanza_name, sz in config_file.stanzas.items():
            if stanza is not None and stanza_name != stanza:
                continue
            for key, value in sz.content.items():
                # TODO: move include_default into model
                if include_default and re.match("^[A-Z_]+$", key):
                    table.add_row(stanza_name, key, value)
                elif not include_default and not re.match("^[A-Z_]+$", key):
                    table.add_row(stanza_name, key, value)

    console.print(table)


@app.command(name="set", help="Set a config from an instance.", no_args_is_help=True)
def set(
    config: Annotated[str, typer.Option("--config", "-c", help="Config file")],
    keys_values: Annotated[List[str], typer.Argument(help="Key=Value")],
    stanza: Annotated[
        Optional[str], typer.Option("--stanza", "-s", help="Stanza")
    ] = "default",
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
    stanza_content = parse_keys_values_into_dict(keys_values)

    try:
        config_file: SplunkInstanceConfigFile = next(instance.get_configs(name=config))
        config_file.update(stanza, stanza_content)
        console.print(f"[green][+] Updated[/] {config} config")
    except StopIteration:
        config_file = instance.create_config(name=config)
        config_file.update(stanza, stanza_content)
        console.print(f"[green]Created[/] new config {config}")


@app.command(
    name="rm",
    help="Remove a stanza from a configuration or a key subset from a stanza",
    no_args_is_help=True,
)
def rm(
    config: Annotated[
        str,
        typer.Option("--config", "-c", help="ConfigurationFile name (without .conf)"),
    ],
    stanza: Annotated[
        Optional[str],
        typer.Option(
            "--stanza",
            "-s",
            help="If not specified, it will delete all stanzas from ConfigurationFile.",
        ),
    ] = None,
    keys: Annotated[List[str], typer.Argument(help="Key")] = None,
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
    try:
        config_file: SplunkInstanceConfigFile = next(instance.get_configs(name=config))
        if stanza:
            if stanza.lower() != "default" and stanza not in config_file.stanzas:
                raise typer.BadParameter(
                    f"Stanza '{stanza}' not found in ConfigurationFile '{config}'"
                )

            if keys:
                txt = "these keys: \n" + "\n- ".join(keys)
            else:
                txt = "all keys"

            if force or typer.confirm(
                "Are you sur you want to delete "
                + txt
                + f"of '{stanza}' stanza from ConfigurationFile '{config}'"
            ):
                config_file.delete(stanza, keys)
                console.print(f"delete '{stanza}' or {keys}")
            else:
                console.print("canceled")
        else:
            for stanza_name, stanza in config_file.stanzas.items():
                console.print(f"delete stanza {stanza_name}")

        # config_file.delete(stanza, keys)

        console.print(f"[green][+] Updated[/] {config} config")
    except StopIteration:
        raise typer.BadParameter(f"ConfigurationFile '{config}' doesn't exists")
