import io
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import splunklib.client as client
from splunklib.binding import HTTPError

from splunk_power_client.models import SplunkInstanceInformations

SERVER_INFO = {
    "health_info": "green",
    "host": "sh",
    "host_fqdn": "sh.local",
    "kvStoreStatus": "ready",
    "os_name": "Linux",
    "os_version": "6",
    "startup_time": "2026-11-03T10:00:00",
    "serverName": "sh",
    "guid": "guid",
    "server_roles": ["search_head", "cluster_search_head", "kv_store"],
    "shutting_down": 0,
    "version": "10.0.0",
}
CONTEXT = {"username": "admin", "roles": ["admin"], "capabilities": [], "tz": "UTC"}


def _body(payload: dict) -> SimpleNamespace:
    return SimpleNamespace(body=io.BytesIO(json.dumps(payload).encode()))


def _http_error(status: int) -> HTTPError:
    response = SimpleNamespace(
        status=status,
        reason="Service Unavailable",
        headers=[],
        body=io.BytesIO(b"not part of any cluster configuration"),
    )
    return HTTPError(response)


def _service(members_side_effect) -> MagicMock:
    service = MagicMock(spec=client.Service)

    def get(path, **kwargs):
        if path == "/services/authentication/current-context":
            return _body({"entry": [{"content": CONTEXT}]})
        if path.startswith("/services/shcluster/"):
            return members_side_effect()
        raise AssertionError(f"unexpected call {path}")

    service.get.side_effect = get
    return service


def test_standalone_search_head_with_shc_role():
    def members():
        raise _http_error(503)

    info = SplunkInstanceInformations(service=_service(members), **SERVER_INFO)
    assert info.is_search_head_cluster is False
    assert info.is_search_head_cluster_rolling_restart is False
    assert info.is_search_head_cluster_ready is False
    assert info.search_head_cluster_members == []


MEMBER = {
    "advertise_restart_required": False,
    "artifact_count": 0,
    "is_captain": True,
    "label": "sh1",
    "last_heartbeat": "2026-11-03T10:00:00",
    "no_artifact_replications": False,
    "pending_job_count": 0,
    "precompress_artifacts": False,
    "preferred_captain": True,
    "replication_count": 0,
    "replication_port": 9887,
    "replication_use_ssl": False,
    "site": "default",
    "status": "Up",
}


def test_real_cluster_member_is_detected():
    members = {"entry": [{"name": "sh1", "content": MEMBER}]}
    info = SplunkInstanceInformations(
        service=_service(lambda: _body(members)), **SERVER_INFO
    )
    assert info.is_search_head_cluster is True
    assert [m.name for m in info.search_head_cluster_members] == ["sh1"]


def test_other_http_errors_are_raised():
    def members():
        raise _http_error(500)

    with pytest.raises(HTTPError):
        SplunkInstanceInformations(service=_service(members), **SERVER_INFO)
