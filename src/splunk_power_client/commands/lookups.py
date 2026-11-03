from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Optional

import pandas as pd
import typer
from rich import box
from rich.console import Console
from rich.table import Table

from ..models import (
    CopyObject,
    CopyStatusEnum,
    FileType,
    KvStoreFieldType,
    LocalLookupFile,
    SplunkInstance,
    SplunkInstanceLookupCSV,
    SplunkInstanceLookupKvStore,
)
from ..table_views import ScrollingTableConfig, ScrollingTableView
from ..utils import get_instance_from_settings, remote_parse_uri

if TYPE_CHECKING:
    from ..kvstore_apply import Plan

app = typer.Typer(no_args_is_help=True)

console = Console()


def get_copy_table_columns(copy_list: list[CopyObject]) -> list[dict]:
    """Build column definitions with dynamic width based on lookup names."""
    # Calculate max width for lookup name columns
    max_src_lookup = max(
        (len(obj.src.name) for obj in copy_list),
        default=len("Src Lookup"),
    )
    max_dst_lookup = max(
        (len(obj.dst.name) for obj in copy_list),
        default=len("Dest Lookup"),
    )

    return [
        {"header": "Src Instance", "justify": "center"},
        {"header": "Src Owner", "justify": "center"},
        {"header": "Src App", "justify": "center"},
        {"header": "Src Lookup", "min_width": max(len("Src Lookup"), max_src_lookup)},
        {"header": "Dest Instance", "justify": "center"},
        {"header": "Dest Owner", "justify": "center"},
        {"header": "Dest App", "justify": "center"},
        {"header": "Dest Lookup", "min_width": max(len("Dest Lookup"), max_dst_lookup)},
        {"header": "Copied?", "justify": "center"},
    ]


def build_copy_row(obj: CopyObject) -> tuple:
    """Build a row for the copy table."""
    if obj.status is None or obj.status == CopyStatusEnum.COPYING:
        status = "[yellow]...[/yellow]"
    elif obj.status == CopyStatusEnum.DONE:
        status = f"[green]{obj.status}[/green]"
    else:
        status = f"[red]{obj.status}[/red]"

    return (
        obj.src.get_instance_name(),
        obj.src.get_namespace().owner,
        obj.src.get_namespace().app,
        obj.src.name,
        obj.dst.get_instance_name(),
        obj.dst.get_namespace().owner,
        obj.dst.get_namespace().app,
        obj.dst.name,
        status,
    )


