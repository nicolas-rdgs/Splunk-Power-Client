import io
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import typer

from splunk_power_client.commands import lookups
from splunk_power_client.models import SplunkInstanceLookupKvStore


def _definitions(*entries):
    return SimpleNamespace(
        body=io.BytesIO(
            json.dumps(
                {"entry": [{"name": n, "content": c, "acl": a} for n, c, a in entries]}
            ).encode()
        )
    )


def _kv(service) -> SplunkInstanceLookupKvStore:
    kv = SplunkInstanceLookupKvStore.model_construct(
        name="assets",
        instance=SimpleNamespace(service=service, name="rct"),
        collection=MagicMock(),
        namespace=SimpleNamespace(app="my_app", owner="nobody", sharing="app"),
    )
    return kv


def test_drop_deletes_its_definitions_then_the_collection():
    service = MagicMock()
    service.get.return_value = _definitions(
        (
            "assets",
            {"external_type": "kvstore", "collection": "assets"},
            {"app": "my_app", "owner": "nobody"},
        ),
        (
            "assets_by_ip",
            {"external_type": "kvstore", "collection": "assets"},
            {"app": "my_app", "owner": "bob"},
        ),
        # same collection name, other app: kept
        (
            "assets",
            {"external_type": "kvstore", "collection": "assets"},
            {"app": "other_app", "owner": "nobody"},
        ),
        # other collection: kept
        (
            "assets_old",
            {"external_type": "kvstore", "collection": "assets_v1"},
            {"app": "my_app", "owner": "nobody"},
        ),
    )
    kv = _kv(service)
    calls = MagicMock()
    service.delete.side_effect = lambda path: calls("definition", path)
    kv.collection.delete.side_effect = lambda: calls("collection")

    assert kv.drop() == ["assets", "assets_by_ip"]
    assert [c.args for c in calls.call_args_list] == [
        ("definition", "/servicesNS/nobody/my_app/data/transforms/lookups/assets"),
        ("definition", "/servicesNS/bob/my_app/data/transforms/lookups/assets_by_ip"),
        ("collection",),
    ]
    kv.collection.data.delete.assert_not_called()


def test_rm_data_only_requires_kv():
    with pytest.raises(typer.BadParameter, match="--data-only requires --kv"):
        lookups.rm(search="name=x", instance=None, kv=False, force=True, data_only=True)
