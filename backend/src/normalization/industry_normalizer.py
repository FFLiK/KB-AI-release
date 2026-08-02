from __future__ import annotations

from pathlib import Path
import yaml


class IndustryNormalizer:
    def __init__(self):
        with Path(__file__).parents[1].joinpath("registries/industry_mapping.v1.yaml").open(encoding="utf-8") as f:
            self.mapping=yaml.safe_load(f)["mappings"]
    def normalize(self, raw_values: list[str]) -> tuple[list[str],str]:
        codes=[]
        for raw in raw_values:
            for key, values in self.mapping.items():
                if key.lower() in raw.lower(): codes.extend(values)
        return sorted(set(codes)),"FNB_INDUSTRY_MAPPING_V1"
    def relevance(self, store_code: str, codes: list[str]) -> float:
        if not codes: return 1.0
        if store_code in codes: return 1.0
        if store_code.startswith("FNB") and "FNB" in codes: return 0.7
        return 0.0