@app.command(
    no_args_is_help=True,
    help="Copy a lookup from one namespace to another.",
)
def cp(
    source: Annotated[
        str,
        typer.Argument(show_default=False, help="<RemotePath> or <LocalPath>"),
    ],
    target: Annotated[
        str,
        typer.Argument(show_default=False, help="<RemotePath> or <LocalPath>"),
    ],
    source_kv: Annotated[
        Optional[bool],
        typer.Option(help="Source is a KVStore", show_default=False),
    ] = None,
    source_output_format: Annotated[
        Optional[FileType],
        typer.Option(
            help="Change the default format based on file extension. Only applicable to Local Lookup.",
            show_default=False,
        ),
    ] = None,
    target_kv: Annotated[
        Optional[bool],
        typer.Option(help="Target is a KVStore", show_default=False),
    ] = None,
    target_output_format: Annotated[
        Optional[FileType],
        typer.Option(
            help="Change the default format based on file extension. Only applicable to Local Lookup.",
            show_default=False,
        ),
    ] = None,
    csv_field_size_limit: Annotated[
        Optional[int],
        typer.Option(
            help="Override default value if you have lots of columns in your lookup.",
            show_default=False,
            rich_help_panel="CSV Options",
        ),
    ] = None,
    use_source_namespace: Annotated[
        Optional[bool],
        typer.Option(
            help="Use Same Source Namespace for Target.",
            show_default=False,
        ),
    ] = None,
    kv_append: Annotated[
        bool,
        typer.Option(
            help="Append data to the target KVStore collection",
            show_default=False,
            rich_help_panel="KVStore Options",
        ),
    ] = False,
):
    """ """

    try:
        # Instantiate Lookups and attempts to login to the instance
        if source.startswith("s://"):
            source_instance, source_lookup_name = remote_parse_uri(uri=source)
            source_instance.login()
            if source_kv:
                source_lookup = SplunkInstanceLookupKvStore(
                    name=source_lookup_name, instance=source_instance
                )
            else:
                source_lookup = SplunkInstanceLookupCSV(
                    name=source_lookup_name, instance=source_instance
                )
        else:
            source_instance = None
            source_lookup = LocalLookupFile(name=source)
            if source_output_format:
                source_lookup.file_type = source_output_format

        if target.startswith("s://"):
            target_instance, target_lookup_name = remote_parse_uri(uri=target)
            target_instance.login()
            if target_kv:
                target_lookup = SplunkInstanceLookupKvStore(
                    name=target_lookup_name, instance=target_instance
                )
            else:
                target_lookup = SplunkInstanceLookupCSV(
                    name=target_lookup_name, instance=target_instance
                )
        else:
            target_instance = None
            target_lookup = LocalLookupFile(name=target)
            if target_output_format:
                target_lookup.file_type = target_output_format

        # Order:
        # - if directory or wildcard in source:
        #   - target must be a existing directory if local
        #   - target must not have a lookup name if remote
        # - if a single file in source:
        #   - target lookup_name will take the name of the source if not present

        source_lookups: list[
            LocalLookupFile | SplunkInstanceLookupCSV | SplunkInstanceLookupKvStore
        ] = []
        target_lookups: list[
            LocalLookupFile | SplunkInstanceLookupCSV | SplunkInstanceLookupKvStore
        ] = []

        # Source Lookups
        if "*" in source_lookup.name:
            if isinstance(source_lookup, LocalLookupFile):
                for file in Path().glob(source_lookup.name):
                    if file.is_file():
                        source_lookups.append(
                            LocalLookupFile(
                                name=file.as_posix(),
                                csv_field_size_limit=csv_field_size_limit,
                            )
                        )
            elif isinstance(source_lookup, SplunkInstanceLookupCSV):
                for lookup in source_instance.get_lookup_table_files(
                    search=f"name={source_lookup.name}"
                ):
                    lookup.csv_field_size_limit = csv_field_size_limit
                    source_lookups.append(lookup)
            elif isinstance(source_lookup, SplunkInstanceLookupKvStore):
                for lookup in source_instance.get_kvstore_collections(
                    search=f"name={source_lookup.name}"
                ):
                    source_lookups.append(lookup)

        elif (
            isinstance(source_lookup, LocalLookupFile)
            and source_lookup.file.is_dir()
            and source_lookup.file.exists()
        ):
            for file in source_lookup.file.iterdir():
                if file.is_file():
                    source_lookups.append(
                        LocalLookupFile(
                            name=file.as_posix(),
                            csv_field_size_limit=csv_field_size_limit,
                        )
                    )

        else:
            source_lookups.append(source_lookup)

        # Target Lookups
        if (
            len(source_lookups) > 1  # wildcard case
            and isinstance(target_lookup, LocalLookupFile)
            and not (target_lookup.file.is_dir() or target_lookup.file.exists())
        ):
            console.print(
                "[red]Error: For wildcard mode, the target local lookup must be an existing folder[/red]"
            )
            return typer.Exit(code=1)
        elif (
            len(source_lookups) > 1
            and isinstance(
                target_lookup, (SplunkInstanceLookupCSV, SplunkInstanceLookupKvStore)
            )
            and target_lookup.name is not None
        ):
            console.print(
                "[red]Error: For wildcard mode, the target lookup must not have a lookup name[/red]"
            )
            return typer.Exit(code=1)
        elif len(source_lookups) > 1:
            for src_lookup in source_lookups:
                if isinstance(src_lookup, LocalLookupFile):
                    target_name = src_lookup.file.name
                else:
                    target_name = src_lookup.name

                if isinstance(target_lookup, LocalLookupFile):
                    target_lookups.append(
                        LocalLookupFile(
                            name=(Path(target_lookup.name) / target_name).as_posix(),
                            csv_field_size_limit=csv_field_size_limit,
                        )
                    )
                elif isinstance(target_lookup, SplunkInstanceLookupCSV):
                    target_lookups.append(
                        SplunkInstanceLookupCSV(
                            name=target_name,
                            instance=target_instance,
                            csv_field_size_limit=csv_field_size_limit,
                        )
                    )
                    if use_source_namespace:
                        target_lookups[-1].namespace = src_lookup.namespace
                elif isinstance(target_lookup, SplunkInstanceLookupKvStore):
                    target_lookups.append(
                        SplunkInstanceLookupKvStore(
                            name=target_name, instance=target_instance
                        )
                    )
                    if use_source_namespace:
                        target_lookups[-1].namespace = src_lookup.namespace
        else:
            # single file case
            if target_lookup.name is None:
                if isinstance(source_lookup, LocalLookupFile):
                    target_lookup.name = source_lookup.file.name
                else:
                    target_lookup.name = source_lookup.name
                    if use_source_namespace:
                        target_lookup.namespace = source_lookup.namespace
            # single file case but the target is a existing directory
            elif (
                isinstance(target_lookup, LocalLookupFile)
                and target_lookup.file.is_dir()
            ):
                target_lookup.name = (
                    Path(target_lookup.name) / source_lookup.name
                ).as_posix()

            target_lookups = [target_lookup]

        copy_list: list[CopyObject] = [
            CopyObject(src=src_lookup, dst=tgt_lookup)
            for src_lookup, tgt_lookup in zip(source_lookups, target_lookups)
        ]

        config = ScrollingTableConfig(window_size=10, show_progress_bar=True)

        # Collect errors to display after completion
        errors: list[tuple[CopyObject, str]] = []

        with ScrollingTableView(
            items=copy_list,
            columns=get_copy_table_columns(copy_list),
            row_builder=build_copy_row,
            config=config,
        ) as table_view:
            for obj in copy_list:
                try:
                    source_data = obj.src.read()

                    if isinstance(obj.dst, SplunkInstanceLookupKvStore):
                        obj.dst.write(source_data, append=kv_append)
                    else:
                        # header of the source, for header-only CSV lookups
                        obj.dst.write(source_data, fieldnames=obj.src.fieldnames)
                    obj.status = CopyStatusEnum.DONE
                except Exception as error:
                    obj.status = CopyStatusEnum.FAILED
                    errors.append((obj, str(error)))

                table_view.mark_processed()

        # Display error table if there were failures
        if errors:
            console.print()
            error_table = Table(
                box=box.SIMPLE,
                title="[red]Errors[/red]",
            )
            error_table.add_column("Src Lookup")
            error_table.add_column("Dest Lookup")
            error_table.add_column("Error", overflow="fold")

            for obj, error_msg in errors:
                error_table.add_row(
                    f"{obj.src.get_instance_name()}/{obj.src.name}",
                    f"{obj.dst.get_instance_name()}/{obj.dst.name}",
                    f"[red]{error_msg}[/red]",
                )

            console.print(error_table)

    except Exception as e:
        # TODO: add global debug option to enable traceback
        import traceback

        traceback.print_exc()
        console.print(f"[red]Error: {e}[/red]")


