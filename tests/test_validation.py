import logging
from pathlib import Path

from mall_geo_targeting.pipeline import run
from mall_geo_targeting.validation import validate_inputs


def test_sample_inputs_validate_with_explicit_warnings() -> None:
    root = Path(__file__).parents[1]
    report = validate_inputs(root)
    assert report.errors == []
    warned_sources = {issue.source for issue in report.warnings}
    assert {"malls", "estat", "osm", "commercial"} <= warned_sources
    assert sum("サンプルデータ" in issue.message for issue in report.warnings) == 3
    assert any(issue.source == "malls" and "暫定値" in issue.message for issue in report.warnings)


def test_require_real_rejects_samples_and_incomplete_coverage() -> None:
    root = Path(__file__).parents[1]
    report = validate_inputs(root, require_real=True)
    assert report.errors
    assert {"estat", "osm", "commercial"} <= {issue.source for issue in report.errors}
    assert not any(issue.source == "malls" and "サンプルデータ" in issue.message for issue in report.errors)
    assert any(issue.source == "malls" and "暫定値" in issue.message for issue in report.warnings)
    assert any("Feature ID" in issue.message for issue in report.errors)
    assert any("coverage" in issue.message or "覆っていません" in issue.message for issue in report.errors)


def test_pipeline_warns_when_sample_modes_are_selected(caplog) -> None:
    root = Path(__file__).parents[1]
    with caplog.at_level(logging.WARNING):
        run(root, data_mode="sample", accessibility_mode="sample", commercial_mode="sample")
    messages = [record.getMessage() for record in caplog.records]
    assert any("sample人口モード" in message for message in messages)
    assert any("sample到達性モード" in message for message in messages)
    assert any("sample商業モード" in message for message in messages)
