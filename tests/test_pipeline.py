import json
from pathlib import Path

from mall_geo_targeting.pipeline import run


def test_sample_pipeline_outputs_files() -> None:
    root = Path(__file__).parents[1]
    result = run(root)
    assert result["mesh_count"] > 0
    assert result["scored_count"] > 0
    for path in result["outputs"].values():
        assert path.exists()
    geojson = json.loads(result["outputs"]["geojson"].read_text(encoding="utf-8"))
    assert geojson["type"] == "FeatureCollection"
    assert len(geojson["features"]) == result["mesh_count"]
    properties = geojson["features"][0]["properties"]
    for field in (
        "score_coverage",
        "score_quality_tier",
        "feature_count_used",
        "feature_count_enabled",
        "required_groups_passed",
        "required_groups_missing",
        "required_feature_gate_passed",
        "eligible_for_delivery",
    ):
        assert field in properties


def test_estat_mode_runs_without_replacing_sample_default() -> None:
    root = Path(__file__).parents[1]
    result = run(root, data_mode="estat")
    assert result["data_mode"] == "estat"
    assert result["mesh_count"] > 0
    assert result["scored_count"] > 0
    geojson = json.loads(result["outputs"]["geojson"].read_text(encoding="utf-8"))
    matched = [f for f in geojson["features"] if f["properties"]["source_table_id"]]
    # The checked-in e-Stat fixture covers the former synthetic Tokyo Bay mall,
    # not the real-data candidate in Musashimurayama. It must not be joined by accident.
    assert matched == []
    assert result["demographic_missing_count"] == result["mesh_count"]

    huff_only = [
        f for f in geojson["features"]
        if f["properties"]["used_features"] == ["huff_visit_probability"]
    ]
    assert huff_only
    assert all(f["properties"]["acquisition_potential_score"] is not None for f in huff_only)
    assert all(f["properties"]["score_quality_tier"] == "D" for f in huff_only)
    assert all(f["properties"]["eligible_for_delivery"] is False for f in huff_only)
    assert all(f["properties"]["is_delivery_zone"] is False for f in huff_only)


def test_estat_and_osm_modes_can_run_together() -> None:
    root = Path(__file__).parents[1]
    result = run(root, data_mode="estat", accessibility_mode="osm")
    assert result["data_mode"] == "estat"
    assert result["accessibility_mode"] == "osm"
    assert result["accessibility_coverage_count"] == result["mesh_count"]
    assert result["mean_accessibility_coverage"] == 1.0
    geojson = json.loads(result["outputs"]["geojson"].read_text(encoding="utf-8"))
    properties = geojson["features"][0]["properties"]
    assert properties["accessibility_index"] is not None
    assert properties["straight_line_distance_to_mall_m"] is not None
    assert properties["accessibility_used_components"]
    assert "accessibility_index" in properties["used_features"]


def test_osm_mode_overrides_deprecated_sample_accessibility() -> None:
    root = Path(__file__).parents[1]
    run(root, data_mode="sample", accessibility_mode="osm")
    geojson = json.loads((root / "outputs" / "delivery_zones.geojson").read_text(encoding="utf-8"))
    properties = geojson["features"][0]["properties"]
    assert properties["accessibility_coverage"] == 1.0
    assert properties["accessibility_used_components"]


def test_estat_osm_accessibility_and_commercial_poi_run_together() -> None:
    root = Path(__file__).parents[1]
    result = run(root, data_mode="estat", accessibility_mode="osm", commercial_mode="osm")
    assert result["commercial_mode"] == "osm"
    assert result["commercial_coverage_count"] == result["mesh_count"]
    assert result["mean_commercial_coverage"] == 1.0
    geojson = json.loads(result["outputs"]["geojson"].read_text(encoding="utf-8"))
    properties = geojson["features"][0]["properties"]
    assert properties["commercial_concentration_index"] is not None
    assert properties["commercial_poi_total"] is not None
    assert properties["commercial_used_components"]
    assert "commercial_concentration_index" in properties["used_features"]


def test_separate_commercial_file_mode_overrides_sample_value() -> None:
    root = Path(__file__).parents[1]
    result = run(root, data_mode="sample", accessibility_mode="sample", commercial_mode="file")
    assert result["commercial_mode"] == "file"
    geojson = json.loads(result["outputs"]["geojson"].read_text(encoding="utf-8"))
    properties = geojson["features"][0]["properties"]
    assert properties["commercial_coverage"] == 1.0
    assert properties["commercial_used_components"]
