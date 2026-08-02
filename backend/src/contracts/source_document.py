from __future__ import annotations

from datetime import datetime
from enum import Enum
import hashlib
import json
from typing import Any, Mapping

from pydantic import Field, model_validator

from src.contracts.research import StrictModel


class SourceType(str, Enum):
    OFFICIAL_PRIMARY = "OFFICIAL_PRIMARY"
    OFFICIAL_SECONDARY = "OFFICIAL_SECONDARY"
    OFFICIAL_LOCAL_GOV = "OFFICIAL_LOCAL_GOV"
    FINANCIAL_INSTITUTION = "FINANCIAL_INSTITUTION"
    MAJOR_NEWS = "MAJOR_NEWS"
    INDUSTRY_ASSOCIATION = "INDUSTRY_ASSOCIATION"
    OTHER = "OTHER"

class SourceTrustLevel(str, Enum):
    """Authority of a source, kept separate from the page's operational role."""
    OFFICIAL_TRUSTED = "OFFICIAL_TRUSTED"
    INSTITUTIONAL_TRUSTED = "INSTITUTIONAL_TRUSTED"
    VERIFIED_MEDIA = "VERIFIED_MEDIA"
    UNVERIFIED = "UNVERIFIED"


class SourceRole(str, Enum):
    CENTRAL_GOVERNMENT = "CENTRAL_GOVERNMENT"
    LOCAL_GOVERNMENT = "LOCAL_GOVERNMENT"
    OFFICIAL_DATA = "OFFICIAL_DATA"
    FINANCIAL_INSTITUTION = "FINANCIAL_INSTITUTION"
    OTHER = "OTHER"



class AccessStatus(str, Enum):
    OK = "OK"
    UNAVAILABLE = "UNAVAILABLE"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    UNSUPPORTED_CONTENT = "UNSUPPORTED_CONTENT"
    TOO_LARGE = "TOO_LARGE"
    BLOCKED_PRIVATE_NETWORK = "BLOCKED_PRIVATE_NETWORK"
    DOMAIN_NOT_ALLOWED = "DOMAIN_NOT_ALLOWED"
    EXTRACTION_FAILED = "EXTRACTION_FAILED"
    REDIRECT_LIMIT = "REDIRECT_LIMIT"
    REDIRECT_EXPIRED = "REDIRECT_EXPIRED"
    FINAL_DOMAIN_REJECTED = "FINAL_DOMAIN_REJECTED"


class DocumentPageType(str, Enum):
    """How a retrieved page participates in research processing."""

    UNKNOWN = "UNKNOWN"
    STRUCTURED_EVENT_LIST = "STRUCTURED_EVENT_LIST"
    EVENT_DETAIL_PAGE = "EVENT_DETAIL_PAGE"
    EVENT_ATTACHMENT = "EVENT_ATTACHMENT"
    LOCAL_NOTICE_LIST = "LOCAL_NOTICE_LIST"
    LOCAL_NOTICE_DETAIL = "LOCAL_NOTICE_DETAIL"
    NAVIGATION_ONLY = "NAVIGATION_ONLY"
    UNUSABLE_CONTENT = "UNUSABLE_CONTENT"


class StructuredEventRow(StrictModel):
    """A row-bounded piece of evidence found on a structured listing."""

    text: str = Field(min_length=1)
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)
    detail_urls: list[str] = Field(default_factory=list)


ROUTING_METADATA_VERSION = "routing_metadata.v1"


def source_snapshot_fingerprint(payload: Mapping[str, Any]) -> str:
    """Hash every field that can change extraction, routing, or source trust."""

    def enum_value(value: Any) -> Any:
        return value.value if isinstance(value, Enum) else value

    rows = []
    for row in payload.get("structured_event_rows") or []:
        row_data = row.model_dump(mode="json") if hasattr(row, "model_dump") else dict(row)
        rows.append({
            "text": row_data.get("text", ""),
            "start_offset": row_data.get("start_offset", 0),
            "end_offset": row_data.get("end_offset", 0),
            "detail_urls": sorted(set(row_data.get("detail_urls") or [])),
        })
    material = {
        "canonical_url": payload.get("canonical_url"),
        "original_url": payload.get("original_url"),
        "redirect_chain": payload.get("redirect_chain") or [],
        "body_sha256": payload.get("body_sha256"),
        "access_status": enum_value(payload.get("access_status")),
        "http_status": payload.get("http_status"),
        "content_type": payload.get("content_type"),
        "page_type": enum_value(payload.get("page_type", DocumentPageType.UNKNOWN)),
        "detail_urls": sorted(set(payload.get("detail_urls") or [])),
        "attachment_urls": sorted(set(payload.get("attachment_urls") or [])),
        "structured_event_rows": rows,
        "final_url_resolved": bool(payload.get("final_url_resolved", False)),
        "source_type": enum_value(payload.get("source_type", SourceType.OTHER)),
        "source_trust_level": enum_value(
            payload.get("source_trust_level", SourceTrustLevel.UNVERIFIED)
        ),
        "source_role": enum_value(payload.get("source_role", SourceRole.OTHER)),
        "classification_reasons": sorted(set(payload.get("classification_reasons") or [])),
        "security_flags": sorted(set(payload.get("security_flags") or [])),
        "retrieval_reason_code": payload.get("retrieval_reason_code"),
        "routing_metadata_version": payload.get(
            "routing_metadata_version", ROUTING_METADATA_VERSION
        ),
    }
    encoded = json.dumps(
        material, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class SourceDocument(StrictModel):
    source_id: str
    canonical_url: str
    publisher: str | None = None
    source_type: SourceType = SourceType.OTHER
    source_trust_level: SourceTrustLevel = SourceTrustLevel.UNVERIFIED
    source_role: SourceRole = SourceRole.OTHER
    published_at: datetime | None = None
    retrieved_at: datetime
    title: str = ""
    raw_content_uri: str | None = None
    raw_content_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    body_text: str = ""
    body_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    language: str = "ko"
    access_status: AccessStatus
    http_status: int | None = Field(default=None, ge=100, le=599)
    content_type: str | None = None
    http_metadata: dict[str, str] = Field(default_factory=dict)
    revision_id: str
    search_snippet: str | None = Field(default=None, description="Discovery metadata only.")
    parent_source_id: str | None = None
    attachment_urls: list[str] = Field(default_factory=list)
    detail_urls: list[str] = Field(default_factory=list)
    structured_event_rows: list[StructuredEventRow] = Field(default_factory=list)
    page_type: DocumentPageType = DocumentPageType.UNKNOWN
    classification_reasons: list[str] = Field(default_factory=list)
    security_flags: list[str] = Field(default_factory=list)
    original_url: str | None = None
    redirect_chain: list[str] = Field(default_factory=list)
    final_url_resolved: bool = False
    retrieval_reason_code: str | None = None
    snapshot_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    routing_metadata_version: str = ROUTING_METADATA_VERSION
    schema_version: str = "source_document.v1"

    @model_validator(mode="after")
    def successful_documents_have_content(self) -> "SourceDocument":
        if self.access_status == AccessStatus.OK and not self.body_text.strip():
            raise ValueError("OK source documents require non-empty body_text")
        self.snapshot_fingerprint = source_snapshot_fingerprint(self.__dict__)
        return self
