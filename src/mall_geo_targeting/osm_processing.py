"""Convert locally acquired Overpass JSON files into reproducible OSM GeoJSON."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import yaml


def _element_key(element: dict[str, Any]) -> tuple[str, int]:
    return str(element["type"]), int(element["id"])


def _merge_elements(paths: list[Path]) -> tuple[list[dict[str, Any]], int, int]:
    elements_by_key: dict[tuple[str, int], dict[str, Any]] = {}
    input_count = 0
    duplicate_count = 0
    for path in paths:
        document = json.loads(path.read_text(encoding="utf-8"))
        elements = document.get("elements")
        if not isinstance(elements, list):
            raise ValueError(f"Overpass JSONにelementsがありません: {path}")
        input_count += len(elements)
        for element in elements:
            key = _element_key(element)
            existing = elements_by_key.get(key)
            if existing is None:
                elements_by_key[key] = element
                continue
            duplicate_count += 1
            merged = dict(existing)
            merged.update(element)
            merged["tags"] = {**existing.get("tags", {}), **element.get("tags", {})}
            elements_by_key[key] = merged
    return list(elements_by_key.values()), input_count, duplicate_count


def _lon_lat(point: dict[str, Any]) -> list[float]:
    return [float(point["lon"]), float(point["lat"])]


def _representative_point(element: dict[str, Any]) -> list[float] | None:
    center = element.get("center")
    if isinstance(center, dict) and "lon" in center and "lat" in center:
        return _lon_lat(center)
    bounds = element.get("bounds")
    if isinstance(bounds, dict) and all(
        name in bounds for name in ("minlon", "minlat", "maxlon", "maxlat")
    ):
        return [
            (float(bounds["minlon"]) + float(bounds["maxlon"])) / 2,
            (float(bounds["minlat"]) + float(bounds["maxlat"])) / 2,
        ]
    return None


def _geometry(element: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    element_type = element.get("type")
    if element_type == "node":
        if "lon" not in element or "lat" not in element:
            return None, "node_without_coordinates"
        return {"type": "Point", "coordinates": _lon_lat(element)}, None
    if element_type == "way":
        raw_geometry = element.get("geometry")
        if not isinstance(raw_geometry, list) or len(raw_geometry) < 2:
            return None, "way_without_usable_geometry"
        coordinates = [_lon_lat(point) for point in raw_geometry]
        tags = element.get("tags", {})
        polygonal = len(coordinates) >= 4 and coordinates[0] == coordinates[-1] and (
            tags.get("amenity") == "parking" or tags.get("area") == "yes"
        )
        if polygonal:
            return {"type": "Polygon", "coordinates": [coordinates]}, None
        return {"type": "LineString", "coordinates": coordinates}, None
    if element_type == "relation":
        point = _representative_point(element)
        if point is None:
            return None, "relation_without_representative_point"
        return {"type": "Point", "coordinates": point}, "relation_represented_as_point"
    return None, "unsupported_element_type"


def convert_overpass(paths: list[Path]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Convert source files and return GeoJSON plus deterministic conversion statistics."""
    elements, input_count, duplicate_count = _merge_elements(paths)
    features: list[dict[str, Any]] = []
    excluded: Counter[str] = Counter()
    notices: Counter[str] = Counter()
    element_types: Counter[str] = Counter()
    geometry_types: Counter[str] = Counter()
    highway_types: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()
    walkable_exclusions: Counter[str] = Counter()
    road_values = {
        "motorway", "trunk", "primary", "secondary", "tertiary", "residential",
        "living_street", "service", "footway", "path", "pedestrian",
    }
    walkable_values = {"residential", "living_street", "service", "footway", "path", "pedestrian"}
    for element in elements:
        element_types[str(element.get("type"))] += 1
        geometry, reason = _geometry(element)
        if geometry is None:
            excluded[str(reason)] += 1
            continue
        if reason:
            notices[reason] += 1
        identifier = f"{element['type']}/{element['id']}"
        features.append(
            {
                "type": "Feature",
                "id": identifier,
                "properties": dict(element.get("tags", {})),
                "geometry": geometry,
            }
        )
        geometry_types[geometry["type"]] += 1
        tags = element.get("tags", {})
        highway = str(tags.get("highway", ""))
        if highway:
            highway_types[highway] += 1
        if geometry["type"] == "LineString" and highway in road_values:
            category_counts["roads"] += 1
            if highway in walkable_values:
                restricted = False
                if str(tags.get("access", "")) in {"no", "private"}:
                    walkable_exclusions["access_no_or_private"] += 1
                    restricted = True
                if str(tags.get("foot", "")) in {"no", "private"}:
                    walkable_exclusions["foot_no_or_private"] += 1
                    restricted = True
                if restricted:
                    walkable_exclusions["unique_features"] += 1
        point_compatible = geometry["type"] in {"Point", "Polygon"}
        if point_compatible and (
            tags.get("railway") in {"station", "halt"} or tags.get("train") == "yes"
        ) and (tags.get("railway") in {"station", "halt"} or tags.get("public_transport") == "station"):
            category_counts["stations"] += 1
        bus_match = tags.get("highway") == "bus_stop" or (
            tags.get("public_transport") == "platform" and tags.get("bus") in {"yes", "designated"}
        )
        if point_compatible and bus_match and tags.get("railway") is None and tags.get("train") != "yes":
            category_counts["bus_stops"] += 1
        if point_compatible and tags.get("amenity") == "parking":
            category_counts["parking"] += 1
    stats = {
        "input_elements": input_count,
        "unique_elements": len(elements),
        "duplicate_source_elements": duplicate_count,
        "element_counts": dict(sorted(element_types.items())),
        "feature_counts_by_geometry": dict(sorted(geometry_types.items())),
        "feature_counts_by_category": dict(sorted(category_counts.items())),
        "highway_counts": dict(sorted(highway_types.items())),
        "walkable_excluded_counts": dict(sorted(walkable_exclusions.items())),
        "excluded_counts": dict(sorted(excluded.items())),
        "processing_notices": dict(sorted(notices.items())),
        "feature_count": len(features),
    }
    return {"type": "FeatureCollection", "features": features}, stats


