import pytest
import typer

from splunk_power_client.commands.lookups import (
    parse_kv_accelerated_fields,
    parse_kv_fields,
)
from splunk_power_client.models import KvStoreFieldType


def test_parse_kv_fields_defaults_to_string():
    assert parse_kv_fields(["user", "count:number"]) == {
        "user": KvStoreFieldType.STRING,
        "count": KvStoreFieldType.NUMBER,
    }


@pytest.mark.parametrize("field", ["count:integer", ":number"])
def test_parse_kv_fields_rejects_invalid(field):
    with pytest.raises(typer.BadParameter):
        parse_kv_fields([field])


def test_parse_kv_accelerated_fields():
    assert parse_kv_accelerated_fields(["by_user=user, host"]) == {
        "by_user": {"user": 1, "host": 1}
    }


@pytest.mark.parametrize("accelerated_field", ["by_user", "=user", "by_user="])
def test_parse_kv_accelerated_fields_rejects_invalid(accelerated_field):
    with pytest.raises(typer.BadParameter):
        parse_kv_accelerated_fields([accelerated_field])
