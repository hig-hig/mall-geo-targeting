"""Commercial POI GeoJSON adapter and mesh-level concentration features."""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import Mesh
from .osm import LocalProjection

LOGGER = logging.getLogger(__name__)
CATEGORIES = ("retail", "supermarket", "convenience_store", "restaurant", "cafe", "entertainment", "service", "office", "hotel", "school", "childcare")
COMMERCIAL_CATEGORIES = CATEGORIES[:9]


class CommercialAdapterError(ValueError):
    """Raised when commercial POI input or configuration is invalid."""


@dataclass(frozen=True)
class CommercialPoi:
    category: str
    point: tuple[float, float] | None
    polygon: list[tuple[float, float]] | None


@dataclass(frozen=True)
class CommercialPoiData:
    pois: list[CommercialPoi]
    available_categories: frozenset[str]


def _matches(properties: dict[str, Any], selectors: list[dict[str, Any]]) -> bool:
    return any(str(properties.get(item["key"], "")) in {str(value) for value in item["values"]} for item in selectors)


def load_commercial_geojson(path: Path, config: dict[str, Any], projection: LocalProjection) -> CommercialPoiData:
    if str(config.get("crs", "")) != "EPSG:4326":
        raise CommercialAdapterError("初期商業POIアダプターはWGS84 (EPSG:4326) GeoJSONのみ対応します")
    categories = config.get("categories")
    available = frozenset(str(value) for value in config.get("available_categories", []))
    if not isinstance(categories, dict) or set(categories) != set(CATEGORIES):
        raise CommercialAdapterError("commercial.categoriesに11カテゴリの分類設定が必要です")
    if not available <= set(CATEGORIES):
        raise CommercialAdapterError("available_categoriesに未対応カテゴリがあります")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CommercialAdapterError(f"商業POI GeoJSONを読み込めません: {path}: {exc}") from exc
    if document.get("type") != "FeatureCollection" or not isinstance(document.get("features"), list):
        raise CommercialAdapterError("商業POI GeoJSONはFeatureCollectionである必要があります")
    pois: list[CommercialPoi] = []
    try:
        for feature in document["features"]:
            properties = feature.get("properties") or {}
            matched = next((name for name in CATEGORIES if _matches(properties, categories[name])), None)
            if matched is None or matched not in available:
                continue
            geometry = feature.get("geometry") or {}
            coordinates = geometry.get("coordinates")
            if geometry.get("type") == "Point":
                pois.append(CommercialPoi(matched, projection.project(float(coordinates[0]), float(coordinates[1])), None))
            elif geometry.get("type") == "Polygon" and coordinates and coordinates[0]:
                polygon = [projection.project(float(point[0]), float(point[1])) for point in coordinates[0]]
                if len(polygon) >= 4:
                    pois.append(CommercialPoi(matched, None, polygon))
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise CommercialAdapterError(f"商業POI GeoJSONのgeometryまたはタグが不正です: {exc}") from exc
    LOGGER.info("商業POI GeoJSONから%d件を読み込みました", len(pois))
    return CommercialPoiData(pois, available)


def _point_in_polygon(point: tuple[float, float], polygon: list[tuple[float, float]]) -> bool:
    inside = False
    j = len(polygon) - 1
    for i, current in enumerate(polygon):
        previous = polygon[j]
        if (current[1] > point[1]) != (previous[1] > point[1]):
            crossing_x = (previous[0] - current[0]) * (point[1] - current[1]) / (previous[1] - current[1]) + current[0]
            if point[0] < crossing_x:
                inside = not inside
        j = i
    return inside


def _orientation(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _segments_intersect(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float], d: tuple[float, float]) -> bool:
    def on_segment(start: tuple[float, float], point: tuple[float, float], end: tuple[float, float]) -> bool:
        return min(start[0], end[0]) <= point[0] <= max(start[0], end[0]) and min(start[1], end[1]) <= point[1] <= max(start[1], end[1])

    o1, o2 = _orientation(a, b, c), _orientation(a, b, d)
    o3, o4 = _orientation(c, d, a), _orientation(c, d, b)
    if (o1 > 0) != (o2 > 0) and (o3 > 0) != (o4 > 0):
        return True
    return (o1 == 0 and on_segment(a, c, b)) or (o2 == 0 and on_segment(a, d, b)) or (o3 == 0 and on_segment(c, a, d)) or (o4 == 0 and on_segment(c, b, d))