@app.command(help="List lookups in a namespace.")
def ls(
    instance: Annotated[
        SplunkInstance,
        typer.Option(
            callback=get_instance_from_settings,
            parser=lambda obj: obj,
            metavar="INSTANCE",
            help="Instance name",
        ),
    ] = "",
    kv: Annotated[
        Optional[bool], typer.Option(help="KvStore mode", show_default=False)
    ] = None,
    search: Annotated[
        str, typer.Option(help="Search query to filter lookups", show_default=False)
    ] = "",
    limit: Annotated[int, typer.Option(help="Number of jobs to show")] = 0,
):
    try:
        table = Table(box=box.SIMPLE)
        table.add_column("Instance", justify="center")
        table.add_column("Owner", justify="center")
        table.add_column("App")
        table.add_column("Lookup")

        if kv:
            for lookup in instance.get_kvstore_collections(search=search):
                table.add_row(
                    lookup.get_instance_name(),
                    lookup.get_namespace().owner,
                    lookup.get_namespace().app,
                    lookup.name,
                )
        else:
            for lookup in instance.get_lookup_table_files(search=search, limit=limit):
                table.add_row(
                    lookup.get_instance_name(),
                    lookup.get_namespace().owner,
                    lookup.get_namespace().app,
                    lookup.name,
                )
        console.print(table)
        console.print(f"Number of lookups: {table.row_count}")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        return typer.Exit(code=1)


