"""CSV, GeoJSON, and standalone HTML-map writers."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .models import Mall, Mesh


FIELDS = ["mesh_id", "center_latitude", "center_longitude", "population", "young_adult_ratio", "smartphone_affinity", "huff_probability", "acquisition_potential_score", "is_delivery_zone", "missing_fields"]


def _properties(mesh: Mesh) -> dict[str, object]:
    return {name: (",".join(mesh.missing_fields) if name == "missing_fields" else getattr(mesh, name)) for name in FIELDS}


def write_outputs(meshes: list[Mesh], mall: Mall, output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path, geojson_path, html_path = output_dir / "mesh_scores.csv", output_dir / "delivery_zones.geojson", output_dir / "map.html"
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(_properties(mesh) for mesh in meshes)
    features = [{"type": "Feature", "properties": _properties(mesh), "geometry": {"type": "Polygon", "coordinates": [mesh.polygon]}} for mesh in meshes]
    geojson = {"type": "FeatureCollection", "features": features}
    geojson_path.write_text(json.dumps(geojson, ensure_ascii=False, indent=2), encoding="utf-8")
    data = json.dumps(geojson, ensure_ascii=False).replace("</", "<\\/")
    html = f'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>獲得ポテンシャルマップ</title><link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"><style>html,body,#map{{height:100%;margin:0}}.legend{{background:white;padding:8px}}</style></head><body><div id="map"></div><script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script><script>const data={data};const map=L.map('map').setView([{mall.latitude},{mall.longitude}],14);L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{attribution:'&copy; OpenStreetMap contributors'}}).addTo(map);function color(p){{if(p===null)return '#999';return p>=60?'#800026':p>=45?'#FC4E2A':p>=30?'#FEB24C':'#FFEDA0'}}L.geoJSON(data,{{style:f=>({{color:f.properties.is_delivery_zone?'#006d2c':'#666',weight:f.properties.is_delivery_zone?2:0.5,fillColor:color(f.properties.acquisition_potential_score),fillOpacity:.65}}),onEachFeature:(f,l)=>l.bindPopup(`<b>${{f.properties.mesh_id}}</b><br>獲得ポテンシャル: ${{f.properties.acquisition_potential_score ?? '欠損'}}<br>人口: ${{f.properties.population ?? '欠損'}}<br>Huff来館可能性: ${{f.properties.huff_probability === null ? '欠損' : (f.properties.huff_probability*100).toFixed(1)+'%'}}`)}}).addTo(map);L.marker([{mall.latitude},{mall.longitude}]).addTo(map).bindPopup({json.dumps(mall.name, ensure_ascii=False)});</script></body></html>'''
    html_path.write_text(html, encoding="utf-8")
    return {"csv": csv_path, "geojson": geojson_path, "html": html_path}

