import json
from pathlib import Path

import pytest

from service_platform.publishers.publish_manager import publish_daily
from service_platform.shared.config import get_settings
from service_platform.shared.constants import MANIFEST_FILENAME, SNAPSHOT_FILENAMES

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "adapters" / "s2"


@pytest.fixture()
def publish_settings(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("PUBLISH_ROOT_DIR", str(tmp_path / "publish_output"))
    monkeypatch.setenv("S2_HOLDINGS_CSV", str(FIXTURE_DIR / "holdings.csv"))
    monkeypatch.setenv("S2_SNAPSHOT_CSV", str(FIXTURE_DIR / "snapshot.csv"))
    monkeypatch.setenv("S2_SUMMARY_CSV", str(FIXTURE_DIR / "summary.csv"))
    monkeypatch.setenv("PUBLISH_KEEP_DAYS", "14")
    return get_settings()


def test_publish_daily_writes_current_and_manifest(publish_settings) -> None:
    result = publish_daily(settings=publish_settings, asof="2026-03-10")

    for filename in SNAPSHOT_FILENAMES.values():
        assert (result.current_dir / filename).exists()
        assert (result.published_dir / filename).exists()

    manifest = json.loads((result.current_dir / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    assert manifest["as_of_date"] == "2026-03-10"
    assert manifest["models"] == ["s2_regime_growth"]


def test_publish_daily_keeps_previous_current_on_failure(publish_settings) -> None:
    first_result = publish_daily(settings=publish_settings, asof="2026-03-10")
    daily_path = first_result.current_dir / SNAPSHOT_FILENAMES["daily_recommendations"]
    first_daily = daily_path.read_text(encoding="utf-8")

    def broken_factory(settings, asof_date):
        class BrokenAdapter:
            def describe_input_sources(self):
                return {"broken": "fixture"}

            def build_service_payloads(self):
                return {
                    "model_catalog": {"models": []},
                    "daily_recommendations": {"as_of_date": "2026-03-10"},
                    "recent_changes": {"as_of_date": "2026-03-10", "changes": []},
                    "performance_summary": {"models": []},
                }

        return BrokenAdapter()

    with pytest.raises(Exception):
        publish_daily(
            settings=publish_settings,
            asof="2026-03-10",
            adapter_factories={"s2_regime_growth": broken_factory},
            force=True,
        )

    current_daily = daily_path.read_text(encoding="utf-8")
    assert current_daily == first_daily
