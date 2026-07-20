import logging
from pathlib import Path

import yaml

from mall_geo_targeting.pipeline import run
from mall_geo_targeting.config import load_yaml, mall_from_dict
from mall_geo_targeting.validation import (
    _bbox_contains,
    _bbox_within_margin,
    _validate_attractiveness_metadata,
    _validate_malls,
    validate_competitor_candidates,
    validate_inputs,
)


def test_mixed_real_and_sample_inputs_validate_with_explicit_warnings() -> None:
    root = Path(__file__).parents[1]
    report = validate_inputs(root)
    assert report.errors == []
    warned_sources = {issue.source for issue in report.warnings}
    assert "malls" not in warned_sources
    assert "commercial" not in warned_sources
    assert "osm" not in warned_sources
    assert "estat" not in warned_sources
    assert sum("サンプルデータ" in issue.message for issue in report.warnings) == 0
    assert not any(issue.source == "malls" and "暫定値" in issue.message for issue in report.warnings)


def test_require_real_accepts_configured_real_sources() -> None:
    root = Path(__file__).parents[1]
    report = validate_inputs(root, require_real=True)
    assert report.errors == []
    assert not any(issue.source == "malls" and "サンプルデータ" in issue.message for issue in report.errors)
    assert not any(issue.source == "malls" and "暫定値" in issue.message for issue in report.warnings)


def test_acquisition_bbox_can_prove_sparse_geojson_coverage() -> None:
    required = [139.2, 35.6, 139.5, 35.9]
    sparse_feature_bbox = [139.3, 35.7, 139.4, 35.8]
    query_bbox = [139.1, 35.5, 139.6, 36.0]
    assert not _bbox_contains(sparse_feature_bbox, required)
    assert _bbox_contains(query_bbox, required)


def test_feature_bbox_may_cross_query_boundary_only_within_tolerance() -> None:
    query_bbox = [139.25, 35.63, 139.52, 35.86]
    assert _bbox_within_margin([139.23, 35.61, 139.55, 35.88], query_bbox, 5000)
    assert not _bbox_within_margin([139.0, 35.3, 140.0, 36.2], query_bbox, 5000)


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


def test_all_registered_malls_use_neutral_non_size_multiplier() -> None:
    root = Path(__file__).parents[1]
    config = load_yaml(root / "data/raw/malls/aeon-mall-musashimurayama__mall-profile__20260718.yaml")
    target = mall_from_dict(config["target_mall"])
    competitors = [mall_from_dict(value) for value in config["competitor_malls"]]
    assert {value["attractiveness_method"] for value in [config["target_mall"], *config["competitor_malls"]]} == {
        "neutral_non_size_multiplier"
    }
    assert [mall.attractiveness for mall in [target, *competitors]] == [1.0, 1.0, 1.0]
    assert [mall.floor_area_m2 * mall.attractiveness for mall in [target, *competitors]] == [
        78000,
        63000,
        64000,
    ]


def test_legacy_gross_leasable_area_ratio_is_rejected(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    config = load_yaml(root / "data/raw/malls/aeon-mall-musashimurayama__mall-profile__20260718.yaml")
    config["competitor_malls"][0]["attractiveness_method"] = "gross_leasable_area_ratio"
    path = tmp_path / "malls.yaml"
    path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    issues = []
    _validate_malls(path, issues)
    assert any("neutral_non_size_multiplier" in issue.message for issue in issues)


def test_attractiveness_metadata_records_formal_method() -> None:
    root = Path(__file__).parents[1]
    metadata = load_yaml(
        root / "data/raw/malls/aeon-mall-musashimurayama__mall-profile__20260718.metadata.yaml"
    )
    issues = []
    _validate_attractiveness_metadata(metadata, issues)
    assert issues == []
    assert metadata["attractiveness_formula"] == "1.0"
    assert metadata["attractiveness_method_version"] == "1.0"


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
