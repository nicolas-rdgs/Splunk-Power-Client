"""Header-only CSV lookups (header kept, no row), without a Splunk instance."""

import io
import json
from unittest.mock import MagicMock

import pytest
import splunklib.client as client

from splunk_power_client.models import (
    LocalLookupFile,
    SplunkInstance,
    SplunkInstanceLookupCSV,
    csv_headers,
)


def make_instance() -> SplunkInstance:
    instance = SplunkInstance(name="test")
    instance.service = MagicMock(spec=client.Service)
    instance.service.namespace = MagicMock(app="search", owner="nobody")
    return instance


def response(body: bytes) -> MagicMock:
    return MagicMock(body=io.BytesIO(body))


def test_csv_headers_from_rows_then_fieldnames():
    assert csv_headers([{"a": 1, "b": 2}], ["x"]) == ["a", "b"]
    assert csv_headers([], ["a", "b"]) == ["a", "b"]
    with pytest.raises(ValueError):
        csv_headers([], None)


def test_local_header_only_csv_roundtrip(tmp_path):
    source = LocalLookupFile(name=(tmp_path / "src.csv").as_posix())
    source.file.write_text("src.process.name,task.path\n")

    rows = source.read()
    assert rows == []
    assert source.fieldnames == ["src.process.name", "task.path"]

    target = LocalLookupFile(name=(tmp_path / "dst.csv").as_posix())
    target.write(rows, fieldnames=source.fieldnames)
    assert target.file.read_text().splitlines() == ["src.process.name,task.path"]


def test_remote_header_only_csv_read_keeps_fieldnames():
    instance = make_instance()
    instance.service.get.return_value = response(b"url.address,meta.comment\n")
    lookup = SplunkInstanceLookupCSV(
        name="x.csv", instance=instance, lookup_editor_version=40001
    )

    assert lookup.read() == []
    assert lookup.fieldnames == ["url.address", "meta.comment"]


def test_remote_header_only_csv_write_posts_header():
    instance = make_instance()
    lookup = SplunkInstanceLookupCSV(
        name="x.csv", instance=instance, lookup_editor_version=40001
    )

    lookup.write([], fieldnames=["url.address", "meta.comment"])

    body = instance.service.post.call_args.kwargs["body"]
    assert json.loads(body["contents"]) == [["url.address", "meta.comment"]]


def test_remote_write_without_rows_nor_header_fails():
    lookup = SplunkInstanceLookupCSV(
        name="x.csv", instance=make_instance(), lookup_editor_version=40001
    )
    with pytest.raises(ValueError, match="without header"):
        lookup.write([])
