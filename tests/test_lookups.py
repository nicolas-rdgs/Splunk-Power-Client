from pathlib import Path

from typer.testing import CliRunner

from splunk_power_client.main import app

runner = CliRunner()
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
    assert "done" in result.output


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
