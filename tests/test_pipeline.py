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
    assert matched
    assert all(f["properties"]["standard_mesh_code"] for f in matched)
    demographic = next(
        f for f in matched
        if f["properties"]["population"] and f["properties"]["household_count"]
    )
    assert "target_age_population_index" in demographic["properties"]["used_features"]
    assert "household_composition_index" in demographic["properties"]["used_features"]
    assert "accessibility_index" in demographic["properties"]["missing_features"]
    assert "smartphone_affinity" not in demographic["properties"]["used_features"]
    assert demographic["properties"]["score_coverage"] == 0.65
    assert demographic["properties"]["score_quality_tier"] == "B"
    assert demographic["properties"]["eligible_for_delivery"] is True

    huff_only = [
        f for f in geojson["features"]
        if f["properties"]["used_features"] == ["huff_visit_probability"]
    ]
    assert huff_only
    assert all(f["properties"]["acquisition_potential_score"] is not None for f in huff_only)
    assert all(f["properties"]["score_quality_tier"] == "D" for f in huff_only)
    assert all(f["properties"]["eligible_for_delivery"] is False for f in huff_only)
    assert all(f["properties"]["is_delivery_zone"] is False for f in huff_only)
