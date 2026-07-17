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

