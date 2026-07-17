"""CSV, GeoJSON, and standalone HTML-map writers."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .models import Mall, Mesh


FIELDS = ["mesh_id", "standard_mesh_code", "source_standard_mesh_code", "center_latitude", "center_longitude", "population", "population_status", "household_count", "household_count_status", "age_0_14_population", "age_0_14_status", "age_15_64_population", "age_15_64_status", "age_65_plus_population", "age_65_plus_status", "source_survey_year", "source_table_id", "young_adult_ratio", "smartphone_affinity", "target_age_population_index", "household_composition_index", "huff_probability", "road_length_m", "major_road_length_m", "walkable_road_length_m", "nearest_station_distance_m", "nearest_bus_stop_distance_m", "parking_count", "straight_line_distance_to_mall_m", "accessibility_index", "accessibility_coverage", "accessibility_used_components", "commercial_concentration_index", "acquisition_potential_score", "score_coverage", "score_quality_tier", "feature_count_used", "feature_count_enabled", "eligible_for_delivery", "used_features", "missing_features", "used_weights", "score_method", "is_delivery_zone", "missing_fields"]


def _properties(mesh: Mesh) -> dict[str, object]:
    return {name: (",".join(mesh.missing_fields) if name == "missing_fields" else getattr(mesh, name)) for name in FIELDS}


def _csv_row(mesh: Mesh) -> dict[str, object]:
    properties = _properties(mesh)
    for name in ("accessibility_used_components", "used_features", "missing_features", "used_weights"):
        properties[name] = json.dumps(properties[name], ensure_ascii=False, sort_keys=True)
    return properties


def write_outputs(meshes: list[Mesh], mall: Mall, output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path, geojson_path, html_path = output_dir / "mesh_scores.csv", output_dir / "delivery_zones.geojson", output_dir / "map.html"
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(_csv_row(mesh) for mesh in meshes)
    features = [{"type": "Feature", "properties": _properties(mesh), "geometry": {"type": "Polygon", "coordinates": [mesh.polygon]}} for mesh in meshes]
    geojson = {"type": "FeatureCollection", "features": features}
    geojson_path.write_text(json.dumps(geojson, ensure_ascii=False, indent=2), encoding="utf-8")
    data = json.dumps(geojson, ensure_ascii=False).replace("</", "<\\/")
    html = f'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>獲得ポテンシャルマップ</title><link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"><style>html,body,#map{{height:100%;margin:0}}.legend{{background:white;padding:8px}}</style></head><body><div id="map"></div><script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script><script>const data={data};const map=L.map('map').setView([{mall.latitude},{mall.longitude}],14);L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{attribution:'&copy; OpenStreetMap contributors'}}).addTo(map);function color(p){{if(p===null)return '#999';return p>=60?'#800026':p>=45?'#FC4E2A':p>=30?'#FEB24C':'#FFEDA0'}}L.geoJSON(data,{{style:f=>({{color:f.properties.is_delivery_zone?'#006d2c':'#666',weight:f.properties.is_delivery_zone?2:0.5,fillColor:color(f.properties.acquisition_potential_score),fillOpacity:.65}}),onEachFeature:(f,l)=>l.bindPopup(`<b>${{f.properties.mesh_id}}</b><br>獲得ポテンシャル: ${{f.properties.acquisition_potential_score ?? '欠損'}}<br>品質ランク: ${{f.properties.score_quality_tier ?? '欠損'}}<br>カバレッジ: ${{f.properties.score_coverage === null ? '欠損' : (f.properties.score_coverage*100).toFixed(0)+'%'}}<br>配信適格: ${{f.properties.eligible_for_delivery ? 'はい' : 'いいえ'}}<br>到達性指数: ${{f.properties.accessibility_index ?? '欠損'}}<br>到達性coverage: ${{f.properties.accessibility_coverage === null ? '欠損' : (f.properties.accessibility_coverage*100).toFixed(0)+'%'}}<br>駅距離: ${{f.properties.nearest_station_distance_m ?? '欠損'}} m<br>バス停距離: ${{f.properties.nearest_bus_stop_distance_m ?? '欠損'}} m<br>幹線道路密度: ${{f.properties.major_road_length_m === null ? '欠損' : (f.properties.major_road_length_m/0.0625).toFixed(0)+' m/km²'}}<br>歩行道路密度: ${{f.properties.walkable_road_length_m === null ? '欠損' : (f.properties.walkable_road_length_m/0.0625).toFixed(0)+' m/km²'}}<br>人口: ${{f.properties.population ?? '欠損'}}<br>Huff来館可能性: ${{f.properties.huff_probability === null ? '欠損' : (f.properties.huff_probability*100).toFixed(1)+'%'}}`)}}).addTo(map);L.marker([{mall.latitude},{mall.longitude}]).addTo(map).bindPopup({json.dumps(mall.name, ensure_ascii=False)});</script></body></html>'''
    html_path.write_text(html, encoding="utf-8")
    return {"csv": csv_path, "geojson": geojson_path, "html": html_path}
