from pathlib import Path
from typing import Optional, Union

import typer

from .exceptions import InstanceNotFound
from .models import SPCCommonOptions, SplunkInstance


class TyperContext(typer.Context):
    obj: SPCCommonOptions


home = Path.home()
spc_config_file = (home / ".spc/config.toml").resolve()
spc_dotenv_file = (home / ".spc.env").resolve()

splunk_funny_quotes = list(
    map(
        lambda x: x.strip().replace("Splunk> ", ""),
        (Path(__file__).resolve().parent / "splunk_funny_quotes.txt")
        .open()
        .readlines(),
    )
)


def get_default_instance_name(toml_data: dict) -> str | None:
    """Return the default instance name set in the config file"""
    if "default" in toml_data:
        return toml_data["default"]
    return None


def get_instance_from_settings(
    ctx: TyperContext, instance_name: Optional[str] = None
) -> SplunkInstance:
    """Return an instance from settings.

    If instance_name is not provided, return the default instance.

    ### Arguments
    - *instance_name: Optional[str]
      - Instance name
    """
    if ctx.resilient_parsing:
        return

    from .settings import Settings

    if instance_name:
        instance_settings = Settings(name=instance_name)
        if instance_settings.exists:
            instance_settings.instance.login()
        else:
            raise typer.BadParameter(f"Instance *{instance_name}* not found")
    else:
        instance_settings = Settings()
        if instance_settings.exists:
            instance_settings.instance.login()
        else:
            raise typer.BadParameter("No default instance found")

    if ctx.obj.namespace_app:
        instance_settings.instance.namespace.app = ctx.obj.namespace_app
    if ctx.obj.namespace_owner:
        instance_settings.instance.namespace.owner = ctx.obj.namespace_owner

    return instance_settings.instance


def remote_parse_uri(uri: str) -> tuple[SplunkInstance, str | None]:
    """Parse a remote URI and return the instance and the resource name.

    ### Arguments
    - *uri: str
      - The URI to parse
    """
    from urllib.parse import urlparse

    from .settings import Settings

    parsed_uri = urlparse(uri)
    if parsed_uri.hostname:
        # TODO: implement instance from credentials in URI
        instance_settings = Settings(name=parsed_uri.hostname)
        if instance_settings.exists:
            instance = instance_settings.instance
        else:
            raise InstanceNotFound(parsed_uri.hostname)
    else:
        instance_settings = Settings()
        instance = instance_settings.instance

    # if no path is provided, use instance default namespace
    if not parsed_uri.path:
        return instance, None

    path_segments = parsed_uri.path[1:].split("/")

    if len(path_segments) == 1:
        return instance, path_segments[0]

    elif len(path_segments) == 2:
        if path_segments[0]:
            instance.namespace.owner = path_segments[0]
        if path_segments[1]:
            instance.namespace.app = path_segments[1]
        return instance, None

    elif len(path_segments) == 3:
        if path_segments[0]:
            instance.namespace.owner = path_segments[0]
        if path_segments[1]:
            instance.namespace.app = path_segments[1]
        return instance, path_segments[2]
    else:
        raise ValueError(f"Invalid URI: {uri}")


def convert_flatten_dict_to_nested(
    source_dict: dict[str, Union[str, None]], separator: str = "."
) -> dict[str, Union[dict, str, None]]:
    nested_dict = {}

    for key, value in source_dict.items():
        current_dict = nested_dict
        *paths, final_key = key.split(separator)

        for path in paths:
            if path not in current_dict:
                current_dict[path] = {}
            current_dict = current_dict[path]

        current_dict[final_key] = value

    return nested_dict


def relative_time_to_seconds(time: str) -> int:
    unit_in_seconds = {
        "s": 1,
        "m": 60,
        "h": 60 * 60,
        "d": 60 * 60 * 24,
        "w": 60 * 60 * 24 * 7,
        "mon": 60 * 60 * 24 * 30,
        "y": 60 * 60 * 24 * 365,
    }
    number = int(time[:-1])
    unit = time[-1].lower()

    return unit_in_seconds[unit] * number
