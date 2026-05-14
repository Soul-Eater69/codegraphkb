"""Dataclasses and service exceptions for the product API layer."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ProjectStatus = Literal["created", "importing", "indexing", "ready", "failed", "deleted"]
SourceType = Literal["github_url", "zip_upload", "local_path"]
JobStatus = Literal["queued", "running", "succeeded", "failed"]


@dataclass
class Project:
    id: str
    name: str
    source_type: SourceType
    source_ref: str
    workspace_path: str
    status: ProjectStatus
    error_message: str
    created_at: str
    updated_at: str
    last_indexed_at: str | None = None


@dataclass
class IndexJob:
    id: str
    project_id: str
    status: JobStatus
    progress_message: str
    error_message: str
    files_scanned: int
    files_indexed: int
    symbols: int
    edges: int
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None


class ProductError(Exception):
    """Base class for product-layer errors."""


class ProjectNotFoundError(ProductError):
    """Raised when a project id has no metadata row."""


class JobNotFoundError(ProductError):
    """Raised when an index job id has no metadata row."""


class InvalidRequestError(ProductError, ValueError):
    """Raised when product-layer input fails validation."""


class UploadTooLargeError(InvalidRequestError):
    """Raised when an uploaded archive exceeds the configured size limit."""

