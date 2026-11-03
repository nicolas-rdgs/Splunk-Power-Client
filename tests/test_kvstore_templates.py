from pathlib import Path

import pytest
from pydantic import ValidationError

from splunk_power_client.kvstore_templates import (
    CollectionTemplate,
    DefinitionTemplate,
    resolve_template,
)

examples = Path(__file__).parent.parent / "examples" / "kvstore"


def test_example_templates_are_valid_and_consistent():
    collection = CollectionTemplate.from_yaml(examples / "collections/_template.yaml")
    definition = DefinitionTemplate.from_yaml(examples / "definitions/_template.yaml")
    definition.check_against(collection)

    params = collection.to_rest_params()
    assert params["field.score"] == "number"
    assert params["enforceTypes"] == "false"
    assert params["accelerated_fields.by_host_last_seen"] == (
        '{"host": 1, "last_seen": -1}'
    )

    params = definition.to_rest_params(collection)
    assert params["fields_list"] == "_key, host, ip, score, is_vip, last_seen"
    assert params["match_type"] == "CIDR(ip)"
    assert params["case_sensitive_match"] == "true"


def test_definition_fields_list_defaults_to_collection_fields():
    collection = CollectionTemplate(name="c", fields={"a": "string", "b": "number"})
    definition = DefinitionTemplate(name="c")
    assert definition.to_rest_params(collection)["fields_list"] == "_key, a, b"


@pytest.mark.parametrize(
    "data",
    [
        {"name": "c", "fields": {}},
        {"name": "c", "fields": {"a": "array"}},
        {"name": "c", "fields": {"_key": "string"}},
        {"name": "c", "fields": {"a": "string"}, "accelerated_fields": {"x": {"b": 1}}},
        {"name": "c", "fields": {"a": "string"}, "accelerated_fields": {"x": {"a": 2}}},
        {"name": "c", "fields": {"a": "string"}, "replication_dump_strategy": "x"},
        {"name": "c/x", "fields": {"a": "string"}},
        {"name": "c", "fields": {"a": "string"}, "unknown_key": 1},
    ],
)
def test_invalid_collection(data):
    with pytest.raises(ValidationError):
        CollectionTemplate.model_validate(data)


@pytest.mark.parametrize(
    "data",
    [
        {"name": "d", "external_type": "python"},
        {"name": "d", "max_matches": 0},
        {"name": "d", "max_matches": 1, "min_matches": 2},
        {"name": "d", "fields_list": ["a"], "match_type": {"b": "CIDR"}},
        {"name": "d", "match_type": {"a": "REGEX"}},
        {"name": "d", "time_format": "%s"},
        {"name": "d", "filename": "x.csv"},
    ],
)
def test_invalid_definition(data):
    with pytest.raises(ValidationError):
        DefinitionTemplate.model_validate(data)


def test_definition_with_unknown_collection_field():
    collection = CollectionTemplate(name="c", fields={"a": "string"})
    with pytest.raises(ValueError, match="not declared"):
        DefinitionTemplate(name="c", fields_list=["_key", "b"]).check_against(
            collection
        )


def test_resolve_template(tmp_path):
    assert resolve_template("assets", "collections", tmp_path) == (
        tmp_path / "collections/assets.yaml"
    )
    assert resolve_template("./x.yaml", "collections", tmp_path) == Path("x.yaml")
