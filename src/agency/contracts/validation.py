from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, cast

from jsonschema import Draft202012Validator, ValidationError
from referencing import Registry, Resource

ContractName = Literal[
    "provenance",
    "signal-result",
    "evidence-pack",
    "selection-report",
    "data-source-health",
]

_SCHEMA_FILES: dict[ContractName, str] = {
    "provenance": "provenance.schema.json",
    "signal-result": "signal-result.schema.json",
    "evidence-pack": "evidence-pack.schema.json",
    "selection-report": "selection-report.schema.json",
    "data-source-health": "data-source-health.schema.json",
}


class ContractValidationError(ValueError):
    """Raised when a payload fails a named contract schema."""


def validate_contract(
    contract: ContractName,
    payload: object,
    *,
    schema_dir: Path | None = None,
) -> None:
    """Validate a payload against a named JSON Schema contract."""
    validator = _validator_for(contract, _resolve_schema_dir(schema_dir))
    try:
        validator.validate(payload)
    except ValidationError as exc:
        path = ".".join(str(part) for part in exc.path)
        location = f" at {path}" if path else ""
        msg = f"{contract} contract validation failed{location}: {exc.message}"
        raise ContractValidationError(msg) from exc


def is_valid_contract(
    contract: ContractName,
    payload: object,
    *,
    schema_dir: Path | None = None,
) -> bool:
    """Return whether a payload satisfies a named contract."""
    try:
        validate_contract(contract, payload, schema_dir=schema_dir)
    except ContractValidationError:
        return False
    return True


def load_contract_schema(
    contract: ContractName,
    *,
    schema_dir: Path | None = None,
) -> dict[str, Any]:
    """Load a contract schema by name."""
    schemas = _load_schemas(_resolve_schema_dir(schema_dir))
    return schemas[_SCHEMA_FILES[contract]]


def _validator_for(contract: ContractName, schema_dir: Path) -> Draft202012Validator:
    schemas = _load_schemas(schema_dir)
    resources = [
        (str(schema["$id"]), Resource.from_contents(schema)) for schema in schemas.values()
    ]
    registry = Registry().with_resources(resources)
    return Draft202012Validator(schemas[_SCHEMA_FILES[contract]], registry=registry)


@lru_cache(maxsize=4)
def _load_schemas(schema_dir: Path) -> dict[str, dict[str, Any]]:
    schemas: dict[str, dict[str, Any]] = {}
    for filename in _SCHEMA_FILES.values():
        schema = json.loads((schema_dir / filename).read_text(encoding="utf-8"))
        schemas[filename] = cast(dict[str, Any], schema)
    return schemas


def _resolve_schema_dir(schema_dir: Path | None) -> Path:
    if schema_dir is not None:
        return schema_dir
    return Path(__file__).resolve().parents[3] / "schemas"
