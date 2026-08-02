from __future__ import annotations

import io
import re
import unicodedata

from bs4 import BeautifulSoup
from pypdf import PdfReader


def normalize_body_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def _content_root(soup: BeautifulSoup):
    candidates = []
    for selector in (
        "main", "article", "[role=main]", "#content", "#contents", ".content",
        ".contents", ".view-content", ".board-view", ".detail", ".notice-view",
    ):
        candidates.extend(soup.select(selector))
    candidates = list(dict.fromkeys(candidates))
    if candidates:
        return max(candidates, key=lambda node: len(node.get_text(" ", strip=True)))
    return soup.body or soup


def extract_html(raw: bytes, encoding: str | None = None) -> tuple[str, str, dict[str, object]]:
    soup = BeautifulSoup(raw, "html.parser", from_encoding=encoding)
    for node in soup([
        "script", "style", "iframe", "noscript", "svg", "form", "nav", "header",
        "footer", "aside", "template",
    ]):
        node.decompose()
    title = normalize_body_text(soup.title.get_text(" ", strip=True)) if soup.title else ""
    main = _content_root(soup)
    text = normalize_body_text(main.get_text("\n", strip=True))
    metadata: dict[str, object] = {}
    for key, names in {
        "publisher": ["og:site_name", "author"],
        "published_at": ["article:published_time", "date", "datePublished"],
    }.items():
        for name in names:
            tag = soup.find("meta", attrs={"property": name}) or soup.find(
                "meta", attrs={"name": name}
            )
            if tag and tag.get("content"):
                metadata[key] = str(tag["content"]).strip()
                break
    if "published_at" not in metadata:
        time_node = soup.find("time", attrs={"datetime": True})
        if time_node:
            metadata["published_at"] = str(time_node.get("datetime") or "").strip()
    # Preserve detail links for bounded list-to-detail traversal.
    attachments: list[str] = []
    detail_urls: list[str] = []
    detail_pattern = re.compile(r"(?:view\.do|detail|board|notice|event|festival)", re.IGNORECASE)
    for anchor in main.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        if not href or href.casefold().startswith(("javascript:", "#")):
            continue
        if re.search(r"\.(?:pdf|hwp|hwpx|txt)(?:$|[?#])", href, re.IGNORECASE):
            attachments.append(href)
        elif detail_pattern.search(href):
            detail_urls.append(href)
    if attachments:
        metadata["attachment_urls"] = list(dict.fromkeys(attachments))[:20]
    if detail_urls:
        metadata["detail_urls"] = list(dict.fromkeys(detail_urls))[:50]
    date_pattern = re.compile(r"(?:20\d{2}|\d{1,2}[./-]\d{1,2})", re.IGNORECASE)
    rows: list[dict[str, object]] = []
    for node in main.select("tr, li, [data-event], .event, .event-card, .event-item, .calendar-item"):
        row_text = normalize_body_text(node.get_text("\n", strip=True))
        if len(row_text) < 20 or not date_pattern.search(row_text):
            continue
        row_links = [
            str(anchor.get("href") or "").strip()
            for anchor in node.find_all("a", href=True)
            if detail_pattern.search(str(anchor.get("href") or ""))
        ]
        rows.append({"text": row_text, "detail_urls": list(dict.fromkeys(row_links))})
    if rows:
        metadata["structured_event_rows"] = rows[:50]
    return title, text, metadata


def extract_pdf(raw: bytes) -> tuple[str, str, dict[str, str]]:
    reader = PdfReader(io.BytesIO(raw))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            return "", "", {"pdf_status": "ENCRYPTED"}
    pages = [page.extract_text(extraction_mode="layout") or "" for page in reader.pages]
    text = normalize_body_text("\n".join(pages))
    meta = reader.metadata or {}
    title = normalize_body_text(str(meta.get("/Title", "")))
    return title, text, {
        "publisher": str(meta.get("/Author", "")),
        "page_count": str(len(reader.pages)),
        "pdf_status": "EXTRACTED" if text else "NO_TEXT_LAYER",
    }
