"""Validate service snapshot files against the project JSON schemas."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

from jsonschema import Draft202012Validator, FormatChecker

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"
EXAMPLE_DIR = SCHEMA_DIR / "examples"

SCHEMA_FILES = {
    "model_catalog": SCHEMA_DIR / "model_catalog.schema.json",
    "daily_recommendations": SCHEMA_DIR / "daily_recommendations.schema.json",
    "recent_changes": SCHEMA_DIR / "recent_changes.schema.json",
    "performance_summary": SCHEMA_DIR / "performance_summary.schema.json",
}

EXAMPLE_FILES = {
    "model_catalog": EXAMPLE_DIR / "model_catalog.example.json",
    "daily_recommendations": EXAMPLE_DIR / "daily_recommendations.example.json",
    "recent_changes": EXAMPLE_DIR / "recent_changes.example.json",
    "performance_summary": EXAMPLE_DIR / "performance_summary.example.json",
}


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def validate_payload(schema_name: str, payload: dict) -> None:
    schema = _load_json(SCHEMA_FILES[schema_name])
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    validator.validate(payload)


def validate_file(schema_name: str, data_path: Path) -> None:
    validate_payload(schema_name, _load_json(data_path))


def validate_examples(schema_names: Iterable[str] | None = None) -> list[str]:
    names = list(schema_names or SCHEMA_FILES.keys())
    validated = []
    for name in names:
        validate_file(name, EXAMPLE_FILES[name])
        validated.append(name)
    return validated


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate QuantService snapshot schemas.")
    parser.add_argument(
        "schema_name",
        nargs="?",
        choices=sorted(SCHEMA_FILES.keys()),
        help="Schema name to validate. If omitted, validate all example files.",
    )
    parser.add_argument(
        "data_path",
        nargs="?",
        type=Path,
        help="Path to a JSON file to validate against the selected schema.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.schema_name and args.data_path:
        validate_file(args.schema_name, args.data_path)
        print(f"Validated {args.data_path} against {args.schema_name}.")
        return 0

    if args.schema_name and not args.data_path:
        validate_file(args.schema_name, EXAMPLE_FILES[args.schema_name])
        print(f"Validated example for {args.schema_name}.")
        return 0

    validated = validate_examples()
    print("Validated examples:", ", ".join(validated))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
