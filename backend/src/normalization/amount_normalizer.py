from __future__ import annotations

import re
from decimal import Decimal


UNITS={"\uc6d0":Decimal("1"),"\ub9cc\uc6d0":Decimal("10000"),"\ubc31\ub9cc\uc6d0":Decimal("1000000"),"\uc5b5\uc6d0":Decimal("100000000")}


def normalize_amount(raw: str) -> tuple[Decimal, str, str]:
    compact=raw.replace(",","").replace(" ","")
    match=re.search(r"(-?\d+(?:\.\d+)?)\s*(\uc5b5\uc6d0|\ubc31\ub9cc\uc6d0|\ub9cc\uc6d0|\uc6d0)",compact)
    if not match: raise ValueError(f"unparseable amount: {raw}")
    value=Decimal(match.group(1))*UNITS[match.group(2)]
    return value.quantize(Decimal("1")),"KRW","KO_KRW_UNIT_V1"


def normalize_percentage(raw: str) -> tuple[Decimal, str, str]:
    match=re.search(r"(-?\d+(?:\.\d+)?)\s*(%p|%\ud3ec\uc778\ud2b8|%)",raw)
    if not match: raise ValueError(f"unparseable percentage: {raw}")
    unit="PERCENTAGE_POINT" if match.group(2) in {"%p","%\ud3ec\uc778\ud2b8"} else "RATIO"
    return Decimal(match.group(1))/Decimal("100"),unit,"KO_PERCENT_V1"
