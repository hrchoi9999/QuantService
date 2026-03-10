import json
from pathlib import Path

import pytest
from jsonschema.exceptions import ValidationError

from service_platform.publishers.writers.validate_schema import (
    EXAMPLE_FILES,
    validate_examples,
    validate_file,
)


def test_validate_all_examples() -> None:
    assert validate_examples() == [
        "model_catalog",
        "daily_recommendations",
        "recent_changes",
        "performance_summary",
    ]


@pytest.mark.parametrize(
    ("schema_name", "example_path"),
    [
        ("model_catalog", EXAMPLE_FILES["model_catalog"]),
        ("daily_recommendations", EXAMPLE_FILES["daily_recommendations"]),
        ("recent_changes", EXAMPLE_FILES["recent_changes"]),
        ("performance_summary", EXAMPLE_FILES["performance_summary"]),
    ],
)
def test_each_example_file_validates(schema_name: str, example_path: Path) -> None:
    validate_file(schema_name, example_path)


def test_invalid_change_type_fails_validation(tmp_path: Path) -> None:
    payload = json.loads(EXAMPLE_FILES["daily_recommendations"].read_text(encoding="utf-8-sig"))
    payload["models"][0]["top_picks"][0]["change_type"] = "sideways"
    invalid_path = tmp_path / "invalid_daily.json"
    invalid_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValidationError):
        validate_file("daily_recommendations", invalid_path)