@app.command(help="Remove a lookup from a namespace.")
def rm(
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
    kv: Annotated[
        Optional[bool], typer.Option(help="KvStore mode", show_default=False)
    ] = None,
    force: Annotated[
        Optional[bool],
        typer.Option(help="Force deletion without confirmation", show_default=False),
    ] = None,
):
    try:
        # TODO: rendre le table dynamique, le tableau s'affiche à la toute fin

        table = Table(box=box.SIMPLE)
        table.add_column("Instance", justify="center")
        table.add_column("Owner", justify="center")
        table.add_column("App")
        table.add_column("Lookup")
        table.add_column("Deleted?", justify="center")

        if kv:
            lookups_list = list(instance.get_kvstore_collections(search=search))
        else:
            lookups_list = list(instance.get_lookup_table_files(search=search))

        console.print(f"{len(lookups_list)} lookups to delete")
        # console.print("\n".join([lookup.name for lookup in lookups_list]))

        for lookup in lookups_list:
            if force or typer.confirm(
                f"Are you sure you want to delete {lookup.get_instance_name()}"
                + f"/{lookup.get_namespace().owner}"
                + f"/{lookup.get_namespace().app}"
                + f"/{lookup.name}?"
            ):
                lookup.delete()
            table.add_row(
                lookup.get_instance_name(),
                lookup.get_namespace().owner,
                lookup.get_namespace().app,
                lookup.name,
                "[green]OK[/green]",
            )

        console.print(table)

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        return typer.Exit(code=1)


def parse_kv_fields(fields: list[str]) -> dict[str, KvStoreFieldType]:
    """Parse `name[:type]` options into a fields dict, type defaults to string."""
    parsed: dict[str, KvStoreFieldType] = {}
    for field in fields:
        name, _, field_type = field.partition(":")
        if not name:
            raise typer.BadParameter(f"Invalid field '{field}'", param_hint="--field")
        try:
            parsed[name] = KvStoreFieldType(field_type or KvStoreFieldType.STRING)
        except ValueError:
            raise typer.BadParameter(
                f"Invalid type '{field_type}' for field '{name}', "
                + f"expected one of: {', '.join(KvStoreFieldType)}",
                param_hint="--field",
            )
    return parsed


def parse_kv_accelerated_fields(
    accelerated_fields: list[str],
) -> dict[str, dict[str, int]]:
    """Parse `name=field1,field2` options into an accelerated_fields dict."""
    parsed: dict[str, dict[str, int]] = {}
    for accelerated_field in accelerated_fields:
        name, _, fields = accelerated_field.partition("=")
        if not name or not fields:
            raise typer.BadParameter(
                f"Invalid accelerated field '{accelerated_field}', "
                + "expected NAME=FIELD1,FIELD2",
                param_hint="--accelerated-field",
            )
        parsed[name] = {field.strip(): 1 for field in fields.split(",")}
    return parsed


