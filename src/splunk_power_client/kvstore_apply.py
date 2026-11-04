"""
Plan / apply KVStore templates on a Splunk instance through the REST API.

- plan_*: read the current object (GET) and compute the changes, nothing is written
- apply_plan: create (POST <endpoint>) or update (POST <endpoint>/<name>) the object,
  then set its sharing (POST <endpoint>/<name>/acl). A collection update sends
  the changed keys only, a definition update sends the whole template (the
  transforms endpoint rewrites the stanza)

Collection keys present on Splunk but absent from the template are reported as
drift and never removed.
"""

import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Optional

from splunklib.binding import HTTPError

from .kvstore_templates import CollectionTemplate, DefinitionTemplate

COLLECTIONS_ENDPOINT = "storage/collections/config"
DEFINITIONS_ENDPOINT = "data/transforms/lookups"

# Splunk defaults, used when a key is not set on the current object
DEFAULTS = {
    "enforceTypes": "false",
    "replicate": "false",
    "replication_dump_strategy": "auto",
    "replication_dump_maximum_file_size": "10240",
    "profilingEnabled": "false",
    "profilingThresholdMs": "1000",
    "case_sensitive_match": "true",
    "max_ext_batch": "300",
    "min_matches": "0",
}
BOOL_KEYS = {"enforceTypes", "replicate", "profilingEnabled", "case_sensitive_match"}
# keys that a template can declare dynamically, reported as drift when missing
DYNAMIC_PREFIXES = ("field.", "accelerated_fields.")


class Action(StrEnum):
    ADD = "add"
    UPDATE = "update"
    DRIFT = "drift (kept)"


@dataclass
class Change:
    key: str
    current: Optional[str]
    desired: Optional[str]
    action: Action


@dataclass
class Plan:
    kind: str  # "collection" | "definition"
    endpoint: str
    name: str
    app: str
    exists: bool
    params: dict[str, str]
    sharing: Optional[str] = None
    current_sharing: Optional[str] = None
    current_owner: Optional[str] = None
    changes: list[Change] = field(default_factory=list)

    @property
    def to_apply(self) -> dict[str, str]:
        if not self.exists:
            return self.params
        return {
            c.key: c.desired
            for c in self.changes
            if c.action != Action.DRIFT and c.key in self.params
        }

    @property
    def acl_to_apply(self) -> bool:
        return self.sharing is not None and self.sharing != self.current_sharing

    @property
    def has_changes(self) -> bool:
        return bool(self.to_apply) or self.acl_to_apply


def _normalize(key: str, value: Any) -> Optional[str]:
    if value is None or value == "":
        return DEFAULTS.get(key)
    if key in BOOL_KEYS:
        return "true" if str(value).lower() in ("1", "true", "t", "yes") else "false"
    if key.startswith("accelerated_fields."):
        try:
            return json.dumps(json.loads(value), sort_keys=True)
        except (TypeError, ValueError):
            return str(value)
    if key == "fields_list":
        return ", ".join(f.strip() for f in str(value).split(",") if f.strip())
    return str(value)


def _set_namespace(service, app: str) -> None:
    # collections and lookup definitions are app-level objects
    service.namespace.app = app
    service.namespace.owner = "nobody"


def get_entry(service, endpoint: str, name: str) -> Optional[dict]:
    """Content (+ eai:acl) of <endpoint>/<name>, None if it does not exist."""
    try:
        response = service.get(f"{endpoint}/{name}", output_mode="json")
    except HTTPError as error:
        if error.status == 404:
            return None
        raise
    entry = json.load(response.body)["entry"][0]
    return {**entry["content"], "eai:acl": entry.get("acl", {})}


def _diff(params: dict[str, str], current: dict) -> list[Change]:
    changes = []
    for key, desired in params.items():
        now = _normalize(key, current.get(key))
        wanted = _normalize(key, desired)
        if now != wanted:
            action = Action.ADD if current.get(key) in (None, "") else Action.UPDATE
            changes.append(Change(key, current.get(key), desired, action))
    for key, value in current.items():
        if key.startswith(DYNAMIC_PREFIXES) and key not in params and value:
            changes.append(Change(key, str(value), None, Action.DRIFT))
    return changes


def _plan(service, kind, endpoint, name, app, params, sharing) -> Plan:
    _set_namespace(service, app)
    current = get_entry(service, endpoint, name)
    plan = Plan(
        kind=kind,
        endpoint=endpoint,
        name=name,
        app=app,
        exists=current is not None,
        params=params,
        sharing=sharing,
    )
    if current is None:
        plan.changes = [Change(k, None, v, Action.ADD) for k, v in params.items()]
    else:
        plan.current_sharing = current["eai:acl"].get("sharing")
        plan.current_owner = current["eai:acl"].get("owner")
        plan.changes = _diff(params, current)
    return plan


def plan_collection(service, template: CollectionTemplate, app: str) -> Plan:
    return _plan(
        service,
        "collection",
        COLLECTIONS_ENDPOINT,
        template.name,
        template.app or app,
        template.to_rest_params(),
        template.sharing,
    )


def plan_definition(
    service,
    template: DefinitionTemplate,
    app: str,
    collection: Optional[CollectionTemplate] = None,
) -> Plan:
    if collection is not None:
        template.check_against(collection)
    return _plan(
        service,
        "definition",
        DEFINITIONS_ENDPOINT,
        template.name,
        template.app or app,
        template.to_rest_params(collection),
        template.sharing,
    )


def apply_plan(service, plan: Plan) -> None:
    _set_namespace(service, plan.app)
    if not plan.exists:
        service.post(plan.endpoint, name=plan.name, **plan.params)
    elif plan.to_apply:
        # data/transforms/lookups/<name> rewrites the whole stanza: a key that
        # is not sent (external_type, collection...) is dropped and the stanza
        # stops being a lookup, so a definition is always sent in full
        params = plan.params if plan.endpoint == DEFINITIONS_ENDPOINT else plan.to_apply
        service.post(f"{plan.endpoint}/{plan.name}", **params)
    if plan.acl_to_apply:
        # sent in the body: as keyword arguments, splunklib takes owner and
        # sharing as the URL namespace and the ACL endpoint answers 400
        service.post(
            f"{plan.endpoint}/{plan.name}/acl",
            body={"sharing": plan.sharing, "owner": plan.current_owner or "nobody"},
        )
