import sys
from pathlib import Path

from service_platform.publishers import run_daily_publish


def test_run_daily_publish_writes_alert_log_on_failure(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PUBLISH_ROOT_DIR", str(tmp_path / "publish_output"))
    monkeypatch.setenv("S2_HOLDINGS_CSV", str(tmp_path / "missing_holdings.csv"))
    monkeypatch.setenv("S2_SNAPSHOT_CSV", str(tmp_path / "missing_snapshot.csv"))
    monkeypatch.setenv("S2_SUMMARY_CSV", str(tmp_path / "missing_summary.csv"))
    monkeypatch.setenv("ALERT_LOG_PATH", str(tmp_path / "alerts.log"))
    monkeypatch.setattr(sys, "argv", ["run_daily_publish", "--asof", "2026-03-10"])

    exit_code = run_daily_publish.main()

    assert exit_code == 2
    assert (tmp_path / "alerts.log").exists()
    assert "Publish Failed" in (tmp_path / "alerts.log").read_text(encoding="utf-8")
