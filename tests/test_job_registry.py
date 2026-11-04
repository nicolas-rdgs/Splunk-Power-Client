from datetime import datetime, timedelta

import pytest

from splunk_power_client.job_registry import (
    JobBatchFile,
    JobRegistry,
    JobRegistryError,
    SubmittedJob,
)


def _job(sid, batch="b1", label=None, minutes=0):
    return SubmittedJob(
        label=label or sid,
        sid=sid,
        batch=batch,
        instance="prod",
        query="| makeresults",
        earliest="-1h",
        latest="now",
        submitted_at=datetime(2026, 11, 3, 12, 0) + timedelta(minutes=minutes),
    )


@pytest.fixture
def registry(tmp_path):
    return JobRegistry(tmp_path / "spc" / "jobs.json")


def test_missing_registry_is_empty(registry):
    assert registry.load() == []
    assert registry.latest_batch() is None
    assert registry.batches() == []


def test_add_and_reload_roundtrip(registry):
    registry.add([_job("s1"), _job("s2", minutes=1)])
    jobs = JobRegistry(registry.path).load()
    assert [j.sid for j in jobs] == ["s1", "s2"]
    assert jobs[0].submitted_at == datetime(2026, 11, 3, 12, 0)


def test_add_merges_and_replaces_same_sid(registry):
    registry.add([_job("s1", label="old")])
    registry.add([_job("s1", label="new"), _job("s2", batch="b2", minutes=5)])
    jobs = {j.sid: j for j in registry.load()}
    assert len(jobs) == 2
    assert jobs["s1"].label == "new"


def test_get_filters_by_batch_and_sid(registry):
    registry.add([_job("s1"), _job("s2", minutes=1), _job("s3", batch="b2", minutes=2)])
    assert [j.sid for j in registry.get(batch="b1")] == ["s1", "s2"]
    assert [j.sid for j in registry.get(sids=["s3"])] == ["s3"]
    assert registry.get(batch="b1", sids=["s3"]) == []


def test_latest_batch_and_batches_summary(registry):
    registry.add(
        [_job("s1"), _job("s2", minutes=1), _job("s3", batch="b2", minutes=10)]
    )
    assert registry.latest_batch() == "b2"
    summaries = {s.name: s for s in registry.batches()}
    assert summaries["b1"].jobs == 2
    assert summaries["b1"].instances == ["prod"]
    assert [s.name for s in registry.batches()] == ["b1", "b2"]


def test_corrupted_registry_raises(registry):
    registry.path.parent.mkdir(parents=True)
    registry.path.write_text("{not json")
    with pytest.raises(JobRegistryError, match="corrupted"):
        registry.load()


def test_save_leaves_no_temporary_file(registry):
    registry.add([_job("s1")])
    leftovers = [p.name for p in registry.path.parent.iterdir()]
    assert leftovers == ["jobs.json"]


# ---------------------------------------------------------------- batch file


def test_batch_file_applies_defaults(tmp_path):
    batch_file = tmp_path / "batch.yml"
    batch_file.write_text(
        """
batch: pq-limit
defaults: {earliest: 1793707200, latest: 1793710800, app: SOC}
searches:
  - label: T1
    query: '| makeresults'
  - label: T2
    query: '| makeresults count=2'
    latest: now
    app: search
"""
    )
    parsed = JobBatchFile.from_file(batch_file)
    t1, t2 = parsed.resolved_searches()
    assert parsed.batch == "pq-limit"
    assert (t1.earliest, t1.latest, t1.app) == ("1793707200", "1793710800", "SOC")
    assert (t2.earliest, t2.latest, t2.app) == ("1793707200", "now", "search")


def test_batch_file_without_defaults_uses_last_24h(tmp_path):
    batch_file = tmp_path / "batch.yml"
    batch_file.write_text("searches:\n  - {label: T1, query: '| makeresults'}\n")
    (t1,) = JobBatchFile.from_file(batch_file).resolved_searches()
    assert (t1.earliest, t1.latest, t1.app) == ("-24h", "now", None)


@pytest.mark.parametrize(
    "content, message",
    [
        (
            "searches:\n  - {label: T1, query: a}\n  - {label: T1, query: b}\n",
            "duplicate labels: T1",
        ),
        ("searches:\n  - {label: T1}\n", "query"),
        ("searches: []\n", "searches"),
        ("- just a list\n", "must contain a mapping"),
        ("searches: [\n", "Invalid YAML"),
        ("searches:\n  - {label: T1, query: a, typo: 1}\n", "typo"),
    ],
)
def test_invalid_batch_files_are_rejected(tmp_path, content, message):
    batch_file = tmp_path / "batch.yml"
    batch_file.write_text(content)
    with pytest.raises(JobRegistryError, match=message):
        JobBatchFile.from_file(batch_file)
