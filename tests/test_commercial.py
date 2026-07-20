from pathlib import Path

from mall_geo_targeting.analysis import generate_meshes
from mall_geo_targeting.commercial import (
    CommercialPoi,
    CommercialPoiData,
    _CommercialSpatialIndex,
    _distance_to_poi,
    calculate_commercial_concentration,
    load_commercial_geojson,
)
from mall_geo_targeting.config import load_yaml, mall_from_dict
from mall_geo_targeting.models import Mesh
from mall_geo_targeting.osm import LocalProjection


def sample_commercial_config(config: dict[str, object]) -> dict[str, object]:
    categories = {
        "retail": [{"key": "shop", "values": ["department_store", "mall", "clothes", "electronics", "books"]}],
        "supermarket": [{"key": "shop", "values": ["supermarket"]}],
        "convenience_store": [{"key": "shop", "values": ["convenience"]}],
        "restaurant": [{"key": "amenity", "values": ["restaurant", "fast_food"]}],
        "cafe": [{"key": "amenity", "values": ["cafe"]}],
        "entertainment": [{"key": "amenity", "values": ["cinema"]}],
        "service": [{"key": "amenity", "values": ["bank"]}],
        "office": [{"key": "office", "values": ["company"]}],
        "hotel": [{"key": "tourism", "values": ["hotel"]}],
        "school": [{"key": "amenity", "values": ["school"]}],
        "childcare": [{"key": "amenity", "values": ["kindergarten", "childcare"]}],
    }
    return {**config, "categories": categories, "available_categories": list(categories)}


def test_configurable_categories_include_all_required_types() -> None:
    root = Path(__file__).parents[1]
    config = load_yaml(root / "config" / "commercial.yaml")
    sample = root / "data/raw/commercial/sample_commercial_poi.geojson"
    sample_config = sample_commercial_config(config)
    data = load_commercial_geojson(sample, sample_config, LocalProjection(35.655, 139.756))
    assert len(data.pois) == 11
    assert {poi.category for poi in data.pois} == set(sample_config["available_categories"])


def test_polygon_poi_can_overlap_multiple_analysis_meshes() -> None:
    root = Path(__file__).parents[1]
    malls = load_yaml(root / "config" / "malls.yaml")
    target = mall_from_dict(malls["target_mall"])
    meshes = generate_meshes(target, 750, 250)
    projection = LocalProjection(target.latitude, target.longitude)
    commercial_config = load_yaml(root / "config" / "commercial.yaml")
    weights = load_yaml(root / "config" / "commercial_weights.yaml")
    sample = root / "data/raw/commercial/sample_commercial_poi.geojson"
    sample_config = sample_commercial_config(commercial_config)
    data = load_commercial_geojson(sample, sample_config, projection)
    calculate_commercial_concentration(meshes, data, projection, weights)
    assert sum(bool(mesh.retail_count) for mesh in meshes) > 1


def test_unrecorded_category_is_missing_and_recorded_absence_is_zero() -> None:
    root = Path(__file__).parents[1]
    weights = load_yaml(root / "config" / "commercial_weights.yaml")
    projection = LocalProjection(35.0, 139.0)
    mesh = Mesh("mesh", 0, 0, 35, 139, [[138.999,34.999],[139.001,34.999],[139.001,35.001],[138.999,35.001],[138.999,34.999]])
    data = CommercialPoiData([], frozenset({"retail", "supermarket", "convenience_store"}))
    calculate_commercial_concentration([mesh], data, projection, weights)
    assert mesh.retail_count == 0
    assert mesh.supermarket_count == 0
    assert mesh.convenience_store_count == 0
    assert mesh.restaurant_count is None
    assert mesh.commercial_poi_total is None
    assert mesh.commercial_used_components == ["retail_density"]
    assert mesh.commercial_coverage == 0.25
    assert mesh.commercial_concentration_index == 0.0


def test_spatial_index_nearest_distance_matches_full_scan() -> None:
    pois = [
        CommercialPoi("retail", (100.0, 100.0), None),
        CommercialPoi("service", None, [(1900.0, 0.0), (2100.0, 0.0), (2100.0, 200.0), (1900.0, 200.0)]),
        CommercialPoi("office", (5000.0, 5000.0), None),
    ]
    point = (2050.0, 500.0)
    expected = min(_distance_to_poi(point, poi) for poi in pois)
    assert _CommercialSpatialIndex(pois).nearest_distance(point) == expected


def test_commercial_index_is_bounded_and_metric_distance_is_output() -> None:
    root = Path(__file__).parents[1]
    target = mall_from_dict(load_yaml(root / "config" / "malls.yaml")["target_mall"])
    meshes = generate_meshes(target, 500, 250)
    projection = LocalProjection(target.latitude, target.longitude)
    config = load_yaml(root / "config" / "commercial.yaml")
    sample = root / "data/raw/commercial/sample_commercial_poi.geojson"
    sample_config = sample_commercial_config(config)
    data = load_commercial_geojson(sample, sample_config, projection)
    calculate_commercial_concentration(meshes, data, projection, load_yaml(root / "config" / "commercial_weights.yaml"))
    assert all(mesh.commercial_concentration_index is not None and 0 <= mesh.commercial_concentration_index <= 1 for mesh in meshes)
    assert all(mesh.commercial_coverage == 1.0 for mesh in meshes)
    assert all(mesh.nearest_commercial_poi_distance_m is not None for mesh in meshes)
