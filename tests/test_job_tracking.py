from unittest.mock import MagicMock

import pytest
import splunklib.client as client
from splunklib.binding import HTTPError

from splunk_power_client.job_registry import SubmittedJob
from splunk_power_client.job_tracking import (
    NOT_FOUND,
    TIMEOUT,
    UNREACHABLE,
    JobSnapshot,
    build_jobs_table,
    build_messages_table,
    fetch_job_snapshot,
    parse_job_messages,
    snapshot_from_content,
    wait_for_jobs,
)
from splunk_power_client.models import SplunkInstance, SplunkNameSpace


def _job(sid, label=None):
    return SubmittedJob(label=label or sid, sid=sid, batch="b1")


def test_parse_messages_atom_and_json_formats():
    assert parse_job_messages({"warn": "omitted", "error": ["boom", "bang"]}) == [
        "WARN: omitted",
        "ERROR: boom",
        "ERROR: bang",
    ]
    assert parse_job_messages([{"type": "info", "text": "query"}]) == ["INFO: query"]
    assert parse_job_messages(None) == []


def test_snapshot_from_done_content():
    snapshot = snapshot_from_content(
        "T1",
        "sid1",
        {
            "dispatchState": "DONE",
            "doneProgress": "1.0",
            "resultCount": "1026672",
            "eventCount": "0",
            "runDuration": "312.5",
            "messages": {"warn": "3,154,724 of 3,332,254 events were omitted"},
        },
    )
    assert snapshot.is_terminal and snapshot.is_success
    assert snapshot.result_count == 1026672
    assert snapshot.messages == ["WARN: 3,154,724 of 3,332,254 events were omitted"]


def test_snapshot_failed_keeps_error_message():
    snapshot = snapshot_from_content(
        "T1",
        "sid1",
        {
            "dispatchState": "FAILED",
            "messages": {"info": "x", "fatal": "Error in 'powerquery' command"},
        },
    )
    assert snapshot.is_terminal and not snapshot.is_success
    assert snapshot.error == "FATAL: Error in 'powerquery' command"


def test_fetch_snapshot_not_found_and_unreachable():
    service = MagicMock()
    response = MagicMock(status=404, reason="Not Found", headers=[])
    response.body.read.return_value = b""
    service.job.side_effect = HTTPError(response)
    assert fetch_job_snapshot(service, _job("gone")).state == NOT_FOUND

    service.job.side_effect = ConnectionError("dns")
    snapshot = fetch_job_snapshot(service, _job("s1"))
    assert snapshot.state == UNREACHABLE and not snapshot.is_terminal


def _scripted_fetch(states_by_sid):
    """fetch() returning the next scripted state of each SID at every call."""
    iterators = {sid: iter(states) for sid, states in states_by_sid.items()}

    def fetch(job):
        return JobSnapshot(label=job.label, sid=job.sid, state=next(iterators[job.sid]))

    return fetch


def test_wait_skips_failed_and_cancelled_jobs():
    jobs = [_job("ok"), _job("ko"), _job("cancel")]
    fetch = _scripted_fetch(
        {
            "ok": ["QUEUED", "RUNNING", "DONE"],
            "ko": ["RUNNING", "FAILED"],
            "cancel": ["USER_CANCEL"],
        }
    )
    updates = []
    snapshots = wait_for_jobs(
        jobs,
        fetch,
        timeout=60,
        poll_interval=1,
        on_update=updates.append,
        sleep=lambda _: None,
        clock=lambda: 0,
    )
    assert [s.state for s in snapshots] == ["DONE", "FAILED", "USER_CANCEL"]
    assert len(updates) == 3  # one refresh per polling round


def test_wait_marks_timeout_without_cancelling():
    clock = iter([0, 5, 11]).__next__
    fetch = _scripted_fetch({"slow": ["RUNNING"] * 10, "fast": ["DONE"]})
    snapshots = wait_for_jobs(
        [_job("slow"), _job("fast")],
        fetch,
        timeout=10,
        poll_interval=5,
        sleep=lambda _: None,
        clock=clock,
    )
    assert [s.state for s in snapshots] == [TIMEOUT, "DONE"]


def test_wait_keeps_polling_unreachable_jobs():
    fetch = _scripted_fetch({"s1": [UNREACHABLE, UNREACHABLE, "DONE"]})
    (snapshot,) = wait_for_jobs(
        [_job("s1")],
        fetch,
        timeout=60,
        poll_interval=1,
        sleep=lambda _: None,
        clock=lambda: 0,
    )
    assert snapshot.state == "DONE"


def test_tables_render_without_error():
    snapshots = [
        JobSnapshot(
            label="T1", sid="s1", state="DONE", result_count=5, messages=["WARN: x"]
        ),
        JobSnapshot(label="T2", sid="s2", state="USER_CANCEL"),
    ]
    assert build_jobs_table(snapshots, title="b1").row_count == 2
    assert build_messages_table(snapshots).row_count == 1
    assert build_messages_table(snapshots[1:]) is None


# ---------------------------------------------------------------- submit_job


@pytest.fixture
def instance():
    service = MagicMock(spec=client.Service)
    service.namespace = MagicMock(owner="analyst", app="SOC", sharing="user")
    service.jobs.create.return_value = MagicMock(sid="1793707200.123")
    return SplunkInstance(
        name="prod",
        service=service,
        namespace=SplunkNameSpace(app="SOC", owner="analyst", sharing="user"),
    )


def test_submit_job_dispatches_normal_job_with_ttl(instance):
    job = instance.submit_job(
        '| powerquery limit=0 search="x"',
        earliest_time="1793707200",
        latest_time="1793710800",
        ttl=604800,
    )
    instance.service.jobs.create.assert_called_once_with(
        '| powerquery limit=0 search="x"',
        exec_mode="normal",
        earliest_time="1793707200",
        latest_time="1793710800",
    )
    job.set_ttl.assert_called_once_with(604800)
    assert job.sid == "1793707200.123"


def test_submit_job_prefixes_search_and_sets_app_namespace(instance):
    instance.submit_job("index=main", app="search", ttl=None)
    args, kwargs = instance.service.jobs.create.call_args
    assert args == ("search index=main",)
    assert kwargs["app"] == "search" and kwargs["owner"] == "analyst"
    instance.service.jobs.create.return_value.set_ttl.assert_not_called()
