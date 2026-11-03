import io
import json
from types import SimpleNamespace

from splunklib.binding import HTTPError

from splunk_power_client.kvstore_apply import (
    Action,
    apply_plan,
    plan_collection,
    plan_definition,
)
from splunk_power_client.kvstore_templates import (
    CollectionTemplate,
    DefinitionTemplate,
)


class FakeService:
    """Minimal splunklib Service: GET returns stored entries, POST is recorded."""

    def __init__(self, entries=None):
        self.entries = entries or {}
        self.posts = []
        self.namespace = SimpleNamespace(app="search", owner="admin", sharing="user")

    def get(self, path, **kwargs):
        if path not in self.entries:
            response = SimpleNamespace(
                status=404, reason="Not Found", body=io.BytesIO(b""), headers=[]
            )
            raise HTTPError(response)
        content, acl = self.entries[path]
        body = json.dumps({"entry": [{"content": content, "acl": acl}]})
        return SimpleNamespace(body=io.StringIO(body))

    def post(self, path, **kwargs):
        self.posts.append((self.namespace.app, self.namespace.owner, path, kwargs))


collection = CollectionTemplate(
    name="assets",
    sharing="global",
    fields={"host": "string", "score": "number"},
    accelerated_fields={"by_host": {"host": 1}},
)
definition = DefinitionTemplate(name="assets", max_matches=1)


def test_create_collection_and_definition():
    service = FakeService()
    plans = [
        plan_collection(service, collection, "my_app"),
        plan_definition(service, definition, "my_app", collection),
    ]
    assert all(not p.exists and p.has_changes for p in plans)
    for plan in plans:
        apply_plan(service, plan)

    (app, owner, path, params), acl, (_, _, dpath, dparams) = service.posts
    assert (app, owner, path) == ("my_app", "nobody", "storage/collections/config")
    assert params["name"] == "assets"
    assert params["field.score"] == "number"
    assert params["accelerated_fields.by_host"] == '{"host": 1}'
    assert acl[2] == "storage/collections/config/assets/acl"
    assert acl[3] == {"sharing": "global", "owner": "nobody"}
    assert dpath == "data/transforms/lookups"
    assert dparams["fields_list"] == "_key, host, score"
    assert dparams["max_matches"] == "1"


def test_up_to_date_collection_has_no_changes():
    current = {
        "field.host": "string",
        "field.score": "number",
        # Splunk returns unset booleans as empty and JSON with other spacing
        "enforceTypes": None,
        "replicate": "0",
        "accelerated_fields.by_host": '{"host":1}',
    }
    service = FakeService(
        {
            "storage/collections/config/assets": (
                current,
                {"sharing": "global", "owner": "bob"},
            )
        }
    )
    plan = plan_collection(service, collection, "my_app")
    assert plan.exists
    assert not plan.has_changes, plan.changes
    apply_plan(service, plan)
    assert service.posts == []


def test_update_collection_sends_only_changes_and_reports_drift():
    current = {
        "field.host": "string",
        "field.score": "string",
        "field.legacy": "string",
        "enforceTypes": "false",
    }
    service = FakeService(
        {
            "storage/collections/config/assets": (
                current,
                {"sharing": "app", "owner": "bob"},
            )
        }
    )
    plan = plan_collection(service, collection, "my_app")
    actions = {c.key: c.action for c in plan.changes}
    assert actions == {
        "field.score": Action.UPDATE,
        "accelerated_fields.by_host": Action.ADD,
        "field.legacy": Action.DRIFT,
    }
    apply_plan(service, plan)
    (_, _, path, params), (_, _, acl_path, acl) = service.posts
    assert path == "storage/collections/config/assets"
    assert params == {
        "field.score": "number",
        "accelerated_fields.by_host": '{"host": 1}',
    }
    assert acl_path.endswith("/acl")
    assert acl == {"sharing": "global", "owner": "bob"}  # owner kept
