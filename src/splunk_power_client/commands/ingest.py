from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.text import Text

from splunk_power_client.models import SplunkInstance, FileReader
from splunk_power_client.table_views import ScrollingTableView, ScrollingTableConfig
from splunk_power_client.utils import get_instance_from_settings

app = typer.Typer(no_args_is_help=True)

# if "edit_tcp" or "edit_tcp_stream" (for stream) in instance.info.current_context.capabilities
#   needed for /services/receivers/simple


class IngestStatus(str, Enum):
    PENDING = "pending"
    INGESTING = "ingesting"
    DONE = "done"
    FAILED = "failed"


@dataclass
class IngestFile:
    """Represents a file to be ingested."""

    path: Path
    status: IngestStatus = IngestStatus.PENDING
    event_count: int = 0
    total_lines: int = 0
    file_size: int = 0
    error: Optional[str] = None


def resolve_files(path_pattern: str) -> list[IngestFile]:
    """Resolve path pattern to list of files.

    Supports:
    - Single file: /path/to/file.csv
    - Directory: /path/to/dir/ (recursive scan for supported files)
    - Glob pattern: /path/to/*.csv, /path/to/**/*.log
    """
    path = Path(path_pattern)
    supported_extensions = {".csv", ".json", ".log", ".txt", ".raw"}

    if path.is_file():
        return [IngestFile(path=path, file_size=path.stat().st_size)]

    if path.is_dir():
        # Scan directory recursively for supported file types
        files = []
        for ext in supported_extensions:
            files.extend(
                IngestFile(path=f, file_size=f.stat().st_size)
                for f in path.rglob(f"*{ext}")
            )
        return sorted(files, key=lambda x: x.path)

    # Glob pattern
    if "**" in str(path):
        # Handle recursive glob - need to reconstruct full pattern
        parts = str(path).split("**")
        if len(parts) == 2:
            base = Path(parts[0].rstrip("/")) if parts[0] else Path(".")
            suffix_pattern = parts[1].lstrip("/")
            files = [
                IngestFile(path=f, file_size=f.stat().st_size)
                for f in base.rglob(suffix_pattern)
                if f.is_file()
            ]
        else:
            files = []
    else:
        parent = path.parent if path.parent.exists() else Path(".")
        pattern = path.name
        files = [
            IngestFile(path=f, file_size=f.stat().st_size)
            for f in parent.glob(pattern)
            if f.is_file()
        ]

    return sorted(files, key=lambda x: x.path)


def format_size(size_bytes: int) -> str:
    """Format bytes as human-readable size."""
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f}{unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f}TB"


def get_ingest_columns() -> list[dict]:
    """Get column definitions for ingest progress table."""
    return [
        {"header": "File", "min_width": 40},
        {"header": "Size", "justify": "right", "min_width": 8},
        {"header": "Status", "justify": "center", "min_width": 10},
        {"header": "Progress", "justify": "right", "min_width": 15},
    ]


def build_ingest_row(item: IngestFile) -> tuple:
    """Build a row for the ingest progress table."""
    if item.status == IngestStatus.PENDING:
        status = Text("pending", style="dim")
    elif item.status == IngestStatus.INGESTING:
        status = Text("ingesting", style="yellow")
    elif item.status == IngestStatus.DONE:
        status = Text("done", style="green")
    else:
        status = Text("failed", style="red")

    # Show progress as "sent/total"
    if item.total_lines > 0:
        progress = f"{item.event_count}/{item.total_lines}"
    elif item.event_count > 0:
        progress = str(item.event_count)
    else:
        progress = "-"

    return (
        str(item.path.name),
        format_size(item.file_size),
        status,
        progress,
    )


@app.command(help="Send events to Splunk via streaming connection")
def send_events(
    path_pattern: Annotated[
        str,
        typer.Argument(
            help="File, directory, or glob pattern (e.g., *.csv, /data/**/*.log)"
        ),
    ],
    index: Annotated[str, typer.Option("--index", "-i", help="Target index")],
    sourcetype: Annotated[str, typer.Option("--sourcetype", "-s", help="Sourcetype")],
    source: Annotated[
        Optional[str],
        typer.Option("--source", "-S", help="Source value (defaults to filename)"),
    ] = None,
    batch_size: Annotated[
        int, typer.Option("--batch-size", "-b", help="Events per batch")
    ] = 1000,
    host: Annotated[
        Optional[str], typer.Option("--host", "-H", help="Host value")
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
    # Resolve files from pattern
    files = resolve_files(path_pattern)

    if not files:
        typer.echo(f"No files found matching: {path_pattern}", err=True)
        raise typer.Exit(1)

    total_size = sum(f.file_size for f in files)
    typer.echo(
        f"Found {len(files)} file(s) to ingest ({format_size(total_size)} total)"
    )

    config = ScrollingTableConfig(
        window_size=15,
        show_progress_bar=True,
        title="Ingest Progress",
    )

    total_events = 0
    errors: list[tuple[IngestFile, str]] = []

    with ScrollingTableView(
        items=files,
        columns=get_ingest_columns(),
        row_builder=build_ingest_row,
        config=config,
    ) as table_view:
        for file_item in files:
            file_item.status = IngestStatus.INGESTING
            table_view.refresh()

            try:
                # Use generator-based FileReader for memory efficiency
                reader = FileReader(file_item.path)
                file_source = source if source else file_item.path.name

                # Count lines first (fast, memory-efficient)
                file_item.total_lines = reader.count_lines()
                table_view.refresh()

                # Stream events in batches using generator
                with instance.stream_events(
                    index=index,
                    sourcetype=sourcetype,
                    source=file_source,
                    host=host,
                ) as stream:
                    for batch in reader.iter_batches(batch_size):
                        stream.send_batch(batch)
                        file_item.event_count += len(batch)
                        table_view.refresh()

                file_item.status = IngestStatus.DONE
                total_events += file_item.event_count

            except Exception as e:
                file_item.status = IngestStatus.FAILED
                file_item.error = str(e)
                errors.append((file_item, str(e)))

            table_view.mark_processed()

    # Summary
    typer.echo(
        f"\nIngested {total_events} events from {len(files) - len(errors)} file(s) to index={index}"
    )

    if errors:
        typer.echo(f"\n{len(errors)} file(s) failed:", err=True)
        for file_item, error in errors:
            typer.echo(f"  - {file_item.path}: {error}", err=True)