def _overlaps_bounds(poi: CommercialPoi, bounds: tuple[float, float, float, float]) -> bool:
    xmin, ymin, xmax, ymax = bounds
    if poi.point is not None:
        return xmin <= poi.point[0] <= xmax and ymin <= poi.point[1] <= ymax
    polygon = poi.polygon or []
    if not polygon:
        return False
    if any(xmin <= point[0] <= xmax and ymin <= point[1] <= ymax for point in polygon):
        return True
    corners = [(xmin, ymin), (xmax, ymin), (xmax, ymax), (xmin, ymax)]
    if any(_point_in_polygon(corner, polygon) for corner in corners):
        return True
    rectangle_edges = list(zip(corners, corners[1:] + corners[:1], strict=True))
    polygon_edges = list(zip(polygon, polygon[1:] + polygon[:1], strict=True))
    return any(_segments_intersect(a, b, c, d) for a, b in rectangle_edges for c, d in polygon_edges)


def _segment_distance(point: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    if dx == dy == 0:
        return math.dist(point, a)
    ratio = max(0.0, min(1.0, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / (dx * dx + dy * dy)))
    return math.dist(point, (a[0] + ratio * dx, a[1] + ratio * dy))


def _distance_to_poi(point: tuple[float, float], poi: CommercialPoi) -> float:
    if poi.point is not None:
        return math.dist(point, poi.point)
    polygon = poi.polygon or []
    if _point_in_polygon(point, polygon):
        return 0.0
    return min(_segment_distance(point, a, b) for a, b in zip(polygon, polygon[1:] + polygon[:1], strict=True))


def _poi_bounds(poi: CommercialPoi) -> tuple[float, float, float, float]:
    if poi.point is not None:
        return poi.point[0], poi.point[1], poi.point[0], poi.point[1]
    polygon = poi.polygon or []
    xs, ys = [point[0] for point in polygon], [point[1] for point in polygon]
    return min(xs), min(ys), max(xs), max(ys)


class _CommercialSpatialIndex:
    def __init__(self, pois: list[CommercialPoi], cell_size_m: float = 1000) -> None:
        self.pois = pois
        self.cell_size_m = cell_size_m
        self.cells: dict[tuple[int, int], list[int]] = {}
        for index, poi in enumerate(pois):
            xmin, ymin, xmax, ymax = _poi_bounds(poi)
            for x_cell in range(int(xmin // cell_size_m), int(xmax // cell_size_m) + 1):
                for y_cell in range(int(ymin // cell_size_m), int(ymax // cell_size_m) + 1):
                    self.cells.setdefault((x_cell, y_cell), []).append(index)

    def candidates(self, bounds: tuple[float, float, float, float]) -> list[CommercialPoi]:
        xmin, ymin, xmax, ymax = bounds
        indexes: set[int] = set()
        for x_cell in range(int(xmin // self.cell_size_m), int(xmax // self.cell_size_m) + 1):
            for y_cell in range(int(ymin // self.cell_size_m), int(ymax // self.cell_size_m) + 1):
                indexes.update(self.cells.get((x_cell, y_cell), ()))
        return [self.pois[index] for index in indexes]

    def nearest_distance(self, point: tuple[float, float]) -> float | None:
        if not self.cells:
            return None
        x_cell = int(point[0] // self.cell_size_m)
        y_cell = int(point[1] // self.cell_size_m)
        max_radius = max(
            max(abs(cell[0] - x_cell), abs(cell[1] - y_cell)) for cell in self.cells
        )
        visited: set[int] = set()
        best = math.inf
        for radius in range(max_radius + 1):
            for x in range(x_cell - radius, x_cell + radius + 1):
                for y in range(y_cell - radius, y_cell + radius + 1):
                    if radius and x_cell - radius < x < x_cell + radius and y_cell - radius < y < y_cell + radius:
                        continue
                    for index in self.cells.get((x, y), ()):
                        if index not in visited:
                            visited.add(index)
                            best = min(best, _distance_to_poi(point, self.pois[index]))
            xmin = (x_cell - radius) * self.cell_size_m
            ymin = (y_cell - radius) * self.cell_size_m
            xmax = (x_cell + radius + 1) * self.cell_size_m
            ymax = (y_cell + radius + 1) * self.cell_size_m
            distance_to_outside = min(point[0] - xmin, xmax - point[0], point[1] - ymin, ymax - point[1])
            if best <= distance_to_outside:
                return best
        return best if math.isfinite(best) else None


def calculate_commercial_concentration(
    meshes: list[Mesh],
    data: CommercialPoiData,
    projection: LocalProjection,
    config: dict[str, Any],
) -> None:
    weights = config.get("weights", {})
    thresholds = config.get("thresholds", {})
    components = ("retail_density", "food_density", "service_density", "entertainment_density", "office_density", "commercial_proximity")
    if set(weights) != set(components) or any(float(weights[name]) < 0 for name in components):
        raise ValueError("commercial_weights.yamlのweightsに6要素の非負重みが必要です")
    total_weight = sum(float(weights[name]) for name in components)
    if total_weight <= 0:
        raise ValueError("商業集積要素の重み合計は正数である必要があります")
    spatial_index = _CommercialSpatialIndex(data.pois)
    count_fields = {name: f"{name}_count" for name in COMMERCIAL_CATEGORIES}
    for mesh in meshes:
        polygon = [projection.project(point[0], point[1]) for point in mesh.polygon]
        xs, ys = [p[0] for p in polygon], [p[1] for p in polygon]
        bounds = min(xs), min(ys), max(xs), max(ys)
        area_km2 = (bounds[2] - bounds[0]) * (bounds[3] - bounds[1]) / 1_000_000
        center = projection.project(mesh.center_longitude, mesh.center_latitude)
        candidates = spatial_index.candidates(bounds)
        counts: dict[str, int | None] = {}
        for category in COMMERCIAL_CATEGORIES:
            counts[category] = sum(
                poi.category == category and _overlaps_bounds(poi, bounds) for poi in candidates
            ) if category in data.available_categories else None
            setattr(mesh, count_fields[category], counts[category])
        if all(counts[name] is not None for name in COMMERCIAL_CATEGORIES):
            mesh.commercial_poi_total = sum(value for value in counts.values() if value is not None)
            mesh.commercial_poi_density = round(mesh.commercial_poi_total / area_km2, 6)
        nearest_distance = spatial_index.nearest_distance(center)
        mesh.nearest_commercial_poi_distance_m = round(nearest_distance, 2) if nearest_distance is not None else None
        retail_available = all(name in data.available_categories for name in ("retail", "supermarket", "convenience_store"))
        food_available = all(name in data.available_categories for name in ("restaurant", "cafe"))
        values = {
            "retail_density": min(1.0, ((counts["retail"] or 0) + (counts["supermarket"] or 0) + (counts["convenience_store"] or 0)) / area_km2 / float(thresholds["retail_saturation_per_km2"])) if retail_available else None,
            "food_density": min(1.0, ((counts["restaurant"] or 0) + (counts["cafe"] or 0)) / area_km2 / float(thresholds["food_saturation_per_km2"])) if food_available else None,
            "service_density": min(1.0, (counts["service"] or 0) / area_km2 / float(thresholds["service_saturation_per_km2"])) if "service" in data.available_categories else None,
            "entertainment_density": min(1.0, (counts["entertainment"] or 0) / area_km2 / float(thresholds["entertainment_saturation_per_km2"])) if "entertainment" in data.available_categories else None,
            "office_density": min(1.0, (counts["office"] or 0) / area_km2 / float(thresholds["office_saturation_per_km2"])) if "office" in data.available_categories else None,
            "commercial_proximity": max(0.0, 1.0 - mesh.nearest_commercial_poi_distance_m / float(thresholds["commercial_max_distance_m"])) if mesh.nearest_commercial_poi_distance_m is not None else None,
        }
        mesh.commercial_used_components = [name for name in components if values[name] is not None]
        available_weight = sum(float(weights[name]) for name in mesh.commercial_used_components)
        mesh.commercial_coverage = round(available_weight / total_weight, 6)
        mesh.commercial_concentration_index = round(sum(values[name] * float(weights[name]) for name in mesh.commercial_used_components) / available_weight, 6) if available_weight > 0 else None  # type: ignore[operator]
