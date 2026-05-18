import csv
import io
import json
from datetime import datetime, timedelta
from enum import StrEnum
from functools import wraps
from pathlib import Path
from time import sleep, time
from typing import (
    Annotated,
    Any,
    Callable,
    Generator,
    Optional,
    ParamSpec,
    TypeVar,
    Union,
)
from urllib.parse import urlencode

import dateparser
import pandas as pd
import splunklib.client as client
import splunklib.results as results
import typer
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    computed_field,
    field_validator,
    model_validator,
)
from splunklib.binding import AuthenticationError

from .splunk_sdk_patch import NewService

_P = ParamSpec("_P")
_R = TypeVar("_R")


def update_service_namespace_from_instance(func: Callable[_P, _R]) -> Callable[_P, _R]:
    """
    Decorator that updates the service namespace with the instance namespace before calling the decorated method.

    This decorator should be used on methods of SplunkInstance that need to ensure
    the service namespace is synchronized with the instance namespace before making API calls.
    """

    @wraps(func)
    def wrapper(
        cls: Union[
            "SplunkInstance", "SplunkInstanceLookupCSV", "SplunkInstanceLookupKvStore"
        ],
        *args: _P.args,
        **kwargs: _P.kwargs,
    ) -> _R:
        if isinstance(cls, SplunkInstance):
            instance = cls
        else:
            instance = cls.instance

        if instance.service and instance.namespace:
            instance.service.namespace.app = instance.namespace.app
            instance.service.namespace.owner = instance.namespace.owner
            instance.service.namespace.sharing = instance.namespace.sharing

        return func(cls, *args, **kwargs)

    return wrapper


def convert_bytes_to_human(size_bytes: int) -> str:
    # TODO: move to utils? cause cyclic import error
    import math

    if size_bytes == 0:
        return "0B"
    size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_name[i]}"


class StrEnum(StrEnum):
    def __str__(self):
        return self.value


class SortDirection(StrEnum):
    ASC = "asc"
    DESC = "desc"


class FileType(StrEnum):
    CSV = "csv"
    JSON = "json"
    XLSX = "xlsx"
    RAW = "raw"


class SharingEnum(StrEnum):
    USER = "user"
    APP = "app"
    GLOBAL = "global"
    SYSTEM = "system"


class KvStoreFieldType(StrEnum):
    NUMBER = "number"
    BOOL = "bool"
    STRING = "string"
    TIME = "time"
    ARRAY = "array"


class JobStatus(StrEnum):
    RUNNING = "RUNNING"
    PARSING = "PARSING"
    QUEUED = "QUEUED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    FINALIZING = "FINALIZING"
    PAUSE = "PAUSE"
    INTERNAL_CANCEL = "INTERNAL_CANCEL"
    USER_CANCEL = "USER_CANCEL"
    BAD_INPUT_CANCEL = "BAD_INPUT_CANCEL"
    QUIT = "QUIT"
    DONE = "DONE"


# =============================================================================
# Replay Models
# =============================================================================


class ReplayConfig(BaseModel):
    """Configuration for the replay operation."""

    earliest_time: str = "-2d@d"
    latest_time: str = "now"
    time_span: str = "1h"
    max_concurrents: int = 3
    max_retry: int = 2
    timeout: int = 300  # seconds
    output_dir: Optional[Path] = None
    output_format: "FileType" = Field(default="json")
    trigger_actions: bool = False
    poll_interval: int = 5  # seconds between status checks


class ReplaySummary(BaseModel):
    """Summary statistics for display before confirmation."""

    search_count: int  # Number of unique saved searches
    total_jobs: int  # Total job occurrences to launch
    earliest_time: datetime  # Parsed earliest time
    latest_time: datetime  # Parsed latest time
    time_window_human: str  # Human-readable time window (e.g., "2 days")
    trigger_actions: bool  # Whether trigger actions is enabled
    max_concurrent: int  # Max concurrent jobs
    time_span: str  # Time span per job (e.g., "1h")


