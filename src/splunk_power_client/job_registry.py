"""Batch files and persistent registry for jobs dispatched with ``spc jobs submit``.

Every submitted job is recorded in ``~/.spc/jobs.json`` (label, SID, batch,
instance, time range) so ``spc jobs status`` / ``spc jobs wait`` can track it
later, from any directory, even after the terminal that submitted it is closed.
"""

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .utils import spc_config_file

DEFAULT_REGISTRY_FILE = spc_config_file.parent / "jobs.json"
DEFAULT_JOB_TTL = 604800  # 7 days: keep long jobs available while they are audited


class JobRegistryError(Exception):
    """Raised when the registry or a batch file cannot be read."""


# =============================================================================
# Batch file (YAML)
# =============================================================================


class JobSearch(BaseModel):
    """One search of a batch file, before or after defaults are applied."""

    # Epoch values written without quotes in YAML are read as int
    model_config = ConfigDict(coerce_numbers_to_str=True, extra="forbid")

    label: str = Field(min_length=1)
    query: str = Field(min_length=1)
    earliest: Optional[str] = None
    latest: Optional[str] = None
    app: Optional[str] = None


class JobBatchDefaults(BaseModel):
    model_config = ConfigDict(coerce_numbers_to_str=True, extra="forbid")

    earliest: str = "-24h"
    latest: str = "now"
    app: Optional[str] = None


class JobBatchFile(BaseModel):
    """A YAML file declaring several searches to dispatch together.

    ```yaml
    batch: pq-limit
    defaults: {earliest: "1793707200", latest: "1793710800", app: SOC}
    searches:
      - label: T1_nolimit
        query: '| powerquery limit=0 ...'
    ```
    """

    model_config = ConfigDict(extra="forbid")

    batch: Optional[str] = None
    defaults: JobBatchDefaults = Field(default_factory=JobBatchDefaults)
    searches: list[JobSearch] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_labels(self) -> "JobBatchFile":
        seen: set[str] = set()
        duplicates: set[str] = set()
        for search in self.searches:
            if search.label in seen:
                duplicates.add(search.label)
            seen.add(search.label)
        if duplicates:
            raise ValueError(f"duplicate labels: {', '.join(sorted(duplicates))}")
        return self

    def resolved_searches(self) -> list[JobSearch]:
        """Searches with the batch defaults applied to unset fields."""
        return [
            JobSearch(
                label=search.label,
                query=search.query,
                earliest=search.earliest or self.defaults.earliest,
                latest=search.latest or self.defaults.latest,
                app=search.app or self.defaults.app,
            )
            for search in self.searches
        ]

    @classmethod
    def from_file(cls, path: Path) -> "JobBatchFile":
        try:
            with open(path, encoding="utf-8") as stream:
                data = yaml.safe_load(stream)
        except OSError as error:
            raise JobRegistryError(f"Cannot read batch file {path}: {error}") from error
        except yaml.YAMLError as error:
            raise JobRegistryError(f"Invalid YAML in {path}: {error}") from error

        if not isinstance(data, dict):
            raise JobRegistryError(f"{path} must contain a mapping with 'searches'")
        try:
            return cls.model_validate(data)
        except ValidationError as error:
            raise JobRegistryError(f"Invalid batch file {path}:\n{error}") from error


# =============================================================================
# Registry (JSON)
# =============================================================================


class SubmittedJob(BaseModel):
    """A dispatched job, as recorded in the registry."""

    label: str
    sid: str
    batch: str
    instance: Optional[str] = None
    query: str = ""
    earliest: str = ""
    latest: str = ""
    app: Optional[str] = None
    submitted_at: datetime = Field(default_factory=datetime.now)


class JobBatchSummary(BaseModel):
    name: str
    jobs: int
    instances: list[str]
    first_submitted_at: datetime
    last_submitted_at: datetime


def default_batch_name() -> str:
    return f"batch-{datetime.now():%Y%m%d-%H%M%S}"


class JobRegistry:
    """JSON registry of submitted jobs, keyed by SID."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else DEFAULT_REGISTRY_FILE

    def load(self) -> list[SubmittedJob]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8") or "{}")
            return [SubmittedJob.model_validate(job) for job in raw.get("jobs", [])]
        except (json.JSONDecodeError, ValidationError, AttributeError) as error:
            raise JobRegistryError(
                f"Job registry {self.path} is corrupted, fix or remove it: {error}"
            ) from error

    def save(self, jobs: Iterable[SubmittedJob]) -> None:
        """Write the registry atomically (temporary file + rename)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"jobs": [job.model_dump(mode="json") for job in jobs]}
        fd, tmp_name = tempfile.mkstemp(
            dir=self.path.parent, prefix=".jobs.", suffix=".json"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, indent=2, ensure_ascii=False)
            os.replace(tmp_name, self.path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise

    def add(self, new_jobs: Iterable[SubmittedJob]) -> None:
        """Record new jobs; a SID already present is replaced."""
        by_sid = {job.sid: job for job in self.load()}
        for job in new_jobs:
            by_sid[job.sid] = job
        self.save(by_sid.values())

    def get(
        self, batch: Optional[str] = None, sids: Optional[Iterable[str]] = None
    ) -> list[SubmittedJob]:
        """Jobs of a batch and/or matching SIDs, in submission order."""
        wanted = set(sids or [])
        jobs = [
            job
            for job in self.load()
            if (batch is None or job.batch == batch)
            and (not wanted or job.sid in wanted)
        ]
        return sorted(jobs, key=lambda job: job.submitted_at)

    def latest_batch(self) -> Optional[str]:
        jobs = self.load()
        if not jobs:
            return None
        return max(jobs, key=lambda job: job.submitted_at).batch

    def batches(self) -> list[JobBatchSummary]:
        grouped: dict[str, list[SubmittedJob]] = {}
        for job in self.load():
            grouped.setdefault(job.batch, []).append(job)
        summaries = [
            JobBatchSummary(
                name=name,
                jobs=len(jobs),
                instances=sorted({job.instance for job in jobs if job.instance}),
                first_submitted_at=min(job.submitted_at for job in jobs),
                last_submitted_at=max(job.submitted_at for job in jobs),
            )
            for name, jobs in grouped.items()
        ]
        return sorted(summaries, key=lambda summary: summary.last_submitted_at)
