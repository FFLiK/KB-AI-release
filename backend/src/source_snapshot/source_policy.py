from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from src.contracts.source_document import SourceRole, SourceTrustLevel, SourceType

PRIMARY_DOMAINS = {
    "bok.or.kr", "kosis.kr", "customs.go.kr", "moef.go.kr", "mafra.go.kr",
    "motie.go.kr", "mfds.go.kr", "ftc.go.kr", "gov.kr", "bizinfo.go.kr",
    "semas.or.kr", "data.go.kr",
}
LOCAL_MARKERS = (
    "seoul.go.kr", "busan.go.kr", "daegu.go.kr", "incheon.go.kr",
    "gwangju.go.kr", "daejeon.go.kr", "ulsan.go.kr", "sejong.go.kr", "gg.go.kr",
    "gangnam.go.kr", "seocho.go.kr", "songpa.go.kr",
)
FINANCIAL_DOMAINS = {"kbstar.com", "kfcc.co.kr", "kodit.co.kr", "koreg.or.kr"}
MAJOR_NEWS_DOMAINS = {
    "yna.co.kr", "kbs.co.kr", "imbc.com", "sbs.co.kr", "hani.co.kr",
    "donga.com", "joongang.co.kr", "chosun.com",
}


def domain_matches(host: str, domain: str) -> bool:
    normalized_host = host.rstrip(".").lower()
    normalized_domain = domain.rstrip(".").lower()
    return normalized_host == normalized_domain or normalized_host.endswith("." + normalized_domain)


def url_matches_allowed_domains(url: str, allowed_domains: list[str]) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return bool(host) and any(domain_matches(host, domain) for domain in allowed_domains)


def _looks_like_local_context(page_context: str | None, publisher: str | None) -> bool:
    context = " ".join(value or "" for value in (page_context, publisher)).casefold()
    return any(marker in context for marker in (
        "구청", "시청", "군청", "도청", "주민센터", "district office",
        "municipal", "metropolitan government", "local government",
    ))


def classify_source(
    url: str, *, page_context: str | None = None, publisher: str | None = None
) -> SourceType:
    authority = source_authority(url)
    if authority:
        return SourceType(authority["source_type"])
    host = (urlsplit(url).hostname or "").lower()
    if any(domain_matches(host, domain) for domain in LOCAL_MARKERS):
        return SourceType.OFFICIAL_LOCAL_GOV
    if any(domain_matches(host, domain) for domain in PRIMARY_DOMAINS):
        return SourceType.OFFICIAL_PRIMARY
    if host.endswith(".go.kr") and _looks_like_local_context(page_context, publisher):
        return SourceType.OFFICIAL_LOCAL_GOV
    if host.endswith(".go.kr"):
        return SourceType.OFFICIAL_PRIMARY
    if any(domain_matches(host, domain) for domain in FINANCIAL_DOMAINS):
        return SourceType.FINANCIAL_INSTITUTION
    if any(domain_matches(host, domain) for domain in MAJOR_NEWS_DOMAINS):
        return SourceType.MAJOR_NEWS
    return SourceType.OTHER


def classify_source_trust(url: str) -> SourceTrustLevel:
    """Classify authority using parsed-hostname boundary matching only."""
    host = (urlsplit(url).hostname or "").rstrip(".").lower()
    authority = source_authority(url)
    if authority:
        return SourceTrustLevel(authority["trust_level"])
    if host == "go.kr" or host.endswith(".go.kr") or any(
        domain_matches(host, domain) for domain in PRIMARY_DOMAINS
    ):
        return SourceTrustLevel.OFFICIAL_TRUSTED
    if any(domain_matches(host, domain) for domain in FINANCIAL_DOMAINS):
        return SourceTrustLevel.INSTITUTIONAL_TRUSTED
    if any(domain_matches(host, domain) for domain in MAJOR_NEWS_DOMAINS):
        return SourceTrustLevel.VERIFIED_MEDIA
    return SourceTrustLevel.UNVERIFIED


def classify_source_role(url: str) -> SourceRole:
    host = (urlsplit(url).hostname or "").rstrip(".").lower()
    authority = source_authority(url)
    if authority:
        return SourceRole(authority["source_role"])
    if any(domain_matches(host, domain) for domain in LOCAL_MARKERS):
        return SourceRole.LOCAL_GOVERNMENT
    if host == "data.go.kr" or domain_matches(host, "kosis.kr"):
        return SourceRole.OFFICIAL_DATA
    if host == "go.kr" or host.endswith(".go.kr"):
        # District hosts need not be enumerated in LOCAL_MARKERS.
        return SourceRole.LOCAL_GOVERNMENT
    if any(domain_matches(host, domain) for domain in FINANCIAL_DOMAINS):
        return SourceRole.FINANCIAL_INSTITUTION
    if any(domain_matches(host, domain) for domain in PRIMARY_DOMAINS):
        return SourceRole.CENTRAL_GOVERNMENT
    return SourceRole.OTHER


@lru_cache(maxsize=1)
def source_authority_registry() -> tuple[str, dict[str, dict[str, str]]]:
    path = Path(__file__).parents[1] / "registries" / "source_authorities.v1.yaml"
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)
    return payload["version"], payload["authorities"]


def source_authority(url: str) -> dict[str, str] | None:
    host = (urlsplit(url).hostname or "").rstrip(".").lower()
    _, authorities = source_authority_registry()
    for domain, authority in authorities.items():
        if domain_matches(host, domain):
            return authority
    return None
