"""
KVStore as code: YAML templates for a collection (collections.conf) and its
lookup definition (transforms.conf), validated with pydantic and translated
into Splunk REST parameters.

Allowed values follow the Splunk 10.0 specs:
- collections.conf: storage/collections/config
- transforms.conf (external_type = kvstore): data/transforms/lookups
"""

import json
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, Optional, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, model_validator

# Collection / definition / field names: no path separator, no Mongo operator
SplunkName = Annotated[str, Field(pattern=r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*$")]
FieldName = Annotated[str, Field(pattern=r"^[^$\s,][^\s,]*$")]


class CollectionFieldType(StrEnum):
    """`field.<name>` types allowed by collections.conf.spec."""

    NUMBER = "number"
    BOOL = "bool"
    STRING = "string"
    TIME = "time"


class Sharing(StrEnum):
    USER = "user"
    APP = "app"
    GLOBAL = "global"


class MatchType(StrEnum):
    EXACT = "EXACT"
    WILDCARD = "WILDCARD"
    CIDR = "CIDR"


def _bool(value: bool) -> str:
    return "true" if value else "false"


class _Template(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    template_version: Literal[1] = 1
    name: SplunkName
    app: Optional[str] = None
    sharing: Optional[Sharing] = None

    @classmethod
    def from_yaml(cls, path: Path) -> Self:
        with path.open(encoding="utf-8") as file:
            return cls.model_validate(yaml.safe_load(file) or {})


class CollectionTemplate(_Template):
    """collections.conf stanza."""

    enforce_types: bool = Field(default=False, alias="enforceTypes")
    replicate: bool = False
    replication_dump_strategy: Literal["auto", "one_file"] = "auto"
    replication_dump_maximum_file_size: NonNegativeInt = 10240
    profiling_enabled: bool = Field(default=False, alias="profilingEnabled")
    profiling_threshold_ms: NonNegativeInt = Field(
        default=1000, alias="profilingThresholdMs"
    )
    fields: Annotated[dict[FieldName, CollectionFieldType], Field(min_length=1)]
    # name -> {field: 1 (ascending) | -1 (descending)}, _key is always accelerated
    accelerated_fields: dict[
        SplunkName, Annotated[dict[FieldName, Literal[1, -1]], Field(min_length=1)]
    ] = {}

    @model_validator(mode="after")
    def check_fields(self) -> Self:
        if "_key" in self.fields:
            raise ValueError("'_key' is managed by Splunk, do not declare it in fields")
        for name, acceleration in self.accelerated_fields.items():
            unknown = set(acceleration) - set(self.fields)
            if unknown:
                raise ValueError(
                    f"accelerated_fields.{name} uses undeclared fields: "
                    + ", ".join(sorted(unknown))
                )
        return self

    def to_rest_params(self) -> dict[str, str]:
        """Parameters for POST storage/collections/config[/<name>]."""
        params = {
            "enforceTypes": _bool(self.enforce_types),
            "replicate": _bool(self.replicate),
            "replication_dump_strategy": self.replication_dump_strategy,
            "replication_dump_maximum_file_size": str(
                self.replication_dump_maximum_file_size
            ),
            "profilingEnabled": _bool(self.profiling_enabled),
            "profilingThresholdMs": str(self.profiling_threshold_ms),
        }
        params |= {f"field.{k}": str(v) for k, v in self.fields.items()}
        params |= {
            f"accelerated_fields.{k}": json.dumps(v)
            for k, v in self.accelerated_fields.items()
        }
        return params


class DefinitionTemplate(_Template):
    """transforms.conf lookup stanza with external_type = kvstore."""

    external_type: Literal["kvstore"] = "kvstore"
    collection: Optional[SplunkName] = None
    fields_list: Optional[Annotated[list[FieldName], Field(min_length=1)]] = None
    filter: Optional[str] = None
    max_matches: Optional[Annotated[int, Field(ge=1, le=1000)]] = None
    min_matches: Optional[NonNegativeInt] = None
    default_match: Optional[str] = None
    case_sensitive_match: Optional[bool] = None
    # field -> WILDCARD / CIDR / EXACT, rendered as "WILDCARD(f), CIDR(g)"
    match_type: dict[FieldName, MatchType] = {}
    time_field: Optional[FieldName] = None
    time_format: Optional[str] = None
    max_offset_secs: Optional[NonNegativeInt] = None
    min_offset_secs: Optional[NonNegativeInt] = None
    max_ext_batch: Optional[Annotated[int, Field(ge=1, le=1000)]] = None

    @model_validator(mode="after")
    def check_definition(self) -> Self:
        if self.fields_list is not None:
            used = set(self.match_type) | ({self.time_field} - {None})
            unknown = used - set(self.fields_list)
            if unknown:
                raise ValueError(
                    "match_type / time_field use fields missing from fields_list: "
                    + ", ".join(sorted(unknown))
                )
        temporal = (self.time_format, self.max_offset_secs, self.min_offset_secs)
        if self.time_field is None and any(v is not None for v in temporal):
            raise ValueError(
                "time_format / max_offset_secs / min_offset_secs need time_field"
            )
        if (
            self.min_matches is not None
            and self.max_matches is not None
            and self.min_matches > self.max_matches
        ):
            raise ValueError("min_matches cannot be greater than max_matches")
        return self

    @property
    def collection_name(self) -> str:
        return self.collection or self.name

    def check_against(self, collection: CollectionTemplate) -> None:
        """Cross-check the definition with the collection it points to."""
        if self.collection_name != collection.name:
            raise ValueError(
                f"Definition '{self.name}' targets collection "
                + f"'{self.collection_name}', not '{collection.name}'"
            )
        if self.fields_list is not None:
            unknown = set(self.fields_list) - {"_key", *collection.fields}
            if unknown:
                raise ValueError(
                    f"fields_list of '{self.name}' has fields not declared in "
                    + f"collection '{collection.name}': {', '.join(sorted(unknown))}"
                )

    def to_rest_params(self, collection: Optional[CollectionTemplate] = None) -> dict:
        """Parameters for POST data/transforms/lookups[/<name>]."""
        fields_list = self.fields_list
        if fields_list is None:
            if collection is None:
                raise ValueError("fields_list is required without a collection")
            fields_list = ["_key", *collection.fields]
        params = {
            "external_type": self.external_type,
            "collection": self.collection_name,
            "fields_list": ", ".join(fields_list),
        }
        if self.match_type:
            params["match_type"] = ", ".join(
                f"{t}({f})" for f, t in self.match_type.items()
            )
        for key in (
            "filter",
            "max_matches",
            "min_matches",
            "default_match",
            "case_sensitive_match",
            "time_field",
            "time_format",
            "max_offset_secs",
            "min_offset_secs",
            "max_ext_batch",
        ):
            value = getattr(self, key)
            if value is not None:
                params[key] = _bool(value) if isinstance(value, bool) else str(value)
        return params


def resolve_template(value: str, kind: str, templates_dir: Path) -> Path:
    """`assets` -> <templates_dir>/<kind>/assets.yaml, an explicit path is kept."""
    path = Path(value).expanduser()
    if path.suffix in (".yaml", ".yml") or path.parent != Path("."):
        return path
    return templates_dir / kind / f"{value}.yaml"
