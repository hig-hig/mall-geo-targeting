"""Convert locally acquired commercial Overpass JSON into classified GeoJSON."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from .osm_processing import _bbox, _lon_lat, _merge_elements, _representative_point

SHOP_SERVICES = {
    "beauty",
    "car_repair",
    "copyshop",
    "dry_cleaning",
    "estate_agent",
    "funeral_directors",
    "hairdresser",
    "laundry",
    "locksmith",
    "massage",
    "motorcycle_repair",
    "pet_grooming",
    "rental",
    "repair",
    "shoe_repair",
    "storage_rental",
    "tailor",
    "tattoo",
    "travel_agency",
}
FOOD_AMENITIES = {"bar", "cafe", "fast_food", "food_court", "pub", "restaurant"}
SERVICE_AMENITIES = {
    "atm",
    "bank",
    "car_wash",
    "clinic",
    "dentist",
    "fuel",
    "pharmacy",
    "photo_booth",
    "post_office",
    "veterinary",
}
ENTERTAINMENT_AMENITIES = {"cinema", "theatre"}
ENTERTAINMENT_LEISURE = {
    "amusement_arcade",
    "bowling_alley",
    "fitness_centre",
    "sports_centre",
    "water_park",
}
ENTERTAINMENT_TOURISM = {"attraction", "museum"}
HOTEL_TOURISM = {"guest_house", "hostel", "hotel"}


def classify_commercial(tags: dict[str, Any]) -> str | None:
    """Assign one detailed category using deterministic, most-specific-first priority."""
    shop = str(tags.get("shop", ""))
    amenity = str(tags.get("amenity", ""))
    leisure = str(tags.get("leisure", ""))
    tourism = str(tags.get("tourism", ""))
    if shop == "supermarket":
        return "supermarket"
    if shop == "convenience":
        return "convenience_store"
    if amenity in FOOD_AMENITIES:
        return "cafe" if amenity == "cafe" else "restaurant"
    if (
        amenity in ENTERTAINMENT_AMENITIES
        or leisure in ENTERTAINMENT_LEISURE
        or tourism in ENTERTAINMENT_TOURISM
        or shop == "pachinko"
    ):
        return "entertainment"
    if amenity in SERVICE_AMENITIES or shop in SHOP_SERVICES:
        return "service"
    if tourism in HOTEL_TOURISM or amenity == "love_hotel":
        return "hotel"
    if tags.get("office") not in (None, "", "no"):
        return "office"
    if amenity == "marketplace":
        return "retail"
    if shop not in {"", "no", "vacant"}:
        return "retail"
    return None


def _commercial_geometry(element: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    element_type = element.get("type")
    if element_type == "node":
        if "lon" not in element or "lat" not in element:
            return None, "node_without_coordinates"
        return {"type": "Point", "coordinates": _lon_lat(element)}, None
    if element_type == "way":
        raw_geometry = element.get("geometry")
        if isinstance(raw_geometry, list) and len(raw_geometry) >= 4:
            coordinates = [_lon_lat(point) for point in raw_geometry]
            if coordinates[0] == coordinates[-1]:
                return {"type": "Polygon", "coordinates": [coordinates]}, None
        point = _representative_point(element)
        if point is not None:
            return {"type": "Point", "coordinates": point}, "open_way_represented_as_point"
        return None, "way_without_usable_geometry"
    if element_type == "relation":
        point = _representative_point(element)
        if point is not None:
            return {"type": "Point", "coordinates": point}, "relation_represented_as_point"
        return None, "relation_without_representative_point"
    return None, "unsupported_element_type"


def convert_commercial_overpass(
    paths: list[Path],
) -> tuple[dict[str, Any], dict[str, Any]]:
    elements, input_count, duplicate_count = _merge_elements(paths)
    features: list[dict[str, Any]] = []
    detailed_counts: Counter[str] = Counter()
    geometry_counts: Counter[str] = Counter()
    excluded: Counter[str] = Counter()
    notices: Counter[str] = Counter()
    for element in elements:
        tags = dict(element.get("tags", {}))
        category = classify_commercial(tags)
        if category is None:
            excluded["classification_unmatched"] += 1
            continue
        geometry, reason = _commercial_geometry(element)
        if geometry is None:
            excluded[str(reason)] += 1
            continue
        if reason:
            notices[reason] += 1
        tags["commercial_category"] = category
        features.append(
            {
                "type": "Feature",
                "id": f"{element['type']}/{element['id']}",
                "properties": tags,
                "geometry": geometry,
            }
        )
        detailed_counts[category] += 1
        geometry_counts[str(geometry["type"])] += 1
    broad_counts = {
        "retail": sum(detailed_counts[name] for name in ("retail", "supermarket", "convenience_store")),
        "food": detailed_counts["restaurant"] + detailed_counts["cafe"],
        "service": detailed_counts["service"],
        "entertainment": detailed_counts["entertainment"],
        "office": detailed_counts["office"],
    }
    stats = {
        "input_elements": input_count,
        "unique_elements": len(elements),
        "duplicate_source_elements": duplicate_count,
        "feature_count": len(features),
        "category_counts": broad_counts,
        "detailed_category_counts": dict(sorted(detailed_counts.items())),
        "geometry_counts": dict(sorted(geometry_counts.items())),
        "excluded_counts": dict(sorted(excluded.items())),
        "processing_notices": dict(sorted(notices.items())),
    }
    return {"type": "FeatureCollection", "features": features}, stats


def main() -> int:
    parser = argparse.ArgumentParser(description="商業POI Overpass JSONを分類済みGeoJSONへ変換")
    parser.add_argument("--source", action="append", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metadata-output", type=Path, required=True)
    parser.add_argument("--retrieved-at", required=True)
    parser.add_argument("--query-bbox", nargs=4, type=float, required=True)
    parser.add_argument("--required-bbox", nargs=4, type=float, required=True)
    args = parser.parse_args()

    document, stats = convert_commercial_overpass(args.source)
    output_bbox = _bbox(document)
    metadata = {
        "dataset_name": "イオンモールむさし村山周辺 OpenStreetMap商業POI",
        "source": "OpenStreetMap contributors (Overpass API)",
        "source_url": "https://overpass-api.de/api/interpreter",
        "license": "Open Database License (ODbL) 1.0",
        "commercial_use_allowed": True,
        "attribution_required": True,
        "retrieved_at": args.retrieved_at,
        "coverage_area": args.query_bbox,
        "query_bbox": args.query_bbox,
        "required_bbox": args.required_bbox,
        "processing": (
            "nodeをPoint、閉じたwayをPolygon、開いたwayとrelationをbounds代表Pointへ変換し、"
            "shop、amenity、leisure、tourism、officeタグから単一のcommercial_categoryを付与。"
            "分類不能要素は除外した。OSMのタグ付与状況に依存するため、商業POIの完全な網羅性は保証しない。"
        ),
        "is_sample": False,
        "source_files": [str(path) for path in args.source],
        "source_generator": "Overpass API 0.7.62.11 87bfad18",
        "feature_counts": {"input_elements": stats["input_elements"], "total": stats["feature_count"]},
        "category_counts": stats["category_counts"],
        "detailed_category_counts": stats["detailed_category_counts"],
        "excluded_counts": {
            **stats["excluded_counts"],
            "duplicate_source_elements_merged": stats["duplicate_source_elements"],
        },
        "geometry_counts": stats["geometry_counts"],
        "processing_notices": stats["processing_notices"],
        "output_bbox": output_bbox,
        "crs": "EPSG:4326",
        "attribution": "© OpenStreetMap contributors",
        "query_conditions": {
            "tags": ["shop", "amenity", "leisure", "tourism", "office"],
            "excluded": "駐車場、交通施設、分類対象外タグ。nameの有無は除外条件にしない。",
            "note": "元JSONにクエリ本文は含まれないため、取得対象タグを記録。",
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.metadata_output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    args.metadata_output.write_text(
        yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    print(json.dumps({**stats, "output_bbox": output_bbox}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
