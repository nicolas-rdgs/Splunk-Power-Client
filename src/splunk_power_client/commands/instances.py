import tomllib
from typing import Annotated, Optional, Union

import tomli_w
import typer
from rich.console import Console
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table

from ..models import SharingEnum, SplunkInstance, SplunkNameSpace
from ..settings import Settings
from ..utils import get_default_instance_name, spc_config_file

app = typer.Typer(no_args_is_help=True)

console = Console()


class InstanceManager:
    def __init__(cls, name: str, **kwargs) -> None:
        cls.name = name
        cls.settings = Settings(name=cls.name)
        cls.toml_data: dict[str, Union[str, dict]] = cls._read_config_file()
        cls.default_instance = get_default_instance_name(cls.toml_data)
        cls.options = kwargs

    def _is_default_instance(cls) -> bool:
        """Return True if the current instance is default."""
        return cls.name == cls.default_instance

    def _read_config_file(cls) -> dict:
        if spc_config_file.exists():
            return tomllib.load(spc_config_file.open(mode="rb"))
        else:
            return {}

    def _write_config_file(cls) -> None:
        spc_config_file.parent.mkdir(parents=True, exist_ok=True)
        return tomli_w.dump(cls.toml_data, spc_config_file.open(mode="wb"))

    def set(cls, instance: SplunkInstance, default: bool) -> None:
        """Set instance to config file."""
        if default:
            cls.toml_data["default"] = cls.name

        cls.toml_data[cls.name] = instance.model_dump(
            exclude={"name": True}, exclude_none=True
        )
        cls._write_config_file()

    def remove(cls) -> None:
        """Remove a instance from config file."""
        if cls.settings.exists:
            cls.toml_data.pop(cls.name)
        if cls._is_default_instance():
            cls.toml_data.pop("default", None)
        cls._write_config_file()

    def list(cls) -> None:
        """List all instances."""
        columns = ["host", "port", "login_type", "sharing", "app", "owner"]

        table = Table(title="Instances", show_lines=True)
        table.add_column("Name")
        for column in columns:
            table.add_column(column.capitalize().replace("_", " "))

        for instance, settings in cls.toml_data.items():
            if instance == "default":
                continue

            if "token" in settings and settings["token"]:
                settings["login_type"] = "Token"
            elif all([settings.get(field) for field in ["username", "password"]]):
                settings["login_type"] = "Username/Password"

            row = [
                str(settings.get(column) or settings["namespace"].get(column))
                for column in columns
            ]
            instance = (
                f"* [green]{instance}[/]"
                if cls.default_instance == instance
                else instance
            )
            table.add_row(instance, *row)

        console.print(table)


@app.command(help="Add or update a instance")
def set(
    name: Annotated[str, typer.Argument(help="Instance name")],
    host: Optional[str] = typer.Option(None, show_default=False),
    port: Optional[int] = typer.Option(None, show_default=False),
    username: Optional[str] = typer.Option(None, show_default=False),
    password: Optional[str] = typer.Option(
        None,
        prompt="Password",
        prompt_required=False,
        hide_input=True,
        show_default=False,
    ),
    token: Optional[str] = typer.Option(
        None, prompt="Token", prompt_required=False, hide_input=True, show_default=False
    ),
    sharing: Optional[str] = typer.Option(None, show_default=False),
    owner: Optional[str] = typer.Option(None, show_default=False),
    app: Optional[str] = typer.Option(None, show_default=False),
    ssl_verify: Optional[bool] = typer.Option(
        False, "--ssl-verify", show_default=False, help="Verify SSL certificate"
    ),
    default: Optional[bool] = typer.Option(
        False, "-d", "--default", show_default=False, help="Set as default instance"
    ),
) -> None:
    """
    Add or update a instance.

    If the instance already exists, it will be updated.
    If the instance does not exist, it will be created.

    If no arguments are provided, the user will be asked for the missing information.
    """
    im = InstanceManager(name)

    if im.settings.exists:
        namespace = {
            "sharing": sharing,
            "owner": owner,
            "app": app,
        }
        namespace = {k: v for k, v in namespace.items() if v is not None}

        options = {
            "host": host,
            "port": port,
            "username": username,
            "password": password,
            "token": token,
            "ssl_verify": ssl_verify,
            "namespace": SplunkNameSpace(**namespace) if namespace else None,
        }
        options = {k: v for k, v in options.items() if v is not None}

        instance = im.settings.instance.model_copy(update=options)
        im.set(instance, default)
    else:
        if host and (token or (username and password)):
            instance = SplunkInstance(
                host=host,
                port=port,
                username=username,
                password=password,
                token=token,
                namespace=SplunkNameSpace(
                    sharing=sharing,
                    owner=owner,
                    app=app,
                ),
                ssl_verify=ssl_verify,
            )
        else:
            # Ask questions if no token or password is provided (meant there is no arguments)
            if not im.settings.exists and token is None and password is None:
                instance = SplunkInstance()
                token = False

                for field_name, field_info in SplunkInstance.model_fields.items():
                    question = f"{field_name}".capitalize()
                    if field_name == "host":
                        instance.host = Prompt.ask(
                            question, default=str(field_info.default)
                        )
                    elif field_name == "port":
                        instance.port = IntPrompt.ask(
                            question, default=field_info.default
                        )
                    elif field_name == "token":
                        instance.token = Prompt.ask(question, password=True)
                        if instance.token:
                            token = True
                    elif not token and field_name == "username":
                        instance.username = Prompt.ask(question)
                    elif not token and field_name == "password":
                        instance.password = Prompt.ask(question, password=True)
                    elif field_name == "namespace":
                        ns: SplunkNameSpace = field_info.default
                        instance.namespace.sharing = SharingEnum(
                            Prompt.ask(
                                "Namespace Sharing",
                                default=str(ns.sharing),
                                choices=SharingEnum,
                            )
                        )

                        instance.namespace.owner = Prompt.ask(
                            "Namespace Owner", default=str(ns.owner)
                        )

                        instance.namespace.app = Prompt.ask(
                            "Namespace App", default=str(ns.app)
                        )
                    elif field_name == "ssl_verify":
                        instance.ssl_verify = Confirm.ask(
                            question, default=field_info.default
                        )

                default = Confirm.ask("Default ?")

        im.set(instance, default)


@app.command(help="Remove a instance")
def rm(name: str) -> None:
    InstanceManager(name).remove()


@app.command(help="List all instances")
def ls() -> None:
    InstanceManager(None).list()
