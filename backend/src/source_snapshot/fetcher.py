from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from urllib.parse import urljoin, urlsplit

import httpx

from src.config.settings import Settings
from src.contracts.source_document import (
    AccessStatus, SourceDocument, StructuredEventRow, source_snapshot_fingerprint,
)
from src.providers.base import DocumentFetcher, SearchHit
from src.source_snapshot.security import assert_public_url, detect_prompt_injection
from src.source_snapshot.source_policy import (
    classify_source, classify_source_role, classify_source_trust, url_matches_allowed_domains,
)
from src.source_snapshot.text_extractor import extract_html, extract_pdf
from src.source_snapshot.url_utils import canonicalize_url


class HttpDocumentFetcher(DocumentFetcher):
    ALLOWED_TYPES = {
        "text/html", "application/xhtml+xml", "application/pdf", "text/plain",
        "application/vnd.hancom.hwp", "application/x-hwp", "application/haansofthwp",
        "application/vnd.hancom.hwpx", "application/zip",
    }
    GROUNDING_REDIRECT_DOMAINS = {"vertexaisearch.cloud.google.com"}
    SAFE_HTTP_HEADERS = ("etag", "last-modified", "cache-control", "content-language")

    def __init__(self, settings: Settings | None = None, transport: httpx.BaseTransport | None = None):
        self.settings = settings or Settings()
        self.transport = transport

    @staticmethod
    def _revision_id(source_id: str, snapshot_fingerprint: str) -> str:
        material = f"{source_id}|{snapshot_fingerprint}".encode()
        return "REV-" + hashlib.sha256(material).hexdigest()[:20].upper()

    def _failure(
        self,
        hit: SearchHit,
        url: str,
        status: AccessStatus,
        http_status: int | None = None,
        content_type: str | None = None,
        http_metadata: dict[str, str] | None = None,
        redirect_chain: list[str] | None = None,
        reason_code: str | None = None,
    ) -> SourceDocument:
        source_id = "SRC-" + hashlib.sha256(url.encode()).hexdigest()[:20].upper()
        body_hash = hashlib.sha256(b"").hexdigest()
        chain = list(redirect_chain or [])
        values = dict(
            source_id=source_id,
            canonical_url=url,
            publisher=hit.publisher,
            source_type=classify_source(url),
            source_trust_level=classify_source_trust(url),
            source_role=classify_source_role(url),
            published_at=hit.published_at,
            retrieved_at=datetime.now(UTC),
            title=hit.title,
            body_sha256=body_hash,
            access_status=status,
            http_status=http_status,
            content_type=content_type,
            http_metadata=http_metadata or {},
            revision_id="PENDING",
            search_snippet=hit.snippet,
            original_url=canonicalize_url(hit.url),
            redirect_chain=chain,
            final_url_resolved=bool(chain),
            retrieval_reason_code=reason_code or str(status),
        )
        fingerprint = source_snapshot_fingerprint(values)
        values["revision_id"] = self._revision_id(source_id, fingerprint)
        values["snapshot_fingerprint"] = fingerprint
        return SourceDocument(**values)

    @classmethod
    def _is_grounding_redirect(cls, url: str) -> bool:
        return (urlsplit(url).hostname or "").lower() in cls.GROUNDING_REDIRECT_DOMAINS

    @classmethod
    def _http_metadata(cls, response: httpx.Response) -> dict[str, str]:
        return {
            name: response.headers[name]
            for name in cls.SAFE_HTTP_HEADERS
            if name in response.headers
        }

    def fetch(
        self, hit: SearchHit, *, timeout_reason_code: str = "DOCUMENT_FETCH_TIMEOUT"
    ) -> SourceDocument:
        url = canonicalize_url(hit.url)
        if hit.allowed_domains and not (
            url_matches_allowed_domains(url, hit.allowed_domains) or self._is_grounding_redirect(url)
        ):
            return self._failure(hit, url, AccessStatus.DOMAIN_NOT_ALLOWED)
        if self.transport is None:
            try:
                assert_public_url(url)
            except ValueError as exc:
                status = (
                    AccessStatus.BLOCKED_PRIVATE_NETWORK
                    if "PRIVATE" in str(exc)
                    else AccessStatus.UNAVAILABLE
                )
                return self._failure(hit, url, status)
        headers = {
            "User-Agent": "KB-AI-ResearchBot/1.0",
            "Accept": "text/html,application/pdf,text/plain;q=0.8",
        }
        current = url
        redirect_chain: list[str] = []
        raw = b""
        response: httpx.Response | None = None
        content_type = ""
        response_encoding = None
        metadata: dict[str, str] = {}
        try:
            with httpx.Client(
                timeout=self.settings.http_timeout_seconds,
                transport=self.transport,
                follow_redirects=False,
            ) as client:
                while True:
                    with client.stream("GET", current, headers=headers) as response:
                        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                        metadata = self._http_metadata(response)
                        if response.is_redirect:
                            location = response.headers.get("location")
                            if not location:
                                return self._failure(
                                    hit, current, AccessStatus.UNAVAILABLE, response.status_code,
                                    content_type, metadata, redirect_chain, "REDIRECT_LOCATION_MISSING",
                                )
                            if len(redirect_chain) >= self.settings.max_redirects:
                                return self._failure(
                                    hit, current, AccessStatus.REDIRECT_LIMIT, response.status_code,
                                    content_type, metadata, redirect_chain, "REDIRECT_LIMIT",
                                )
                            target = canonicalize_url(str(response.url.join(location)))
                            if hit.allowed_domains and not url_matches_allowed_domains(target, hit.allowed_domains):
                                return self._failure(
                                    hit, target, AccessStatus.DOMAIN_NOT_ALLOWED,
                                    response.status_code, content_type, metadata,
                                    [*redirect_chain, target], "FINAL_DOMAIN_REJECTED",
                                )
                            if self.transport is None:
                                try:
                                    assert_public_url(target)
                                except ValueError as exc:
                                    status = (
                                        AccessStatus.BLOCKED_PRIVATE_NETWORK
                                        if "PRIVATE" in str(exc)
                                        else AccessStatus.UNAVAILABLE
                                    )
                                    return self._failure(
                                        hit, target, status, response.status_code, content_type,
                                        metadata, [*redirect_chain, target], str(status),
                                    )
                            redirect_chain.append(target)
                            current = target
                            continue
                        if hit.allowed_domains and not url_matches_allowed_domains(current, hit.allowed_domains):
                            return self._failure(
                                hit, current, AccessStatus.DOMAIN_NOT_ALLOWED,
                                response.status_code, content_type, metadata, redirect_chain,
                                "FINAL_DOMAIN_REJECTED",
                            )
                        if response.status_code in {401, 403}:
                            return self._failure(
                                hit, current, AccessStatus.LOGIN_REQUIRED, response.status_code,
                                content_type, metadata, redirect_chain,
                            )
                        if response.status_code in {404, 410} and self._is_grounding_redirect(url):
                            return self._failure(
                                hit, current, AccessStatus.REDIRECT_EXPIRED, response.status_code,
                                content_type, metadata, redirect_chain, "REDIRECT_EXPIRED",
                            )
                        if response.status_code >= 400:
                            return self._failure(
                                hit, current, AccessStatus.UNAVAILABLE, response.status_code,
                                content_type, metadata, redirect_chain,
                            )
                        is_hwp_attachment = urlsplit(current).path.lower().endswith((".hwp", ".hwpx"))
                        if content_type not in self.ALLOWED_TYPES and not is_hwp_attachment:
                            return self._failure(
                                hit, current, AccessStatus.UNSUPPORTED_CONTENT,
                                response.status_code, content_type, metadata, redirect_chain,
                            )
                        length = int(response.headers.get("content-length", "0") or 0)
                        if length > self.settings.max_document_bytes:
                            return self._failure(
                                hit, current, AccessStatus.TOO_LARGE, response.status_code,
                                content_type, metadata, redirect_chain,
                            )
                        chunks: list[bytes] = []
                        received = 0
                        for chunk in response.iter_bytes():
                            received += len(chunk)
                            if received > self.settings.max_document_bytes:
                                return self._failure(
                                    hit, current, AccessStatus.TOO_LARGE,
                                    response.status_code, content_type, metadata, redirect_chain,
                                )
                            chunks.append(chunk)
                        raw = b"".join(chunks)
                        response_encoding = response.encoding
                    break
            if content_type == "application/pdf":
                title, body, extracted_metadata = extract_pdf(raw)
            elif content_type in {"text/html", "application/xhtml+xml"}:
                title, body, extracted_metadata = extract_html(raw, response_encoding)
            elif content_type == "text/plain" and not urlsplit(current).path.lower().endswith((".hwp", ".hwpx")):
                title = hit.title
                body = raw.decode(response_encoding or "utf-8", errors="replace")
                extracted_metadata = {}
            else:
                title = hit.title
                body = "HWP_BINARY_ATTACHMENT_RETRIEVED"
                extracted_metadata = {"hwp_status": "RETRIEVED_NOT_EXTRACTED"}
            if not body.strip():
                return self._failure(
                    hit, current, AccessStatus.EXTRACTION_FAILED,
                    response.status_code if response else None,
                    content_type, metadata, redirect_chain, "EMPTY_EXTRACTION",
                )
        except httpx.TimeoutException:
            return self._failure(
                hit, current, AccessStatus.UNAVAILABLE,
                redirect_chain=redirect_chain, reason_code=timeout_reason_code,
            )
        except (httpx.HTTPError, ValueError, OSError):
            return self._failure(
                hit, current, AccessStatus.UNAVAILABLE,
                redirect_chain=redirect_chain, reason_code="FETCH_FAILED",
            )
        final_url = canonicalize_url(current)
        attachment_urls: list[str] = []
        detail_urls: list[str] = []
        for field, target in (("attachment_urls", attachment_urls), ("detail_urls", detail_urls)):
            for value in extracted_metadata.get(field, []):
                if not isinstance(value, str):
                    continue
                try:
                    target.append(canonicalize_url(urljoin(final_url, value)))
                except ValueError:
                    continue
        structured_rows: list[StructuredEventRow] = []
        for raw_row in extracted_metadata.get("structured_event_rows", []):
            if not isinstance(raw_row, dict) or not isinstance(raw_row.get("text"), str):
                continue
            row_text = raw_row["text"]
            start_offset = body.find(row_text)
            if start_offset < 0:
                continue
            row_links = raw_row.get("detail_urls", [])
            if not isinstance(row_links, list):
                row_links = []
            structured_rows.append(StructuredEventRow(
                text=row_text,
                start_offset=start_offset,
                end_offset=start_offset + len(row_text),
                detail_urls=[value for value in row_links if isinstance(value, str)],
            ))
        body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
        raw_hash = hashlib.sha256(raw).hexdigest()
        source_id = "SRC-" + hashlib.sha256(final_url.encode()).hexdigest()[:20].upper()
        assert response is not None
        snapshot_values = {
            "canonical_url": final_url,
            "original_url": url,
            "redirect_chain": redirect_chain,
            "body_sha256": body_hash,
            "access_status": AccessStatus.OK,
            "http_status": response.status_code,
            "content_type": response.headers.get("content-type"),
            "detail_urls": list(dict.fromkeys(detail_urls)),
            "attachment_urls": list(dict.fromkeys(attachment_urls)),
            "structured_event_rows": structured_rows,
            "final_url_resolved": final_url != url,
            "source_type": classify_source(
                final_url, page_context=f"{title}\n{body}", publisher=hit.publisher
            ),
            "source_trust_level": classify_source_trust(final_url),
            "source_role": classify_source_role(final_url),
            "classification_reasons": [],
            "security_flags": detect_prompt_injection(body),
            "retrieval_reason_code": "RETRIEVED",
        }
        fingerprint = source_snapshot_fingerprint(snapshot_values)
        revision_id = self._revision_id(source_id, fingerprint)
        snapshot_dir = self.settings.snapshot_dir / source_id
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        suffix = ".pdf" if content_type == "application/pdf" else ".html"
        raw_path = snapshot_dir / f"{revision_id}{suffix}"
        if not raw_path.exists():
            raw_path.write_bytes(raw)
        published = hit.published_at
        if not published and extracted_metadata.get("published_at"):
            try:
                published = datetime.fromisoformat(extracted_metadata["published_at"].replace("Z", "+00:00"))
            except ValueError:
                published = None
        return SourceDocument(
            source_id=source_id,
            canonical_url=final_url,
            publisher=hit.publisher or extracted_metadata.get("publisher"),
            source_type=snapshot_values["source_type"],
            published_at=published,
            source_trust_level=snapshot_values["source_trust_level"],
            source_role=snapshot_values["source_role"],
            retrieved_at=datetime.now(UTC),
            title=title or hit.title,
            raw_content_uri=str(raw_path),
            raw_content_sha256=raw_hash,
            body_text=body,
            body_sha256=body_hash,
            access_status=AccessStatus.OK,
            http_status=response.status_code,
            content_type=response.headers.get("content-type"),
            http_metadata=self._http_metadata(response),
            revision_id=revision_id,
            search_snippet=hit.snippet,
            security_flags=snapshot_values["security_flags"],
            attachment_urls=list(dict.fromkeys(attachment_urls)),
            detail_urls=list(dict.fromkeys(detail_urls)),
            structured_event_rows=structured_rows,
            original_url=url,
            redirect_chain=redirect_chain,
            final_url_resolved=final_url != url,
            retrieval_reason_code="RETRIEVED",
            snapshot_fingerprint=fingerprint,
        )

    def fetch_with_attachments(
        self,
        hit: SearchHit,
        *,
        parent: SourceDocument | None = None,
        max_attachments: int = 5,
    ) -> list[SourceDocument]:
        """Fetch a detail document and its attachment source snapshots."""
        detail = parent or self.fetch(hit)
        documents = [detail]
        if detail.access_status != AccessStatus.OK:
            return documents
        allowed_domains = hit.allowed_domains or [(urlsplit(detail.canonical_url).hostname or "")]
        for attachment_url in detail.attachment_urls[:max_attachments]:
            attachment = self.fetch(
                SearchHit(
                    url=attachment_url, rank=hit.rank, title=detail.title,
                    publisher=detail.publisher, allowed_domains=allowed_domains,
                    discovery_query=hit.discovery_query,
                ),
                timeout_reason_code="ATTACHMENT_FETCH_TIMEOUT",
            ).model_copy(update={"parent_source_id": detail.source_id})
            documents.append(attachment)
        return documents

    def fetch_with_detail_pages(self, hit: SearchHit, *, parent: SourceDocument) -> list[SourceDocument]:
        """Traverse one official list page to bounded detail pages and attachments."""
        if parent.access_status != AccessStatus.OK:
            return []
        limit = self.settings.max_local_child_pages
        allowed_domains = hit.allowed_domains or [(urlsplit(parent.canonical_url).hostname or "")]
        documents: list[SourceDocument] = []
        seen_urls: set[str] = set()
        for detail_url in parent.detail_urls:
            if len(documents) >= max(0, limit):
                break
            if detail_url in seen_urls:
                continue
            seen_urls.add(detail_url)
            detail = self.fetch(SearchHit(
                url=detail_url,
                rank=hit.rank,
                title=parent.title,
                publisher=parent.publisher,
                allowed_domains=allowed_domains,
                discovery_query=hit.discovery_query,
            )).model_copy(update={"parent_source_id": parent.source_id})
            documents.append(detail)
            if detail.access_status == AccessStatus.OK:
                documents.extend(self.fetch_with_attachments(hit, parent=detail, max_attachments=3)[1:])
        return documents
