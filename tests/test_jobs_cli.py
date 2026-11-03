from datetime import datetime

from typer.testing import CliRunner

from splunk_power_client.commands import jobs as jobs_cmd
from splunk_power_client.job_registry import JobRegistry, SubmittedJob
from splunk_power_client.main import app

runner = CliRunner(env={"COLUMNS": "200"})


def test_batches_lists_registry(tmp_path, monkeypatch):
    registry = JobRegistry(tmp_path / "jobs.json")
    registry.add(
        [
            SubmittedJob(
                label="T1",
                sid="s1",
                batch="pq-limit",
                instance="prod",
                submitted_at=datetime(2026, 11, 3, 13, 0),
            ),
            SubmittedJob(
                label="T2",
                sid="s2",
                batch="pq-limit",
                instance="prod",
                submitted_at=datetime(2026, 11, 3, 13, 1),
            ),
        ]
    )
    monkeypatch.setattr(jobs_cmd, "_registry", lambda: registry)
    result = runner.invoke(app, ["jobs", "batches"])
    assert result.exit_code == 0, result.output
    assert "pq-limit" in result.output and "2" in result.output


def test_tracked_jobs_defaults_to_latest_batch_and_accepts_unknown_sid(tmp_path):
    registry = JobRegistry(tmp_path / "jobs.json")
    registry.add(
        [
            SubmittedJob(
                label="old", sid="s0", batch="b0", submitted_at=datetime(2026, 11, 1)
            ),
            SubmittedJob(
                label="new", sid="s1", batch="b1", submitted_at=datetime(2026, 11, 3)
            ),
        ]
    )
    assert [j.label for j in jobs_cmd._tracked_jobs(registry, None, None)] == ["new"]
    tracked = jobs_cmd._tracked_jobs(registry, None, ["s0", "external"])
    assert [(j.label, j.batch) for j in tracked] == [("old", "b0"), ("external", "-")]
