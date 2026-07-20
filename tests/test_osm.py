import json
from pathlib import Path

import pytest

from mall_geo_targeting.analysis import generate_meshes
from mall_geo_targeting.config import load_yaml, mall_from_dict
from mall_geo_targeting.models import Mall, Mesh
from mall_geo_targeting.osm import LocalProjection, OsmAccessibilityData, OsmAdapterError, calculate_osm_accessibility, load_osm_geojson


def accessibility_config() -> dict[str, object]:
    return {
        "weights": {
            "mall_proximity": 0.25,
            "major_road_density": 0.20,
            "walkable_road_density": 0.20,
            "station_proximity": 0.15,
            "bus_stop_proximity": 0.10,
            "parking_availability": 0.10,
        },
        "thresholds": {
            "mall_max_distance_m": 3000,
            "station_max_distance_m": 2000,
            "bus_stop_max_distance_m": 1000,
            "major_road_saturation_m_per_km2": 8000,
            "walkable_road_saturation_m_per_km2": 12000,
            "parking_count_saturation": 3,
        },
    }


def test_local_projection_produces_metric_distance() -> None:
    projection = LocalProjection(35.0, 139.0)
    origin = projection.project(139.0, 35.0)
    east = projection.project(139.001, 35.0)
    assert origin == (0.0, 0.0)
    assert 90 < east[0] < 92
    assert east[1] == 0.0


def test_configurable_tags_load_sample_geojson() -> None:
    root = Path(__file__).parents[1]
    osm_config = load_yaml(root / "config" / "osm.yaml")
    projection = LocalProjection(35.655, 139.756)
    data = load_osm_geojson(root / "data/raw/osm/sample_osm.geojson", osm_config, projection)
    assert len(data.roads) == 4
    assert len(data.major_roads) == 2
    assert len(data.walkable_roads) == 2
    assert len(data.stations) == 1
    assert len(data.bus_stops) == 1
    assert len(data.parking) == 2


def test_walkable_roads_exclude_access_and_foot_restrictions(tmp_path: Path) -> None:
    features = []
    for index, properties in enumerate(
        ({"highway": "footway"}, {"highway": "footway", "access": "private"}, {"highway": "path", "foot": "no"})
    ):
        features.append(
            {
                "type": "Feature",
                "id": f"way/{index}",
                "properties": properties,
                "geometry": {"type": "LineString", "coordinates": [[139, 35], [139.001, 35]]},
            }
        )
    path = tmp_path / "osm.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")
    root = Path(__file__).parents[1]
    data = load_osm_geojson(path, load_yaml(root / "config/osm.yaml"), LocalProjection(35, 139))
    assert len(data.roads) == 3
    assert len(data.walkable_roads) == 1


def test_rail_platform_is_not_bus_stop(tmp_path: Path) -> None:
    features = [
        {
            "type": "Feature",
            "id": "node/1",
            "properties": {"public_transport": "platform", "railway": "platform", "train": "yes"},
            "geometry": {"type": "Point", "coordinates": [139, 35]},
        },
        {
            "type": "Feature",
            "id": "node/2",
            "properties": {"public_transport": "platform", "bus": "yes"},
            "geometry": {"type": "Point", "coordinates": [139, 35]},
        },
    ]
    path = tmp_path / "osm.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")
    root = Path(__file__).parents[1]
    data = load_osm_geojson(path, load_yaml(root / "config/osm.yaml"), LocalProjection(35, 139))
    assert len(data.bus_stops) == 1


def test_only_wgs84_geojson_is_accepted(tmp_path: Path) -> None:
    path = tmp_path / "osm.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": []}), encoding="utf-8")
    with pytest.raises(OsmAdapterError, match="EPSG:4326"):
        load_osm_geojson(path, {"crs": "EPSG:3857"}, LocalProjection(35, 139))


def test_absent_category_is_missing_but_observed_empty_mesh_is_zero() -> None:
    mall = Mall("mall", "mall", 35.0, 139.0, 10_000)
    projection = LocalProjection(mall.latitude, mall.longitude)
    mesh = Mesh(
        "mesh",
        0,
        0,
        35.0,
        139.0,
        [[138.999, 34.999], [139.001, 34.999], [139.001, 35.001], [138.999, 35.001], [138.999, 34.999]],
    )
    far_road = [[projection.project(139.01, 35.01), projection.project(139.02, 35.02)]]
    data = OsmAccessibilityData(
        roads=far_road,
        major_roads=far_road,
        walkable_roads=[],
        stations=[],
        bus_stops=[],
        parking=[],
    )
    calculate_osm_accessibility([mesh], mall, data, projection, accessibility_config())
    assert mesh.road_length_m == 0.0
    assert mesh.major_road_length_m == 0.0
    assert mesh.walkable_road_length_m is None
    assert mesh.nearest_station_distance_m is None
    assert mesh.parking_count is None
    assert mesh.accessibility_used_components == ["mall_proximity", "major_road_density"]
    assert mesh.accessibility_coverage == 0.45


def test_osm_accessibility_is_bounded_and_uses_metric_raw_features() -> None:
    root = Path(__file__).parents[1]
    mall_config = load_yaml(root / "config" / "malls.yaml")
    target = mall_from_dict(mall_config["target_mall"])
    meshes = generate_meshes(target, 500, 250)
    projection = LocalProjection(target.latitude, target.longitude)
    osm_config = load_yaml(root / "config" / "osm.yaml")
    data = load_osm_geojson(root / osm_config["path"], osm_config, projection)
    calculate_osm_accessibility(meshes, target, data, projection, accessibility_config())
    assert all(mesh.accessibility_index is not None and 0 <= mesh.accessibility_index <= 1 for mesh in meshes)
    assert all(mesh.accessibility_coverage == 1.0 for mesh in meshes)
    assert data.roads
    assert all(mesh.straight_line_distance_to_mall_m is not None for mesh in meshes)