class ReplayJob(BaseModel):
    """Represents a single replay job occurrence with time block."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: int
    saved_search: "SplunkInstanceSavedSearch"
    earliest_time: datetime
    latest_time: datetime
    sid: Optional[str] = None
    job: Optional[client.Job] = None
    attempts: int = 0
    max_attempts: int = 3
    start_time: Optional[datetime] = None
    error_message: Optional[str] = None
    is_timeout: bool = False
    is_splunk_restarting: bool = False

    @computed_field
    @property
    def status(self) -> Optional[JobStatus]:
        """Get job status from Splunk SDK by refreshing the job state."""
        if self.job is None:
            return None
        self.job.refresh()
        return JobStatus(self.job["dispatchState"])

    @computed_field
    @property
    def display_status(self) -> str:
        """Get display status for UI, handling special cases."""
        if self.is_splunk_restarting:
            return "SPLUNK IS RESTARTING"
        if self.is_timeout:
            return "TIMEOUT"
        if self.status is None:
            return "PENDING"
        return self.status.value

    @computed_field
    @property
    def title(self) -> str:
        """Get saved search title."""
        return self.saved_search.title

    @computed_field
    @property
    def time_range(self) -> str:
        """Get human-readable time range for this job."""
        return f"{self.earliest_time.strftime('%Y-%m-%d %H:%M')} - {self.latest_time.strftime('%Y-%m-%d %H:%M')}"


class SavedSearchAlertComparatorEnum(StrEnum):
    GREATER_THAN = "greater than"
    LESS_THAN = "less than"
    EQUAL_TO = "equal to"
    RISES_BY = "rises by"
    DROPS_BY = "drops by"
    RISES_BY_PERC = "rises by perc"
    DROPS_BY_PERC = "drops by perc"


class SavedSearchAlertTypeEnum(StrEnum):
    ALWAYS = "always"
    CUSTOM = "custom"
    NUMBER_OF_EVENTS = "number of events"
    NUMBER_OF_HOSTS = "number of hosts"
    NUMBER_OF_SOURCES = "number of sources"


class SavedSearchSchedulePriorityEnum(StrEnum):
    DEFAULT = "default"
    HIGHER = "higher"
    HIGHEST = "highest"


class CopyStatusEnum(StrEnum):
    COPYING = "copying"
    DONE = "done"
    FAILED = "failed"


class CopyObject(BaseModel):
    src: Union[
        "SplunkInstanceLookupCSV", "SplunkInstanceLookupKvStore", "LocalLookupFile"
    ]
    dst: Union[
        "SplunkInstanceLookupCSV", "SplunkInstanceLookupKvStore", "LocalLookupFile"
    ]
    status: Optional[CopyStatusEnum] = None


class SPCCommonOptions(BaseModel):
    namespace_app: Optional[str] = Field(None)
    namespace_owner: Optional[str] = Field(None)


class SplunkNameSpace(BaseModel):
    app: str = Field("search")
    owner: str = Field("nobody")
    sharing: SharingEnum = Field(SharingEnum.APP)


class SplunkInstance(BaseModel):
    """Splunk Instance Model"""

    model_config = ConfigDict(use_enum_values=True, arbitrary_types_allowed=True)

    name: Optional[str] = Field(None)
    host: str = Field("localhost")
    port: int = Field(8089)
    token: Optional[str] = Field(None)
    username: Optional[str] = Field(None)
    password: Optional[str] = Field(None)
    ssl_verify: bool = Field(True)
    namespace: SplunkNameSpace = Field(SplunkNameSpace())
    service: Optional[client.Service] = Field(None)
    info: Optional["SplunkInstanceInformations"] = Field(None)

    @field_validator("*")
    @classmethod
    def empty_as_none(cls, v):
        return v or None if isinstance(v, (str,)) else v

    def login(self) -> None:
        # Use Splunk SDK Patch to add additional functionality

        # TODO:
        #   - check if namespace is correct
        #     after test, the ns is still nobody instead of instance config
        #   - add cache login, reuse session if it still available (perf)
        connect_options = {
            "host": self.host,
            "port": self.port,
            "sharing": self.namespace.sharing,
            "owner": self.namespace.owner,
            "app": self.namespace.app,
            "verify": self.ssl_verify,
            "autologin": True,
        }
        try:
            if self.token:
                # self.service = client.connect(**connect_options, token=self.token)
                self.service = NewService(**connect_options, token=self.token)
                self.service.login()
            elif self.username and self.password:
                # self.service = client.connect(
                #    **connect_options, username=self.username, password=self.password
                # )
                self.service = NewService(
                    **connect_options, username=self.username, password=self.password
                )
                self.service.login()
            else:
                raise typer.BadParameter(
                    "Token or username and password are required",
                    param_hint="Authentication Error",
                )
            self.info = SplunkInstanceInformations(
                service=self.service, **self.service.info
            )
        except client.AuthenticationError as error:
            raise typer.BadParameter(
                f"Invalid token or username and password: {error}",
                param_hint="Authentication Error",
            )
        except client.HTTPError as error:
            raise typer.BadParameter(
                f"Invalid host, port, or SSL verification: {error}",
                param_hint="Authentication Error",
            )
        except Exception as error:
            raise typer.BadParameter(
                f"{error}",
                param_hint="Authentication Error",
            )

    def get_limits(self, stanza: str, option: str) -> Union[str, int]:
        value = self.service.confs["limits"][stanza][option]
        if isinstance(value, str) and value.isdigit():
            return int(value)
        else:
            return value

    def get_refreshable_entities(self, entities: Optional[list[str]] = []) -> list[str]:
        """
        Get the list of refreshable entities.

        ### Arguments
        - *entities: list[str]
          - List of entities to refresh.
          - If not provided, all entities will be returned.
          - ex: ["data/ui/manager", "data/ui/nav", "data/ui/views"]

        ### Returns
        - list[str]
          - List of endpoints to refresh.
          - ex: ["/servicesNS/nobody/search/data/ui/manager/_reload", "/servicesNS/nobody/search/data/ui/nav/_reload"]
        """
        endpoint_list = []
        if entities:
            for entity in entities:
                endpoint_list.append(f"/servicesNS/nobody/search/{entity}/_reload")

            return endpoint_list
        else:
            response: dict = self.service.get(
                "/servicesNS/-/search/admin", output_mode="json", count=0
            )
            response_json = json.load(response.body)

            endpoint_exclusion_list = [
                "auth-services",
                "remote_indexes",
                "riq-config",
                "roq-config",
                "fshpasswords",
            ]

            manual_endpoint = [
                "/servicesNS/nobody/search/data/ui/manager/_reload",
                "/servicesNS/nobody/search/data/ui/nav/_reload",
                "/servicesNS/nobody/search/data/ui/views/_reload",
            ]
            endpoint_list.extend(manual_endpoint)

            for endpoint in response_json["entry"]:
                if endpoint["name"] in endpoint_exclusion_list:
                    continue
                if "_reload" in endpoint["links"]:
                    reload_link = endpoint["links"]["_reload"].split("/")
                    reload_link[2] = "nobody"
                    reload_link[3] = "search"

                    endpoint_list.append("/".join(reload_link))

            return endpoint_list

    @update_service_namespace_from_instance
    def get_configs(
        self, name: str
    ) -> Generator["SplunkInstanceConfigFile", None, None]:
        # endpoint: /services/configs/confs-
        # endpoint: /services/properties
        # doesn't support search and pagination filters
        for config_file in self.service.confs.list():
            if config_file.name == name:
                yield SplunkInstanceConfigFile(
                    instance=self,
                    entity=config_file,
                    name=name,
                )

    @update_service_namespace_from_instance
    def get_users(
        self, search: str = ""
    ) -> Generator["SplunkInstanceUser", None, None]:
        for user in self.service.users.list(search=search):
            from rich import print

            print(user)

            print(user.content)
            yield SplunkInstanceUser(instance=self, entity=user, **user.content)

    @update_service_namespace_from_instance
    def create_config(self, name: str) -> "SplunkInstanceConfigFile":
        return SplunkInstanceConfigFile(
            name=name, instance=self, entity=self.service.confs.create(name=name)
        )

    def get_lookup_table_files(
        self,
        search: str = "",
        limit: int = 0,
    ) -> Generator["SplunkInstanceLookupCSV", None, None]:
        # TODO: add namespace filter when provided from URI
        #       or add by default the namespace?
        response = self.service.get(
            "/services/data/lookup-table-files/",
            output_mode="json",
            count=limit,
            search=search,
        )

        response_json = json.loads(response.body.read())

        for file in response_json["entry"]:
            yield SplunkInstanceLookupCSV(
                name=file["name"],
                instance=self,
                namespace=SplunkNameSpace(
                    app=file["acl"]["app"],
                    owner=file["acl"]["owner"],
                    sharing=file["acl"]["sharing"],
                ),
            )

    @update_service_namespace_from_instance
    def get_kvstore_collections(
        self, search: str = ""
    ) -> Generator["SplunkInstanceLookupKvStore", None, None]:
        for kv in self.service.kvstore.list(count=-1, search=search):
            yield SplunkInstanceLookupKvStore(
                name=kv.name,
                instance=self,
                collection=kv,
                config=SplunkKvStoreCollectionConfig(**kv.content),
                namespace=SplunkNameSpace(
                    app=kv.access.app,
                    owner=kv.access.owner,
                    sharing=kv.access.sharing,
                ),
            )

    @update_service_namespace_from_instance
    def get_saved_searches(
        self,
        count: int = -1,
        sort_key: str = "name",
        sort_dir: SortDirection = SortDirection.ASC,
        search: str = "",
    ) -> Generator["SplunkInstanceSavedSearch", None, None]:
        """
        Get savedsearches from the Splunk instance.

        ### Arguments
        - *count: int
          - Maximum number of savedsearches to return.
          - If 0, all savedsearches will be returned.
        - *sort_key: str
          - Field to sort the savedsearches by.
        - *sort_dir: SortDirection (asc or desc)
          - Direction to sort the savedsearches by.
        - *search: str
          - Search query to filter the savedsearches.
        """
        from .utils import convert_flatten_dict_to_nested

        def sanitize_saved_search_from_api(ss_content: dict) -> dict:
            """
            Splunk doesn't format correctly the output
            """
            import re

            patterns = [
                (
                    '"(action\\.\\w+|alert\\.suppress|auto_summarize|display\\.visualizations\\.charting\\.layout\\.splitSeries)":',
                    '"\\1.enabled":',
                ),
                ('"(display\\.visualizations\\.charting\\.chart)":', '"\\1.type":'),
            ]

            ss_content = json.dumps(ss_content)
            for pattern, replacement in patterns:
                ss_content = re.sub(pattern, replacement, ss_content)

            return json.loads(ss_content)

        list_savedsearches = self.service.saved_searches.list(
            count=count,
            sort_key=sort_key,
            sort_dir=sort_dir.value,
            search=search,
            add_orphan_field=True,
        )
        for savedsearch in list_savedsearches:
            savedsearch_content = convert_flatten_dict_to_nested(
                sanitize_saved_search_from_api(savedsearch.content)
            )

            yield SplunkInstanceSavedSearch(
                instance=self,
                entity=savedsearch,
                title=savedsearch.state.title,
                namespace=SplunkNameSpace(
                    app=savedsearch.access.app,
                    owner=savedsearch.access.owner,
                    sharing=savedsearch.access.sharing,
                ),
                updated=savedsearch.state.updated,
                **savedsearch_content,
            )

    @update_service_namespace_from_instance
    def get_jobs(
        self,
        count: int = 0,
        sort_key: str = "dispatch_time",
        sort_dir: SortDirection = SortDirection.DESC,
        search: str = "",
    ) -> Generator["SplunkInstanceJob", None, None]:
        """
        Get jobs from the Splunk instance.

        ### Arguments
        - *count: int
          - Maximum number of jobs to return.
          - If 0, all jobs will be returned.
        - *sort_key: str
          - Field to sort the jobs by.
        - *sort_dir: SortDirection (asc or desc)
          - Direction to sort the jobs by.
        - *search: str
          - Search query to filter the jobs.
        """
        search = (
            "(NOT scheduler__nobody__system__SMA* AND NOT "
            + "(label=CASE(*_ACCELERATE_*) AND provenance=scheduler) AND NOT "
            + 'CASE(_AUTOSUMMARY_) AND NOT "|*summarize*action=") AND (dispatchState=*) NOT isDataPreview="1"'
            + f" {search}"
        )
        list_jobs = self.service.jobs.list(
            count=count, sort_key=sort_key, sort_dir=sort_dir.value, search=search
        )
        for job in list_jobs:
            # TODO: dispatch_time is not available in the job object
            #       we need to get it from the job.state?
            yield SplunkInstanceJob(
                title=job.state.title,
                published=job.state.published,
                author=job.state.author,
                namespace=SplunkNameSpace(
                    app=job.access.app,
                    owner=job.access.owner,
                    sharing=job.access.sharing,
                ),
                instance=self,
                entity=job,
                updated=job.state.updated,
                **job.content,
            )

    @update_service_namespace_from_instance
    def get_job_results(self, job_sid: str) -> list[dict[str, Any]]:
        # TODO: convert it to Generator instead?
        try:
            max_rows_per_query = self.get_limits(
                "kvstore", "max_rows_per_query"
            )  # TODO: bad option
            job = self.service.job(job_sid)
            job_results = []
            for offset in range(0, int(job.content.resultCount), max_rows_per_query):
                for row in results.JSONResultsReader(
                    job.results(count=0, offset=offset, output_mode="json")
                ):
                    if isinstance(row, dict):
                        job_results.append(row)
            return job_results
        except client.HTTPError:
            raise typer.BadParameter(
                f"Job {job_sid} not found",
                param_hint=f"Splunk Instance ({self.name})",
            )
        except Exception as error:
            raise typer.BadParameter(
                f"Unknown error: {error}",
                param_hint=f"Splunk Instance ({self.name})",
            )

    @update_service_namespace_from_instance
    def get_job_searchlog(self, job_sid: str) -> str:
        try:
            job = self.service.job(job_sid)
            return io.TextIOWrapper(job.searchlog()).read()
        except client.HTTPError:
            raise typer.BadParameter(
                f"Job {job_sid} not found",
                param_hint=f"Splunk Instance ({self.name})",
            )
        except Exception as error:
            raise typer.BadParameter(
                f"Unknown error: {error}",
                param_hint=f"Splunk Instance ({self.name})",
            )

    @update_service_namespace_from_instance
    def get_secrets(
        self,
        search: str = "",
        sort_key: str = "",
        sort_dir: SortDirection = SortDirection.DESC,
        limit: int = -1,
    ) -> Generator["SplunkInstanceSecret", None, None]:
        for secret in self.service.storage_passwords.list(
            search=search, sort_key=sort_key, sort_dir=sort_dir.value, count=limit
        ):
            if (
                secret.realm.startswith("__REST")
                and secret.clear_password.count("`") > 2
            ):
                # skip garbage secrets created by Splunk Addon Builder
                continue
            yield SplunkInstanceSecret(
                realm=secret.realm,
                username=secret.username,
                password=secret.clear_password,
                updated=secret.state.updated,
                namespace=SplunkNameSpace(
                    app=secret.access.app,
                    owner=secret.access.owner,
                    sharing=secret.access.sharing,
                ),
                instance=self,
                entity=secret,
            )

    @update_service_namespace_from_instance
    def create_secret(self, realm: str, username: str, password: str) -> None:
        secret = self.service.storage_passwords.create(
            realm=realm, username=username, password=password
        )

        return SplunkInstanceSecret(
            realm=secret.realm,
            username=secret.username,
            password=password,
            updated=secret.state.updated,
            namespace=SplunkNameSpace(
                app=secret.access.app,
                owner=secret.access.owner,
                sharing=secret.access.sharing,
            ),
            service=self.service,
            instance=self,
            entity=secret,
        )

    def send_events(
        self,
        index: str,
        sourcetype: str,
        source: str,
        data: str,
        host: Optional[str] = None,
        host_regex: Optional[str] = None,
    ):
        self.service.post(
            "/services/receivers/simple",
            host=host,
            host_regex=host_regex,
            index=index,
            sourcetype=sourcetype,
            source=source,
            body=data,
        )

    def stream_events(
        self,
        index: str,
        sourcetype: str,
        source: str,
        host: Optional[str] = None,
    ) -> "SplunkStreamConnection":
        """Create a streaming connection for sending events to Splunk.

        Usage:
            with instance.stream_events(index="main", sourcetype="json", source="test") as stream:
                stream.send("event data\\n")
                stream.send_batch(["event1", "event2", "event3"])
        """
        return SplunkStreamConnection(
            instance=self,
            index=index,
            sourcetype=sourcetype,
            source=source,
            host=host,
        )


class SplunkStreamConnection:
    """Streaming connection to Splunk's receivers/stream endpoint.

    Uses the already-authenticated service from SplunkInstance.login().
    Automatically refreshes connection every 20 seconds to avoid splunkd 30s timeout.
    """

    REFRESH_INTERVAL = 20  # seconds - refresh before splunkd 30s timeout

    def __init__(
        self,
        instance: SplunkInstance,
        index: str,
        sourcetype: str,
        source: str,
        host: Optional[str] = None,
    ):
        self.instance = instance
        self.index = index
        self.sourcetype = sourcetype
        self.source = source
        self.host = host
        self._socket = None
        self._connection_start: float = 0

    def _connect(self) -> None:
        """Establish streaming connection to Splunk."""
        service = self.instance.service

        # Build query params
        args = {
            "index": self.index,
            "sourcetype": self.sourcetype,
            "source": self.source,
        }
        if self.host:
            args["host"] = self.host
        path = f"/services/receivers/stream?{urlencode(args)}"

        # Use SDK's connect() for SSL-handled raw socket
        self._socket = service.connect()

        # Build HTTP headers using service's existing auth
        # service._auth_headers returns list of tuples: [("Authorization", "Splunk ...")]
        auth_headers = "\r\n".join(f"{k}: {v}" for k, v in service._auth_headers)

        headers = (
            f"POST {path} HTTP/1.1\r\n"
            f"Host: {service.host}:{service.port}\r\n"
            f"Accept-Encoding: identity\r\n"
            f"{auth_headers}\r\n"
            f"X-Splunk-Input-Mode: Streaming\r\n"
            f"\r\n"
        )
        self._socket.sendall(headers.encode("utf-8"))
        self._connection_start = time()

    def _reconnect(self) -> None:
        """Close and reopen the connection to avoid timeout."""
        if self._socket:
            self._socket.close()
            self._socket = None
        self._connect()

    def _check_refresh(self) -> None:
        """Refresh connection if approaching timeout."""
        elapsed = time() - self._connection_start
        if elapsed >= self.REFRESH_INTERVAL:
            self._reconnect()

    def __enter__(self) -> "SplunkStreamConnection":
        self._connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._socket:
            self._socket.close()
            self._socket = None

    def send(self, data: Union[str, bytes]) -> None:
        """Send data to the stream."""
        if isinstance(data, str):
            data = data.encode("utf-8")
        self._socket.sendall(data)

    def send_batch(self, events: list[str], delimiter: str = "\n") -> int:
        """Send a batch of events. Returns number of events sent."""
        if not events:
            return 0
        # Check if connection needs refresh before sending
        self._check_refresh()
        data = delimiter.join(events)
        if not data.endswith(delimiter):
            data += delimiter
        self.send(data)
        return len(events)


class SplunkInstanceSavedSearch(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    instance: SplunkInstance
    entity: Optional[client.SavedSearch] = None

    title: str
    namespace: SplunkNameSpace
    action: Optional[list["SavedSearchAction"]] = None
    alert: "SavedSearchAlert"
    alert_comparator: Optional[SavedSearchAlertComparatorEnum] = (
        SavedSearchAlertComparatorEnum.GREATER_THAN
    )
    alert_condition: Optional[str] = None
    alert_threshold: Optional[int]
    alert_type: SavedSearchAlertTypeEnum = SavedSearchAlertTypeEnum.NUMBER_OF_EVENTS
    allow_skew: int
    cron_schedule: Optional[str] = None
    description: Optional[str] = None
    disabled: bool
    dispatch: "SavedSearchDispatch"
    dispatch_as: str = Field(alias="dispatchAs")
    is_scheduled: bool
    is_visible: bool
    is_orphan: bool = Field(alias="orphan")
    max_concurrent: int
    next_scheduled_time: Optional[datetime]
    schedule_as: str
    schedule_priority: SavedSearchSchedulePriorityEnum = (
        SavedSearchSchedulePriorityEnum.DEFAULT
    )
    schedule_window: Union[int, Annotated[str, Field(pattern="^auto$")]] = 0
    search: str
    updated: Optional[datetime] = None

    @model_validator(mode="before")
    @classmethod
    def parse_input(cls, values: dict[str, Any]) -> dict:
        action = []
        for action_name in values.get("action", {}):
            action.append(
                SavedSearchAction(name=action_name, **values["action"][action_name])
            )
        values["action"] = action
        if "next_scheduled_time" in values and values["next_scheduled_time"]:
            values["next_scheduled_time"] = dateparser.parse(
                values["next_scheduled_time"]
            ).astimezone()
        return values

    @computed_field
    @property
    def actions(self) -> Union[None, str]:
        return ",".join([action.name for action in self.action if action.enabled])

    def set_action(): ...

    def remove_action(): ...


class SavedSearchAction(BaseModel):
    model_config = {"extra": "allow"}

    enabled: Optional[bool] = None
    name: str
    maxresults: Optional[int] = None
    force_csv_results: Optional[Union[bool, str]] = Field(None, alias="forceCsvResults")
    param: Optional["SavedSearchActionParam"] = None
    track_alert: Optional[bool] = None
    ttl: Optional[int] = None


class SavedSearchActionEmail(SavedSearchAction):
    allow_empty_attachment: Optional[int] = None
    from_address: str = Field(alias="from", serialization_alias="from")
    to_address: str = Field(alias="to", serialization_alias="to")
    cc_address: str = Field(alias="cc", serialization_alias="cc")
    bcc_address: str = Field(alias="bcc", serialization_alias="bcc")


class SavedSearchAlert(BaseModel):
    digest_mode: bool
    expires: str
    severity: int
    suppress: "SavedSearchAlertSuppress"
    track: bool


class SavedSearchAlertSuppress(BaseModel):
    enabled: Optional[bool]
    fields: Optional[str]
    group_name: Optional[str]
    period: Optional[str]


class SavedSearchActionParam(BaseModel):
    model_config = {"extra": "allow"}


class SavedSearchDispatch(BaseModel):
    earliest_time: Optional[str] = None
    latest_time: Optional[str] = None
    index_earliest: Optional[str] = None
    index_latest: Optional[str] = None
    ttl: Optional[Union[int, str]] = None


class SplunkInstanceInformations(BaseModel):
    """Splunk Instance Informations Model"""

    model_config = {"arbitrary_types_allowed": True}

    service: client.Service

    health_info: str
    host: str
    host_fqdn: str
    current_context: Optional["SplunkInstanceCurrentContext"] = None
    kvstore_status: str = Field(alias="kvStoreStatus")
    os_name: str
    os_version: str
    startup_time: datetime
    search_head_cluster_label: Optional[str] = Field(None, alias="shcluster_label")
    search_head_cluster_members: list["SplunkInstanceSearchHeadClusterMember"] = []
    server_name: str = Field(alias="serverName")
    server_guid: str = Field(alias="guid")
    server_roles: list
    shutting_down: int
    version: str
    is_restarting: bool = False

    def model_post_init(self, context: Any):
        response = json.load(
            self.service.get(
                "/services/authentication/current-context", output_mode="json"
            ).body
        )
        current_context = SplunkInstanceCurrentContext(
            **response["entry"][0]["content"]
        )
        self.current_context = current_context

        if self.is_search_head_cluster:
            response = self.service.get(
                "/services/shcluster/member/members",
                output_mode="json",
                count=0,
                search='eai:acl.owner="*"',
            )
            response_json = json.load(response.body)
            for entry in response_json["entry"]:
                self.search_head_cluster_members.append(
                    SplunkInstanceSearchHeadClusterMember(
                        name=entry["name"], **entry["content"]
                    )
                )

    def is_available(self) -> bool:
        """
        Raise ConnectionRefusedError if the instance is down or restarting (even if it's a search head cluster)
        Return True if the instance is available
        """
        while True:
            try:
                self.service.info  # cause ConnectionRefused if it's down
                if self.is_search_head_cluster and (
                    self.is_search_head_cluster_rolling_restart
                    or not self.is_search_head_cluster_ready
                ):
                    raise ConnectionRefusedError
                break
            except (ConnectionRefusedError, AuthenticationError):
                self.is_restarting = True
                sleep(60)
        self.is_restarting = False
        return True

    @computed_field
    @property
    def is_search_head_cluster(self) -> bool:
        # is a shc deployer necessarily a cluster_search_head or is it a bad configuration?
        # otherwise, all api /services/shcluster* fail if the splunk has shc_deployer role because it's not a cluster member
        return (
            True
            if "cluster_search_head" in self.server_roles
            and "shc_deployer" not in self.server_roles
            else False
        )

    @computed_field
    @property
    def is_search_head_cluster_captain(self) -> bool:
        return True if "shc_captain" in self.server_roles else False

    @computed_field
    @property
    def is_search_head_cluster_rolling_restart(self) -> bool:
        if self.is_search_head_cluster:
            status = json.load(
                self.service.get("/services/shcluster/status", output_mode="json").body
            )
            return status["entry"][0]["content"]["captain"][
                "rolling_restart_flag"
            ]  # TODO: create model
        return False

    @computed_field
    @property
    def is_search_head_cluster_ready(self) -> bool:
        if self.is_search_head_cluster:
            status = json.load(
                self.service.get("/services/shcluster/status", output_mode="json").body
            )
            return status["entry"][0]["content"]["captain"][
                "service_ready_flag"
            ]  # TODO: create model
        return False


class SplunkInstanceCurrentContext(BaseModel):
    username: str
    roles: list[str]
    capabilities: list[str]
    tz: str


class SplunkInstanceSearchHeadClusterMember(BaseModel):
    name: str
    advertise_restart_required: bool
    artifact_count: int
    is_captain: bool
    label: str
    last_heartbeat: datetime
    no_artifact_replications: bool
    pending_job_count: int
    precompress_artifacts: bool
    preferred_captain: bool
    replication_count: int
    replication_port: int
    replication_use_ssl: bool
    site: str
    status: str


class SplunkInstanceConfigFile(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    instance: SplunkInstance
    entity: client.ConfigurationFile

    name: str
    stanzas: dict[str, "SplunkInstanceConfigFileStanza"] = {}

    def model_post_init(self, context: Any):
        if not self.stanzas:
            for stanza in self.entity.list():
                content = {
                    k: v for k, v in stanza.content.items() if not k.startswith("eai:")
                }
                self.stanzas[stanza.name] = SplunkInstanceConfigFileStanza(
                    entity=stanza,
                    name=stanza.name,
                    content=content,
                )

    def update(self, stanza_name: str, stanza_content: dict[str, str]) -> None:
        if stanza_name.lower() == "default":
            self.instance.service.post(
                "/servicesNS/"
                + f"{self.instance.namespace.owner}/{self.instance.namespace.app}"
                + f"/properties/{self.name}/default",
                **stanza_content,
            )
        elif stanza_name not in self.stanzas:
            stanza: SplunkInstanceConfigFileStanza = SplunkInstanceConfigFileStanza(
                entity=self.entity.create(stanza_name),
                name=stanza_name,
                content=stanza_content,
            )
            stanza.update()
            self.stanzas.update({stanza_name: stanza})
        else:
            stanza = self.stanzas[stanza_name]
            stanza.content.update(stanza_content)
            stanza.update()

    def delete(self, stanza_name: str, keys: Optional[list[str]] = None) -> None:
        """delete the entire stanza or specific keys"""
        if keys:
            # since 'configs/conf-{file}/{stanza}' or 'properties/{file}/{stanza}/{key}'
            # endpoints API doesn't support DELETE method to remove key in stanza
            # we need to update self.content, delete the stanza then re-create it.
            stanza_content = self.stanzas[stanza_name].content
            new_content: dict[str, str] = {}
            for key, value in stanza_content.items():
                if key in keys:
                    continue
                new_content[key] = value
            self.entity.delete()
            self.update(stanza_name=stanza_name, stanza_content=new_content)
        else:
            # ‘default' cannot be deleted
            # after delete, keep or delete content?
            self.entity.delete(name=stanza_name)


class SplunkInstanceConfigFileStanza(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    entity: client.Stanza

    name: str
    content: dict[str, Union[str, None]]

    def update(self) -> None:
        """synchronize content in Splunk ConfigurationFile"""
        self.entity.update(body={**self.content})

    def delete(self, keys: Optional[list[str]] = None) -> None:
        if keys:
            # since 'configs/conf-{file}/{stanza}' or 'properties/{file}/{stanza}/{key}'
            # endpoints API doesn't support DELETE method to remove key in stanza
            # we need to update self.content, delete the stanza then re-create it.
            new_content = {}
            for key, value in self.content.items():
                if key in keys:
                    continue
                new_content[key] = value
            self.entity.delete()
            self.update()
        else:
            # after delete, keep or delete content?
            self.entity.delete()


class SplunkInstanceJob(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    instance: SplunkInstance
    entity: client.Job

    title: str
    label: Optional[str] = Field(None)
    namespace: SplunkNameSpace
    author: Optional[str] = Field(None)
    earliest_time: Optional[datetime] = Field(alias="earliestTime")
    latest_time: Optional[datetime] = Field(None, alias="latestTime")
    event_count: int = Field(alias="eventCount")
    message: Optional[dict] = {}
    priority: int
    published: Optional[datetime] = Field(None)
    provenance: Optional[str] = Field(None)
    run_duration: str = Field(alias="runDuration")
    result_count: int = Field(alias="resultCount")
    sid: str
    size: int = Field(alias="diskUsage")
    status: JobStatus = Field(alias="dispatchState")
    search: str
    search_providers: list = Field(alias="searchProviders")
    ttl: int
    updated: Optional[datetime] = Field(None)

    @computed_field
    @property
    def size_human(self) -> str:
        return convert_bytes_to_human(self.size)

    @computed_field
    @property
    def expires_at(self) -> datetime:
        if self.updated:
            return self.updated + timedelta(seconds=self.ttl)
        else:
            return None

    @computed_field
    @property
    def name(self) -> str:
        return self.label if self.label else self.title


class SplunkInstanceSecret(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    instance: SplunkInstance
    entity: client.StoragePassword

    realm: str
    username: str
    password: Optional[str] = None
    updated: Optional[datetime] = Field(None)
    namespace: SplunkNameSpace

    def update(self) -> None:
        self.entity.update(password=self.password)

    def delete(self) -> None:
        self.entity.delete()


class SplunkInstanceUser(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    instance: SplunkInstance
    entity: client.User

    default_app: Optional[str] = Field(alias="defaultApp")
    email: str
    name: Optional[str] = None
    password: Optional[str] = None
    realname: Optional[str] = None
    locked_out: bool = Field(
        False, alias="locked-out", serialization_alias="locked-out"
    )
    force_change_pass: bool = Field(
        False, alias="force-change-pass", serialization_alias="force-change-pass"
    )
    restart_background_jobs: Optional[bool] = False
    roles: Optional[list[str]] = None
    capabilities: Optional[list[str]] = None
    tz: None = None


class SplunkKvStoreCollectionConfig(BaseModel):
    disabled: int = Field(0)
    enforce_types: bool = Field(
        False, alias="enforceTypes", serialization_alias="enforceTypes"
    )
    fields: dict[str, KvStoreFieldType]
    accelerated_fields: Optional[dict[str, dict]] = None
    profiling_enabled: bool = Field(
        False, alias="profilingEnabled", serialization_alias="profilingEnabled"
    )
    profiling_threshold_ms: int = Field(
        1000, alias="profilingThresholdMs", serialization_alias="profilingThresholdMs"
    )
    replicate: bool = Field(False)
    replication_dump_maximum_file_size: int = Field(10240)
    replication_dump_strategy: str = Field("auto")

    @model_validator(mode="before")
    @classmethod
    def parse_input(cls, values: dict[str, Any]) -> dict:
        new_input = {"fields": {}, "accelerated_fields": {}}
        for key, value in values.items():
            if key.startswith("field."):
                field_name = key.split(".")[1]
                new_input["fields"][field_name] = KvStoreFieldType(value)
            elif key.startswith("accelerated_fields."):
                field_name = key.split(".")[1]
                if isinstance(value, str):
                    value = json.loads(value)
                new_input["accelerated_fields"][field_name] = value
            else:
                new_input[key] = value
        return new_input


class SplunkLookupDefinition(BaseModel):
    file_name: Optional[str] = Field(None, serialization_alias="filename")
    collection: Optional[str] = Field(None)
    max_matches: int = Field(1, ge=1, le=1000)
    min_matches: int = Field(0, ge=0)
    default_match: Optional[str] = Field(None)
    case_sensitive_match: bool = Field(True)
    match_type: str = Field("EXACT", pattern=r"(EXACT|WILDCARD|CIDR)(\(\w+\))")
    fields_list: Optional[str] = None
    external_type: Optional[str] = Field(None)
    filter: Optional[str] = Field(None)
    replicate: bool = Field(True)

    @field_validator("collection", mode="after")
    @classmethod
    def set_collection_name_if_kvstore(
        cls, collection: str, info: ValidationInfo
    ) -> Optional[str]:
        if info.context and isinstance(info.context, Lookup):
            return info.context.name
        return None


class Lookup(BaseModel):
    name: Optional[str] = None
    definition: Optional[SplunkLookupDefinition] = None
    namespace: Optional[SplunkNameSpace] = None

    model_config = {"arbitrary_types_allowed": True, "from_attributes": True}

    def read(self):
        raise NotImplementedError

    def write(self):
        raise NotImplementedError

    def delete(self):
        raise NotImplementedError

    def get_namespace(self) -> SplunkNameSpace:
        raise NotImplementedError

    def get_instance_name(self) -> str:
        raise NotImplementedError


class SplunkInstanceLookupCSV(Lookup):
    instance: SplunkInstance
    csv_field_size_limit: Optional[int] = None
    lookup_editor_version: int = 0

    def model_post_init(self, context: Any):
        if self.lookup_editor_version == 0 and self.instance.service:
            """
            Check if lookup editor is installed and convert lookup editor version to int
            Example: 4.0.5 -> 40005
            Example: 4.0.1 -> 40001
            """
            try:
                lookup_editor: client.Application = self.instance.service.apps[
                    "lookup_editor"
                ]
            except KeyError:
                # TODO: raise an error when the given app doesn't exists (lookups cp s://local//dummy_app)
                raise typer.BadParameter(
                    "Lookup editor seems not installed on this instance, you must to install it first.",
                    param_hint="Lookups",
                )
            v = list(map(int, lookup_editor.version.split(".")))
            for number, i in zip(v, reversed(range(len(v)))):
                self.lookup_editor_version += number * 100**i

    @update_service_namespace_from_instance
    def read(self) -> list[dict[str, Any]]:
        # Newer version >= 4.0.5
        # they use a POST request to get the lookup as file
        if self.lookup_editor_version >= 40005:
            response = self.instance.service.post(
                "/services/data/lookup_edit/lookup_as_file",
                body={
                    "lookup_file": self.name,
                    "lookup_type": "csv",
                    "namespace": self.instance.service.namespace.app,
                    "owner": self.instance.service.namespace.owner,
                },
            )

        # Old version of Lookup Editor < 4.0.5
        # tested with 4.0.1
        elif self.lookup_editor_version <= 40004:
            response = self.instance.service.get(
                "/services/data/lookup_edit/lookup_as_file",
                lookup_file=self.name,
                body={
                    "namespace": self.instance.service.namespace.app,
                    "owner": self.instance.service.namespace.owner,
                },
            )

        if self.csv_field_size_limit:
            csv.field_size_limit(self.csv_field_size_limit)
        return list(csv.DictReader(io.TextIOWrapper(response.body)))

    def write(self, contents: list[dict[str, Any]]):
        # convert dict to list of list with csv headers as first row
        headers = list(contents[0].keys())
        contents = [headers] + [list(d.values()) for d in contents]
        response = self.instance.service.post(
            "/services/data/lookup_edit/lookup_contents",
            body={
                "lookup_file": self.name,
                "namespace": self.instance.service.namespace.app,
                "owner": self.instance.service.namespace.owner,
                "contents": json.dumps(contents),
            },
        )
        return response, response.body

    def delete(self, query: Optional[str] = "") -> None:
        # query not supported by splunk, we need to run a search to delete specific data
        self.instance.service.delete(
            f"/servicesNS/{self.namespace.owner}/{self.namespace.app}/data/lookup-table-files/{self.name}",
        )
        return None

    def get_namespace(self) -> SplunkNameSpace:
        if self.namespace is None:
            # get namespace from instance if not specified from URI
            # or class instanciated
            return SplunkNameSpace(
                app=self.instance.namespace.app,
                owner=self.instance.namespace.owner,
                sharing=self.instance.namespace.sharing,
            )
        return self.namespace

    def get_instance_name(self) -> str:
        return self.instance.name


class SplunkInstanceLookupKvStore(Lookup):
    instance: SplunkInstance
    collection: Optional[client.KVStoreCollection] = None
    config: Optional[SplunkKvStoreCollectionConfig] = None

    def model_post_init(self, context: Any):
        if self.collection is None:
            try:
                self.collection = self.instance.service.kvstore[self.name]
            except KeyError:
                raise ValueError(f"Collection '{self.name}' not found")
        self.config = SplunkKvStoreCollectionConfig(**self.collection.content)

    def read(
        self,
        query: Optional[dict] = None,
        limit: Optional[int] = None,
        skip: int = 0,
        fields: Optional[str] = None,
        sort: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """
        Read data from the KVStore collection.

        ### Arguments
        - *query: Optional[dict]
          - Query to filter the data
        - *limit: Optional[int]
          - Maximum number of items to return.
        - *skip: Optional[int]
          - Number of items to skip from the start.
        - *fields: Optional[str]
          - Comma-separated list of fields to include
        - *sort: Optional[str]
          - Comma-separated list of fields to sort by
        """
        max_rows_per_query = self.instance.get_limits("kvstore", "max_rows_per_query")

        params = {"skip": skip}

        if query:
            params["query"] = query
        if limit and limit > max_rows_per_query:
            raise typer.BadParameter(
                "limit argument exceeds the 'max_rows_per_query' "
                + f"limit specified under the kvstore stanza in limits.conf ({max_rows_per_query})"
            )
        elif limit:
            params["limit"] = limit
        else:
            params["limit"] = max_rows_per_query
        if fields:
            params["fields"] = fields
        if sort:
            params["sort"] = sort

        documents = []
        while True:
            result = self.collection.data.query(**params)
            params["skip"] += len(result)

            documents.append(result)

            if len(result) != params["limit"]:
                break

        return documents

    def write(self, data: list[dict[str, Any]], append: bool = False) -> None:
        """
        Write data to the KVStore collection.

        ### Arguments
        - *data: list[dict[str, Any]]
          - List of dictionaries to write to the collection.
        - *append: bool
          - If True, data will be appended to the collection.
          - If False, the collection will be deleted and the data will be written.
          - Default is False.
        """
        max_documents_per_batch_save = self.instance.get_limits(
            "kvstore", "max_documents_per_batch_save"
        )
        if not append:
            self.collection.data.delete()
        for i in range(0, len(data), max_documents_per_batch_save):
            self.collection.data.batch_save(*data[i : i + max_documents_per_batch_save])
        return

    def delete(self, query: Optional[dict] = None):
        """
        Delete data from the KVStore collection.

        ### Arguments
        - *query: Optional[dict]
          - Query to filter the data to delete. If not provided, all data will be deleted.
        """
        if query:
            return self.collection.data.delete(query=json.dumps(query))
        else:
            return self.collection.data.delete()

    def get_namespace(self) -> SplunkNameSpace:
        if self.namespace is None:
            # get namespace from instance if not specified from URI
            # or class instanciated
            return SplunkNameSpace(
                app=self.instance.namespace.app,
                owner=self.instance.namespace.owner,
                sharing=self.instance.namespace.sharing,
            )
        return self.namespace

    def get_instance_name(self) -> str:
        return self.instance.name


class LocalLookupFile(Lookup):
    csv_field_size_limit: Optional[int] = None
    _file_handle: Optional[io.TextIOWrapper] = None
    _lock_acquired: bool = False

    @computed_field
    @property
    def file(self) -> Path:
        return Path(self.name)

    @computed_field
    @property
    def file_type(self) -> FileType:
        if self.file.suffix.lower() == ".csv":
            return FileType.CSV
        elif self.file.suffix.lower() == ".json":
            return FileType.JSON
        elif self.file.suffix.lower() == ".xlsx":
            return FileType.XLSX
        elif self.file.suffix.lower() in [".log", ".raw", ".txt"]:
            return FileType.RAW
        else:
            return FileType.CSV

    def read(self) -> list[dict[str, Any]]:
        if not self.file.exists():
            raise FileNotFoundError(
                f"File '{self.file.resolve().as_posix()}' does not exist"
            )
        if self.file_type == FileType.CSV:
            return self.read_from_csv_file()
        elif self.file_type == FileType.XLSX:
            return self.read_from_excel_file()
        elif self.file_type == FileType.JSON:
            return self.read_from_json_file()
        else:
            raise typer.BadParameter(
                f"Unsupported file type: {self.file_type}",
                param_hint="LocalLookupFile",
            )

    def read_from_csv_file(self) -> list[dict[str, Any]]:
        if self.csv_field_size_limit:
            csv.field_size_limit(self.csv_field_size_limit)
        with self.file.open("r") as file:
            return list(csv.DictReader(file))

    def read_from_excel_file(self) -> list[dict[str, Any]]:
        return pd.read_excel(self.file)

    def read_from_json_file(self) -> list[dict[str, Any]]:
        with self.file.open("r") as file:
            return json.load(file)

    def write(self, data: list[dict[str, Any]]):
        if self.file_type == FileType.CSV:
            self.write_to_csv_file(data)
        elif self.file_type == FileType.XLSX:
            self.write_to_excel_file(data)
        elif self.file_type == FileType.JSON:
            self.write_to_json_file(data)
        elif self.file_type == FileType.RAW:
            self.write_to_raw_file(data)
        else:
            raise typer.BadParameter(
                f"Unsupported file type: {self.file_type}",
                param_hint="LocalLookupFile",
            )

    def write_to_csv_file(self, data: list[list[str]]):
        with self.file.open("w") as file:
            writer = csv.DictWriter(file, fieldnames=list(data[0].keys()))
            writer.writeheader()
            writer.writerows(data)

    def write_to_excel_file(self, data: list[dict[str, Any]]):
        # TODO: need to rework
        df = pd.DataFrame(data)
        df.to_excel(self.file, index=False)

    def write_to_json_file(self, data: list[dict[str, Any]]):
        with self.file.open("w") as file:
            if isinstance(data, list):
                for item in data:
                    file.write(json.dumps(item) + "\n")

    def write_to_raw_file(self, data: list[dict[str, Any]]):
        with self.file.open("w") as file:
            for row in data:
                if "_raw" in row:
                    file.write(row["_raw"] + "\n")
                else:
                    typer.BadParameter(
                        "Results must contain '_raw' field for TXT/LOG extension,"
                        + " please use another format",
                        param_hint="Export Data",
                    )
                    break

    def get_namespace(self) -> SplunkNameSpace:
        return SplunkNameSpace(
            app="N/A",
            owner="N/A",
        )

    def get_instance_name(self) -> str:
        return "N/A"

    def acquire_lock(self) -> None:
        """
        Acquire a persistent file lock for append operations.
        The file handle is kept open until release_lock() is called.
        """
        import fcntl

        if self._lock_acquired:
            return

        # Create parent directories if needed
        self.file.parent.mkdir(parents=True, exist_ok=True)

        # Open file in append mode based on file type
        if self.file_type == FileType.JSON:
            # JSON files need special handling - we'll manage as a list
            if not self.file.exists():
                self.file.write_text("[]")
            self._file_handle = self.file.open("r+")
        else:
            # CSV and other text formats can use append mode
            self._file_handle = self.file.open("a+")

        # Acquire exclusive lock
        fcntl.flock(self._file_handle.fileno(), fcntl.LOCK_EX)
        self._lock_acquired = True

    def release_lock(self) -> None:
        """Release the file lock and close the file handle."""
        import fcntl

        if not self._lock_acquired or self._file_handle is None:
            return

        fcntl.flock(self._file_handle.fileno(), fcntl.LOCK_UN)
        self._file_handle.close()
        self._file_handle = None
        self._lock_acquired = False

    def append(self, data: list[dict[str, Any]]) -> None:
        """
        Append data to the file while holding the persistent lock.
        Must call acquire_lock() before using this method.
        """
        if not self._lock_acquired or self._file_handle is None:
            raise RuntimeError("File lock not acquired. Call acquire_lock() first.")

        if self.file_type == FileType.CSV:
            self._append_to_csv(data)
        elif self.file_type == FileType.JSON:
            self._append_to_json(data)
        elif self.file_type == FileType.RAW:
            self._append_to_raw(data)
        else:
            raise typer.BadParameter(
                f"Append not supported for file type: {self.file_type}",
                param_hint="LocalLookupFile",
            )

    def _append_to_csv(self, data: list[dict[str, Any]]) -> None:
        """Append data to CSV file."""
        if not data:
            return

        # Check if file is empty (need to write headers)
        self._file_handle.seek(0, 2)  # Go to end
        file_empty = self._file_handle.tell() == 0

        writer = csv.DictWriter(
            self._file_handle,
            fieldnames=list(data[0].keys()),
        )
        if file_empty:
            writer.writeheader()
        writer.writerows(data)
        self._file_handle.flush()

    def _append_to_json(self, data: list[dict[str, Any]]) -> None:
        """Append data to JSON file (maintains valid JSON array)."""
        if not data:
            return

        # Read existing content
        self._file_handle.seek(0)
        existing_data = json.load(self._file_handle)

        # Append new data
        existing_data.extend(data)

        # Write back
        self._file_handle.seek(0)
        self._file_handle.truncate()
        json.dump(existing_data, self._file_handle)
        self._file_handle.flush()

    def _append_to_raw(self, data: list[dict[str, Any]]) -> None:
        """Append raw data to file."""
        for row in data:
            if "_raw" in row:
                self._file_handle.write(row["_raw"] + "\n")
        self._file_handle.flush()


class FileReader:
    """Simple file reader that yields raw lines for streaming to Splunk.

    Does NOT parse or transform data - sends lines exactly as they appear in the file.
    Splunk will parse the data based on the configured sourcetype.

    Unlike LocalLookupFile (which loads structured data into list[dict] for Lookup Editor),
    this class just reads raw lines for direct ingestion.
    """

    def __init__(self, path: Union[str, Path]):
        self.path = Path(path)

    @property
    def file_size(self) -> int:
        """Get file size in bytes for progress tracking."""
        return self.path.stat().st_size

    def count_lines(self) -> int:
        """Count lines efficiently without loading entire file into memory.

        Reads file in binary mode with large buffer and counts newlines.
        Very fast even for large files (GB+).
        """
        count = 0
        buf_size = 1024 * 1024  # 1MB buffer
        with self.path.open("rb") as f:
            buf = f.read(buf_size)
            while buf:
                count += buf.count(b"\n")
                buf = f.read(buf_size)
        return count

    def iter_lines(self) -> Generator[str, None, None]:
        """Yield each line from the file as-is (stripped of trailing newline)."""
        with self.path.open("r") as f:
            for line in f:
                stripped = line.rstrip("\n\r")
                if stripped:  # Skip empty lines
                    yield stripped

    def iter_batches(self, batch_size: int = 1000) -> Generator[list[str], None, None]:
        """Yield lines in batches for efficient streaming."""
        batch: list[str] = []
        for line in self.iter_lines():
            batch.append(line)
            if len(batch) >= batch_size:
                yield batch
                batch = []
        if batch:
            yield batch