@app.command(
    no_args_is_help=True,
    help="Create a KVStore collection and its lookup definition.",
)
def mkkv(
    target: Annotated[
        str,
        typer.Argument(show_default=False, help="<RemotePath>"),
    ],
    field: Annotated[
        Optional[list[str]],
        typer.Option(
            "--field",
            "-f",
            help="Field as NAME[:TYPE] (string, number, bool, time, array). "
            + "Repeat for each field.",
            show_default=False,
        ),
    ] = None,
    from_file: Annotated[
        Optional[Path],
        typer.Option(
            help="Use the columns of a local lookup file as string fields.",
            show_default=False,
        ),
    ] = None,
    accelerated_field: Annotated[
        Optional[list[str]],
        typer.Option(
            "--accelerated-field",
            help="Acceleration as NAME=FIELD1,FIELD2. Repeat for each acceleration.",
            show_default=False,
        ),
    ] = None,
    enforce_types: Annotated[
        bool,
        typer.Option(help="Reject documents that do not match field types."),
    ] = False,
    replicate: Annotated[
        bool,
        typer.Option(help="Replicate the collection to indexers."),
    ] = False,
    definition: Annotated[
        bool,
        typer.Option(help="Create the lookup definition (transforms.conf)."),
    ] = True,
    definition_name: Annotated[
        Optional[str],
        typer.Option(
            help="Lookup definition name. Defaults to the collection name.",
            show_default=False,
        ),
    ] = None,
    collection_template: Annotated[
        Optional[str],
        typer.Option(
            "--collection",
            "-c",
            help="Collection YAML template: name in <templates-dir>/collections/ "
            + "or path. Created or updated (idempotent).",
            show_default=False,
            rich_help_panel="Templates (as code)",
        ),
    ] = None,
    definition_template: Annotated[
        Optional[str],
        typer.Option(
            "--definition",
            "-d",
            help="Lookup definition YAML template: name in "
            + "<templates-dir>/definitions/ or path. Created or updated (idempotent).",
            show_default=False,
            rich_help_panel="Templates (as code)",
        ),
    ] = None,
    templates_dir: Annotated[
        Path,
        typer.Option(
            envvar="SPC_TEMPLATES_DIR",
            help="Directory holding collections/ and definitions/ templates.",
            rich_help_panel="Templates (as code)",
        ),
    ] = Path("~/.spc/templates"),
    dry_run: Annotated[
        bool,
        typer.Option(
            help="Show the changes against Splunk without applying them.",
            rich_help_panel="Templates (as code)",
        ),
    ] = False,
):
    if collection_template or definition_template:
        legacy = {
            "--field": field,
            "--from-file": from_file,
            "--accelerated-field": accelerated_field,
            "--definition-name": definition_name,
        }
        used = [option for option, value in legacy.items() if value]
        if used:
            raise typer.BadParameter(
                f"{', '.join(used)} cannot be combined with templates",
                param_hint="--collection / --definition",
            )
        return mkkv_from_templates(
            target=target,
            collection_template=collection_template,
            definition_template=definition_template,
            templates_dir=templates_dir.expanduser(),
            dry_run=dry_run,
        )

    try:
        instance, collection_name = remote_parse_uri(uri=target)
        if not collection_name:
            raise typer.BadParameter(
                "The target must contain a collection name", param_hint="TARGET"
            )

        fields: dict[str, KvStoreFieldType] = {}
        if from_file:
            rows = LocalLookupFile(name=from_file.as_posix()).read()
            # xlsx files are read as a DataFrame
            columns = rows.columns if isinstance(rows, pd.DataFrame) else rows[0]
            fields.update({column: KvStoreFieldType.STRING for column in columns})
        fields.update(parse_kv_fields(field or []))
        fields.pop("_key", None)
        if not fields:
            raise typer.BadParameter(
                "At least one field is required", param_hint="--field / --from-file"
            )

        instance.login()
        lookup = instance.create_kvstore_collection(
            name=collection_name,
            fields=fields,
            accelerated_fields=parse_kv_accelerated_fields(accelerated_field or []),
            enforce_types=enforce_types,
            replicate=replicate,
            definition_name=(definition_name or collection_name)
            if definition
            else None,
        )

        table = Table(box=box.SIMPLE, title=f"KVStore '{lookup.name}' created")
        table.add_column("Instance", justify="center")
        table.add_column("Owner", justify="center")
        table.add_column("App")
        table.add_column("Field")
        table.add_column("Type")
        for field_name, field_type in lookup.config.fields.items():
            table.add_row(
                lookup.get_instance_name(),
                lookup.get_namespace().owner,
                lookup.get_namespace().app,
                field_name,
                str(field_type),
            )
        console.print(table)
        if definition:
            console.print(
                f"Lookup definition: [green]{definition_name or collection_name}[/green]"
            )

    except typer.BadParameter:
        raise
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(code=1)


