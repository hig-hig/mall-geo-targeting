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


def test_estat_mode_runs_without_replacing_sample_default() -> None:
    root = Path(__file__).parents[1]
    result = run(root, data_mode="estat")
    assert result["data_mode"] == "estat"
    assert result["mesh_count"] > 0
    # Required e-Stat demographics do not contain smartphone affinity, so the
    # potential score remains missing rather than silently imputing a value.
    assert result["scored_count"] == 0
    geojson = json.loads(result["outputs"]["geojson"].read_text(encoding="utf-8"))
    matched = [f for f in geojson["features"] if f["properties"]["source_table_id"]]
    assert matched
    assert all(f["properties"]["standard_mesh_code"] for f in matched)
