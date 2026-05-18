import typer
from rich.console import Console

from .models import SplunkInstance
from .utils import get_instance_from_settings

console = Console()


def load_instance_callback(ctx: typer.Context, value: str) -> SplunkInstance:
    return get_instance_from_settings(value)


# def load_default_instance_callback(ctx: typer.Context, value: str):
#     # TODO: find a way to get the default instance name and apply it has default value
#     #       for instance option in any command to show it in the help
#     instance_settings = Settings(name=value) if value else Settings()
#     if instance_settings.exists:
#         ctx.obj = instance_settings.instance
#     else:
#         console.print(
#             f":x: Instance '{instance_settings.name}' not found. Please set a instance with 'spc instances set <instance_name>'"
#         )
#         raise typer.BadParameter("Instance not found")