def _bbox(document: dict[str, Any]) -> list[float]:
    points: list[tuple[float, float]] = []

    def walk(value: Any) -> None:
        if isinstance(value, list) and len(value) >= 2 and all(
            isinstance(item, (int, float)) for item in value[:2]
        ):
            points.append((float(value[0]), float(value[1])))
        elif isinstance(value, list):
            for child in value:
                walk(child)

    for feature in document["features"]:
        walk(feature["geometry"]["coordinates"])
    return [
        min(point[0] for point in points),
        min(point[1] for point in points),
        max(point[0] for point in points),
        max(point[1] for point in points),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Overpass JSONをWGS84 GeoJSONへ変換")
    parser.add_argument("--source", action="append", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metadata-output", type=Path, required=True)
    parser.add_argument("--retrieved-at", required=True)
    parser.add_argument("--query-bbox", nargs=4, type=float, required=True)
    parser.add_argument("--required-bbox", nargs=4, type=float, required=True)
    args = parser.parse_args()

    document, stats = convert_overpass(args.source)
    output_bbox = _bbox(document)
    metadata = {
        "dataset_name": "イオンモールむさし村山周辺 OpenStreetMap地物",
        "source": "OpenStreetMap contributors (Overpass API)",
        "source_url": "https://overpass-api.de/api/interpreter",
        "license": "Open Database License (ODbL) 1.0",
        "commercial_use_allowed": True,
        "attribution_required": True,
        "retrieved_at": args.retrieved_at,
        "coverage_area": args.query_bbox,
        "processing": (
            "Overpass API JSONのnodeをPoint、way.geometryをLineString、閉じた駐車場等をPolygonへ変換。"
            "multipolygon relationは不正な面の生成を避け、boundsまたはcenterの代表Pointへ変換した。"
            "同一OSM要素はタグを統合し、geometryがない要素は除外した。"
        ),
        "is_sample": False,
        "source_files": [str(path) for path in args.source],
        "source_generator": "Overpass API 0.7.62.11 87bfad18",
        "query_bbox": args.query_bbox,
        "required_bbox": args.required_bbox,
        "query_conditions": {
            "roads": (
                "highway=motorway|trunk|primary|secondary|tertiary|residential|living_street|"
                "service|footway|path|pedestrian"
            ),
            "poi": "amenity=parking、railway/public_transportの駅・platform、highway=bus_stop",
            "note": "元JSONにクエリ本文は含まれないため、ファイル内容と取得時の作業条件を記録。",
        },
        "feature_counts": {
            "total": stats["feature_count"],
            "elements": stats["element_counts"],
            "geometry": stats["feature_counts_by_geometry"],
            "category": stats["feature_counts_by_category"],
        },
        "excluded_counts": {
            **stats["excluded_counts"],
            "duplicate_source_elements_merged": stats["duplicate_source_elements"],
        },
        "processing_notices": stats["processing_notices"],
        "highway_counts": stats["highway_counts"],
        "walkable_excluded_counts": stats["walkable_excluded_counts"],
        "output_bbox": output_bbox,
        "crs": "EPSG:4326",
        "attribution": "© OpenStreetMap contributors",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.metadata_output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    args.metadata_output.write_text(
        yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    print(json.dumps({**stats, "output_bbox": output_bbox}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
