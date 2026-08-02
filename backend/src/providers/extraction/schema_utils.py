from __future__ import annotations

from copy import deepcopy
from typing import Any


ATTRIBUTE_KEYS = (
    "business_type", "closure_scope", "platform_name", "product_name",
    "official_indicator_id", "official_previous_value", "official_new_value",
    "official_value_unit",
)
_METADATA_KEYS = {"default", "examples"}
_UNSUPPORTED_COMPOSITION_KEYS = {
    "allOf", "not", "dependentRequired", "dependentSchemas", "if", "then", "else",
}


def _normalize_any_of(node: dict[str, Any]) -> None:
    variants = node.get("anyOf")
    if not isinstance(variants, list):
        return
    has_numeric = any(
        isinstance(item, dict) and item.get("type") in {"number", "integer"}
        for item in variants
    )
    if not has_numeric:
        return
    # Pydantic emits Decimal as number OR a decimal-pattern string. The overlapping
    # string branch is unnecessary for model output and has triggered provider schema
    # rejection in the policy contract. JSON numbers still validate as Decimal.
    node["anyOf"] = [
        item for item in variants
        if not (
            isinstance(item, dict)
            and item.get("type") == "string"
            and "pattern" in item
        )
    ]


def to_strict_provider_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Return the minimal Structured Outputs subset used by the Responses API."""
    result = deepcopy(schema)
    attributes = result.get("properties", {}).get("attributes")
    if attributes is not None:
        value_schema = {
            "anyOf": [
                {"type": "string"},
                {"type": "number"},
                {"type": "boolean"},
                {"type": "array", "items": {"type": "string"}},
                {"type": "null"},
            ]
        }
        result["properties"]["attributes"] = {
            "type": "object",
            "additionalProperties": False,
            "properties": {key: deepcopy(value_schema) for key in ATTRIBUTE_KEYS},
            "required": list(ATTRIBUTE_KEYS),
        }

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            for key in _METADATA_KEYS | _UNSUPPORTED_COMPOSITION_KEYS:
                node.pop(key, None)
            _normalize_any_of(node)
            properties = node.get("properties")
            if isinstance(properties, dict):
                node["type"] = "object"
                node["additionalProperties"] = False
                node["required"] = list(properties)
            for value in list(node.values()):
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(result)
    return result


def validate_strict_provider_schema(schema: dict[str, Any]) -> None:
    """Fail locally before a provider call when the strict-object contract drifts."""
    if schema.get("type") != "object" or "anyOf" in schema:
        raise ValueError("Structured Outputs root must be an object")

    def visit(node: Any, path: str) -> None:
        if isinstance(node, dict):
            forbidden = (_METADATA_KEYS | _UNSUPPORTED_COMPOSITION_KEYS).intersection(node)
            if forbidden:
                raise ValueError(f"Unsupported schema keys at {path}: {sorted(forbidden)}")
            properties = node.get("properties")
            if isinstance(properties, dict):
                if node.get("additionalProperties") is not False:
                    raise ValueError(f"additionalProperties must be false at {path}")
                if node.get("required") != list(properties):
                    raise ValueError(f"Every property must be required at {path}")
            for key, value in node.items():
                visit(value, f"{path}/{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                visit(value, f"{path}/{index}")

    visit(schema, "#")


def strict_array_response_schema(
    item_schema: dict[str, Any],
    collection_name: str,
) -> dict[str, Any]:
    """Hoist Pydantic definitions so absolute #/$defs references remain valid."""
    item = to_strict_provider_schema(item_schema)
    definitions = item.pop("$defs", {})
    wrapper: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            collection_name: {"type": "array", "items": item},
        },
        "required": [collection_name],
    }
    if definitions:
        wrapper["$defs"] = definitions
    validate_strict_provider_schema(wrapper)
    return wrapper
