from pathlib import Path

import pytest
from typer.testing import CliRunner

from splunk_power_client.main import app

pytestmark = pytest.mark.integration

runner = CliRunner(env={"COLUMNS": "200"})
tests_dir = Path(__file__).resolve().parent
tests_data = tests_dir / "data"


def test_copy_csv_from_local_csv_to_splunk():
    result = runner.invoke(
        app,
        [
            "lookups",
            "cp",
            (tests_data / "test_dummy_alerts.csv").as_posix(),
            "s://local",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Error" not in result.output, result.output


def test_list_dummy_alerts_lookup_csv_is_present():
    result = runner.invoke(
        app,
        [
            "lookups",
            "ls",
            "--instance",
            "local",
            "--search",
            "eai:acl.app=search name=test_dummy_alerts.csv",
        ],
    )
    assert "test_dummy_alerts.csv" in result.output


def test_remove_dummy_alerts_lookup_csv():
    result = runner.invoke(
        app,
        [
            "lookups",
            "rm",
            "--instance",
            "local",
            "--search",
            "eai:acl.app=search name=test_dummy_alerts.csv",
            "--force",
        ],
    )
    assert "ok" in result.output


def test_create_kvstore_collection():
    result = runner.invoke(
        app,
        [
            "lookups",
            "mkkv",
            "s://local//search/test_spc_kvstore",
            "--from-file",
            (tests_data / "test_dummy_alerts.csv").as_posix(),
            "--field",
            "count:number",
            "--accelerated-field",
            "by_count=count",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Error" not in result.output, result.output


def test_create_existing_kvstore_collection_fails():
    result = runner.invoke(
        app,
        ["lookups", "mkkv", "s://local//search/test_spc_kvstore", "-f", "user"],
    )
    assert result.exit_code == 1, result.output
    assert "already exists" in result.output


def test_list_kvstore_collection_is_present():
    result = runner.invoke(
        app,
        [
            "lookups",
            "ls",
            "--instance",
            "local",
            "--kv",
            "--search",
            "name=test_spc_kvstore",
        ],
    )
    assert "test_spc_kvstore" in result.output


def test_kvstore_lookup_definition_is_present():
    from splunk_power_client.settings import Settings

    instance = Settings(name="local").instance
    instance.login()
    definition = instance.service.confs["transforms"]["test_spc_kvstore"]
    assert definition.content["external_type"] == "kvstore"
    assert definition.content["collection"] == "test_spc_kvstore"

    # cleanup: `lookups rm --kv` only deletes data, not the collection
    definition.delete()
    instance.service.kvstore.delete("test_spc_kvstore")
