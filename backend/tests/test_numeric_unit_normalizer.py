from decimal import Decimal

import pytest

from src.normalization.numeric_unit_normalizer import normalize_numeric_unit
from src.source_snapshot.source_policy import classify_source_trust


def test_numeric_unit_normalizer_canonicalizes_percent_and_currency() -> None:
    assert normalize_numeric_unit("2.75%").normalized_value == Decimal("2.75")
    assert normalize_numeric_unit("2.75", "%").normalized_unit == "PERCENT"
    assert normalize_numeric_unit("0.25 %P").normalized_unit == "PERCENTAGE_POINT"
    assert normalize_numeric_unit("3\uc5b5\uc6d0").normalized_value == Decimal("300000000")
    assert normalize_numeric_unit("300,000,000\uc6d0").normalized_unit == "KRW"


def test_numeric_unit_normalizer_rejects_ambiguous_values() -> None:
    with pytest.raises(ValueError):
        normalize_numeric_unit("2.75")


def test_government_domain_trust_uses_hostname_boundaries() -> None:
    assert str(classify_source_trust("https://www.gangnam.go.kr/notice")).endswith("OFFICIAL_TRUSTED")
    assert str(classify_source_trust("https://gangnam.go.kr.example.com/notice")).endswith("UNVERIFIED")