def _uri_app(target: str) -> Optional[str]:
    """App explicitly given in the URI (s://inst/owner/app), None otherwise."""
    from urllib.parse import urlparse

    segments = urlparse(target).path[1:].split("/")
    return segments[1] or None if len(segments) >= 2 else None


def _print_plan(plan: "Plan") -> None:
    from ..kvstore_apply import Action

    state = "update" if plan.exists else "create"
    table = Table(
        box=box.SIMPLE,
        title=f"{plan.kind} '{plan.name}' (app {plan.app}) : {state}",
        title_justify="left",
    )
    table.add_column("Key")
    table.add_column("Current")
    table.add_column("Desired")
    table.add_column("Action")
    colors = {Action.ADD: "green", Action.UPDATE: "yellow", Action.DRIFT: "red"}
    for change in plan.changes:
        table.add_row(
            change.key,
            change.current or "",
            change.desired or "",
            f"[{colors[change.action]}]{change.action}[/]",
        )
    if plan.acl_to_apply:
        table.add_row(
            "sharing", plan.current_sharing or "", plan.sharing, "[yellow]acl[/]"
        )
    if table.row_count:
        console.print(table)
    else:
        console.print(f"{plan.kind} '{plan.name}' (app {plan.app}) : up to date")


def mkkv_from_templates(
    target: str,
    collection_template: Optional[str],
    definition_template: Optional[str],
    templates_dir: Path,
    dry_run: bool,
) -> None:
    from pydantic import ValidationError

    from ..kvstore_apply import apply_plan, plan_collection, plan_definition
    from ..kvstore_templates import (
        CollectionTemplate,
        DefinitionTemplate,
        resolve_template,
    )

    try:
        collection = definition = None
        if collection_template:
            path = resolve_template(collection_template, "collections", templates_dir)
            collection = CollectionTemplate.from_yaml(path)
        if definition_template:
            path = resolve_template(definition_template, "definitions", templates_dir)
            definition = DefinitionTemplate.from_yaml(path)
            if collection is None:
                # same-name collection template, used for fields_list and checks
                path = (
                    templates_dir / "collections" / f"{definition.collection_name}.yaml"
                )
                if path.exists():
                    collection = CollectionTemplate.from_yaml(path)
                    console.print(f"Using collection template {path}")
            elif definition.collection_name != collection.name:
                raise ValueError(
                    f"Definition '{definition.name}' targets collection "
                    + f"'{definition.collection_name}', not '{collection.name}'"
                )
    except FileNotFoundError as e:
        console.print(f"[red]Template not found: {e.filename}[/red]")
        raise typer.Exit(code=1)
    except (ValidationError, ValueError) as e:
        console.print(f"[red]Invalid template: {e}[/red]")
        raise typer.Exit(code=1)

    try:
        instance, name = remote_parse_uri(uri=target)
        expected = {t.name for t in (collection, definition) if t}
        if name and name not in expected:
            raise typer.BadParameter(
                f"'{name}' does not match the template names: {', '.join(expected)}",
                param_hint="TARGET",
            )
        uri_app = _uri_app(target)
        for template in (collection, definition):
            if template and template.app and uri_app and template.app != uri_app:
                raise typer.BadParameter(
                    f"Template '{template.name}' is for app '{template.app}', "
                    + f"not '{uri_app}'",
                    param_hint="TARGET",
                )

        instance.login()
        service = instance.service
        app_name = instance.namespace.app
        plans = []
        if collection_template:
            plans.append(plan_collection(service, collection, app_name))
        if definition:
            plans.append(plan_definition(service, definition, app_name, collection))

        console.print(f"Instance: [bold]{instance.name}[/bold]")
        for plan in plans:
            _print_plan(plan)

        if dry_run:
            console.print("[yellow]Dry run: nothing applied[/yellow]")
            return
        for plan in plans:
            if plan.has_changes:
                apply_plan(service, plan)
                console.print(f"[green]{plan.kind} '{plan.name}' applied[/green]")

    except typer.BadParameter:
        raise
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(code=1)
