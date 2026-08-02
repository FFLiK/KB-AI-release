from __future__ import annotations

from pathlib import Path
import hashlib
import unicodedata
import yaml


def normalize_text(value: str | None) -> str | None:
    if value is None: return None
    return " ".join(unicodedata.normalize("NFKC",value).split())


class OrganizationNormalizer:
    def __init__(self):
        with Path(__file__).parents[1].joinpath("registries/organization_aliases.v1.yaml").open(encoding="utf-8") as f:
            self.aliases=yaml.safe_load(f)["aliases"]
    def normalize(self, raw: str | None) -> tuple[str | None,str]:
        text=normalize_text(raw)
        if not text: return None,"ORGANIZATION_EMPTY_V1"
        if text in self.aliases: return self.aliases[text],"ORGANIZATION_ALIAS_V1"
        if text.casefold() in {
            "bank of korea", "the bank of korea", "b.o.k.", "bok",
            "monetary policy board of the bank of korea", "한국은행", "한국 은행",
        }:
            return "ORG-BOK", "ORGANIZATION_BANK_OF_KOREA_ALIAS_V1"

        return "ORG-"+hashlib.sha256(text.encode()).hexdigest()[:12].upper(),"ORGANIZATION_STABLE_HASH_V1"
