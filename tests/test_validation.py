import logging
from pathlib import Path

import yaml

from mall_geo_targeting.pipeline import run
from mall_geo_targeting.config import gross_leasable_area_ratio, load_yaml, mall_from_dict
from mall_geo_targeting.validation import _validate_malls, validate_competitor_candidates, validate_inputs


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


def test_verified_target_and_competitors_are_accepted() -> None:
    root = Path(__file__).parents[1]
    issues = []
    target = _validate_malls(
        root / "data/raw/malls/aeon-mall-musashimurayama__mall-profile__20260718.yaml",
        issues,
    )
    assert target == (35.74639, 139.38475)
    assert issues == []


def test_competitor_attractiveness_is_calculated_from_floor_area() -> None:
    root = Path(__file__).parents[1]
    config = load_yaml(root / "data/raw/malls/aeon-mall-musashimurayama__mall-profile__20260718.yaml")
    target = mall_from_dict(config["target_mall"])
    competitors = [
        mall_from_dict(value, target_floor_area_m2=target.floor_area_m2)
        for value in config["competitor_malls"]
    ]
    assert competitors[0].attractiveness == gross_leasable_area_ratio(63000, 78000)
    assert competitors[1].attractiveness == gross_leasable_area_ratio(64000, 78000)


def test_duplicate_id_and_same_coordinate_are_rejected(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    source = load_yaml(root / "data/raw/malls/aeon-mall-musashimurayama__mall-profile__20260718.yaml")
    duplicate = dict(source["competitor_malls"][0])
    duplicate["id"] = source["target_mall"]["id"]
    duplicate["latitude"] = source["target_mall"]["latitude"]
    duplicate["longitude"] = source["target_mall"]["longitude"]
    source["competitor_malls"] = [duplicate]
    path = tmp_path / "malls.yaml"
    path.write_text(yaml.safe_dump(source, allow_unicode=True), encoding="utf-8")
    issues = []
    _validate_malls(path, issues)
    assert any("重複" in issue.message for issue in issues)
    assert any("異常に近接" in issue.message for issue in issues)


def test_moritown_remains_unregistered() -> None:
    root = Path(__file__).parents[1]
    candidates = load_yaml(root / "data/raw/malls/competitor_candidates.yaml")["competitor_candidates"]
    malls = load_yaml(root / "data/raw/malls/aeon-mall-musashimurayama__mall-profile__20260718.yaml")
    moritown = next(candidate for candidate in candidates if candidate["id"] == "moritown")
    assert moritown["registration_status"] == "awaiting_floor_area_verification"
    assert moritown["gross_leasable_area_m2"] is None
    assert "moritown" not in {mall["id"] for mall in malls["competitor_malls"]}
