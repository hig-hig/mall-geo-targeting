"""CSV, GeoJSON, and standalone HTML-map writers."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Mapping

from .map_output import build_map_html
from .models import Mall, Mesh


FIELDS = ["mesh_id", "standard_mesh_code", "source_standard_mesh_code", "center_latitude", "center_longitude", "population", "population_status", "household_count", "household_count_status", "age_0_14_population", "age_0_14_status", "age_15_64_population", "age_15_64_status", "age_65_plus_population", "age_65_plus_status", "source_survey_year", "source_table_id", "young_adult_ratio", "smartphone_affinity", "target_age_population_index", "household_composition_index", "huff_probability", "car_choice_index", "walk_choice_index", "bike_choice_index", "car_availability", "walk_availability", "bike_availability", "road_length_m", "major_road_length_m", "walkable_road_length_m", "nearest_station_distance_m", "nearest_bus_stop_distance_m", "parking_count", "straight_line_distance_to_mall_m", "accessibility_index", "accessibility_coverage", "accessibility_used_components", "retail_count", "supermarket_count", "convenience_store_count", "restaurant_count", "cafe_count", "entertainment_count", "service_count", "office_count", "hotel_count", "commercial_poi_total", "commercial_poi_density", "nearest_commercial_poi_distance_m", "commercial_concentration_index", "commercial_coverage", "commercial_used_components", "acquisition_potential_score", "score_coverage", "score_quality_tier", "feature_count_used", "feature_count_enabled", "required_groups_passed", "required_groups_missing", "required_feature_gate_passed", "eligible_for_delivery", "used_features", "missing_features", "used_weights", "score_contributions", "score_method", "is_delivery_zone", "missing_fields"]


def _properties(mesh: Mesh) -> dict[str, object]:
    return {name: (",".join(mesh.missing_fields) if name == "missing_fields" else getattr(mesh, name)) for name in FIELDS}


def _csv_row(mesh: Mesh) -> dict[str, object]:
    properties = _properties(mesh)
    for name in ("accessibility_used_components", "commercial_used_components", "required_groups_passed", "required_groups_missing", "used_features", "missing_features", "used_weights", "score_contributions"):
        properties[name] = json.dumps(properties[name], ensure_ascii=False, sort_keys=True)
    return properties


def write_outputs(
    meshes: list[Mesh],
    mall: Mall,
    output_dir: Path,
    *,
    competitors: list[Mall] | None = None,
    map_context: Mapping[str, object] | None = None,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path, geojson_path, html_path = output_dir / "mesh_scores.csv", output_dir / "delivery_zones.geojson", output_dir / "map.html"
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(_csv_row(mesh) for mesh in meshes)
    features = [{"type": "Feature", "properties": _properties(mesh), "geometry": {"type": "Polygon", "coordinates": [mesh.polygon]}} for mesh in meshes]
    geojson = {"type": "FeatureCollection", "features": features}
    geojson_path.write_text(json.dumps(geojson, ensure_ascii=False, indent=2), encoding="utf-8")
    html = build_map_html(
        meshes,
        mall,
        competitors or [],
        map_context or {},
    )
    html_path.write_text(html, encoding="utf-8")
    return {"csv": csv_path, "geojson": geojson_path, "html": html_path}
