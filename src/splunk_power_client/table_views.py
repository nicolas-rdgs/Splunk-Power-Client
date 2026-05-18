"""Reusable table views for Rich Live context with scrolling support."""

from dataclasses import dataclass, field
from typing import Any, Callable, Generic, Optional, TypeVar

from rich import box
from rich.console import Group, RenderableType
from rich.live import Live
from rich.progress import BarColumn, Progress, TextColumn
from rich.table import Table

T = TypeVar("T")


@dataclass
class ScrollingTableConfig:
    """Configuration for ScrollingTableView."""

    window_size: int = 10
    show_progress_bar: bool = True
    box_style: box.Box = field(default_factory=lambda: box.SIMPLE)
    refresh_per_second: int = 4
    title: Optional[str] = None
    subtitle: Optional[str] = None


class ScrollingTableView(Generic[T]):
    """
    A reusable scrolling table component for Rich Live contexts.

    Shows a rolling window of the last N rows during operation,
    with progress tracking in the footer. Displays full results
    after completion.

    Usage:
        def row_builder(item: MyItem) -> tuple[RenderableType, ...]:
            return (item.name, item.status)

        columns = [
            {"header": "Name"},
            {"header": "Status", "justify": "center"},
        ]

        with ScrollingTableView(
            items=my_list,
            columns=columns,
            row_builder=row_builder,
            config=ScrollingTableConfig(window_size=15)
        ) as table_view:
            for item in my_list:
                # Process item...
                item.status = "done"
                table_view.mark_processed()
    """

    def __init__(
        self,
        items: list[T],
        columns: list[dict[str, Any] | str],
        row_builder: Callable[[T], tuple[RenderableType, ...]],
        config: Optional[ScrollingTableConfig] = None,
    ):
        self.items = items
        self.columns = columns
        self.row_builder = row_builder
        self.config = config or ScrollingTableConfig()

        self._processed_count: int = 0
        self._live: Optional[Live] = None

    def _get_visible_items(self) -> list[T]:
        """Get the items currently visible in the rolling window."""
        # Show window centered around processed items, including current item being processed
        # Start from max(0, processed - window + 1) to show recently processed items
        # End at min(len(items), start + window_size)
        if self._processed_count == 0:
            start_idx = 0
        else:
            start_idx = max(0, self._processed_count - self.config.window_size + 1)
        end_idx = min(len(self.items), start_idx + self.config.window_size)
        return self.items[start_idx:end_idx]

    def _build_table(self, show_all: bool = False) -> Table:
        """Build the table with either rolling window or all rows."""
        table = Table(
            box=self.config.box_style,
            title=self.config.title,
            caption=self.config.subtitle,
        )

        # Add columns from definitions
        for col_def in self.columns:
            if isinstance(col_def, str):
                table.add_column(col_def)
            else:
                header = col_def.pop("header", "")
                table.add_column(header, **col_def)
                col_def["header"] = header  # Restore for next build

        # Determine which items to show
        if show_all:
            items_to_show = self.items
        else:
            items_to_show = self._get_visible_items()

        # Build rows
        for item in items_to_show:
            row_cells = self.row_builder(item)
            table.add_row(*row_cells)

        return table

    def _build_footer(self) -> RenderableType:
        """Build the footer with progress information."""
        total = len(self.items)

        if self.config.show_progress_bar:
            progress = Progress(
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TextColumn("({task.completed}/{task.total})"),
            )
            progress.add_task(
                "Processing", total=total, completed=self._processed_count
            )
            return progress
        else:
            return f"Processed: {self._processed_count}/{total}"

    def _build_renderable(self, show_all: bool = False) -> RenderableType:
        """Build the complete renderable (table + footer)."""
        table = self._build_table(show_all=show_all)

        if show_all:
            # Final view: just the table, no footer
            return table
        else:
            # During processing: table + footer
            footer = self._build_footer()
            return Group(table, footer)

    def mark_processed(self) -> None:
        """Mark an item as processed and update the display."""
        self._processed_count += 1

        if self._live:
            self._live.update(self._build_renderable())

    def refresh(self) -> None:
        """Manually refresh the display without marking progress."""
        if self._live:
            self._live.update(self._build_renderable())

    def set_subtitle(self, subtitle: str) -> None:
        """Update the subtitle dynamically."""
        self.config.subtitle = subtitle

    def __enter__(self) -> "ScrollingTableView[T]":
        """Start the Live context."""
        self._live = Live(
            self._build_renderable(),
            refresh_per_second=self.config.refresh_per_second,
        )
        self._live.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit Live context and show full table."""
        if self._live:
            # Show final complete table
            self._live.update(self._build_renderable(show_all=True))
            self._live.__exit__(exc_type, exc_val, exc_tb)
