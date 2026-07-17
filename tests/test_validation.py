import logging
from pathlib import Path

import yaml

from mall_geo_targeting.pipeline import run
from mall_geo_targeting.validation import validate_competitor_candidates, validate_inputs


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


def test_competitor_candidate_ledger_is_valid() -> None:
    root = Path(__file__).parents[1]
    issues = validate_competitor_candidates(
        root / "data/raw/malls/competitor_candidates.yaml",
        root / "data/raw/malls/aeon-mall-musashimurayama__mall-profile__20260718.yaml",
    )
    assert issues == []


def test_unverified_candidate_cannot_be_registered(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    source_malls = root / "data/raw/malls/aeon-mall-musashimurayama__mall-profile__20260718.yaml"
    mall_config = yaml.safe_load(source_malls.read_text(encoding="utf-8"))
    mall_config["competitor_malls"] = [
        {
            "id": "lalaport-tachikawa-tachihi",
            "name": "ららぽーと立川立飛",
            "latitude": 0.0,
            "longitude": 0.0,
            "floor_area_m2": 63000,
            "attractiveness": 0.808,
        }
    ]
    malls_path = tmp_path / "malls.yaml"
    malls_path.write_text(yaml.safe_dump(mall_config, allow_unicode=True), encoding="utf-8")
    issues = validate_competitor_candidates(
        root / "data/raw/malls/competitor_candidates.yaml",
        malls_path,
    )
    assert any("座標未確認" in issue.message for issue in issues)
