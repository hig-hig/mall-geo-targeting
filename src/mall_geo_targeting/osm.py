"""Local OpenStreetMap GeoJSON adapter and explainable accessibility features."""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import Mall, Mesh

LOGGER = logging.getLogger(__name__)
EARTH_RADIUS_M = 6_371_008.8


class OsmAdapterError(ValueError):
    """Raised when local OSM-derived GeoJSON or configuration is invalid."""


@dataclass(frozen=True)
class LocalProjection:
    """Local equirectangular metric projection around a fixed origin."""

    latitude_origin: float
    longitude_origin: float

    def project(self, longitude: float, latitude: float) -> tuple[float, float]:
        x = EARTH_RADIUS_M * math.radians(longitude - self.longitude_origin) * math.cos(
            math.radians(self.latitude_origin)
        )
        y = EARTH_RADIUS_M * math.radians(latitude - self.latitude_origin)
        return x, y


@dataclass(frozen=True)
class OsmAccessibilityData:
    roads: list[list[tuple[float, float]]]
    major_roads: list[list[tuple[float, float]]]
    walkable_roads: list[list[tuple[float, float]]]
    stations: list[tuple[float, float]]
    bus_stops: list[tuple[float, float]]
    parking: list[tuple[float, float]]


def _matches(properties: dict[str, Any], selectors: dict[str, Any] | list[dict[str, Any]]) -> bool:
    choices = [selectors] if isinstance(selectors, dict) else selectors
    return any(str(properties.get(item["key"], "")) in {str(v) for v in item["values"]} for item in choices)


def _point_for_geometry(geometry: dict[str, Any]) -> tuple[float, float] | None:
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if kind == "Point" and isinstance(coordinates, list) and len(coordinates) >= 2:
        return float(coordinates[0]), float(coordinates[1])
    if kind == "Polygon" and isinstance(coordinates, list) and coordinates and coordinates[0]:
        ring = coordinates[0]
        points = [(float(point[0]), float(point[1])) for point in ring]
        if len(points) > 1 and points[0] == points[-1]:
            points = points[:-1]
        return sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points)
    return None


def load_osm_geojson(path: Path, config: dict[str, Any], projection: LocalProjection) -> OsmAccessibilityData:
    if str(config.get("crs", "")) != "EPSG:4326":
        raise OsmAdapterError("初期OSMアダプターはWGS84 (EPSG:4326) GeoJSONのみ対応します")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OsmAdapterError(f"OSM GeoJSONを読み込めません: {path}: {exc}") from exc
    if document.get("type") != "FeatureCollection" or not isinstance(document.get("features"), list):
        raise OsmAdapterError("OSM GeoJSONはFeatureCollectionである必要があります")
    tags = config.get("tags")
    if not isinstance(tags, dict):
        raise OsmAdapterError("osm.tagsを設定してください")
    required = ("roads", "major_roads", "walkable_roads", "stations", "bus_stops", "parking")
    if any(name not in tags for name in required):
        raise OsmAdapterError("osm.tagsに道路・駅・バス停・駐車場の全設定が必要です")
    roads: list[list[tuple[float, float]]] = []
    major: list[list[tuple[float, float]]] = []
    walkable: list[list[tuple[float, float]]] = []
    stations: list[tuple[float, float]] = []
    buses: list[tuple[float, float]] = []
    parking: list[tuple[float, float]] = []
    try:
        for feature in document["features"]:
            properties = feature.get("properties") or {}
            geometry = feature.get("geometry") or {}
            if geometry.get("type") == "LineString" and _matches(properties, tags["roads"]):
                line = [projection.project(float(point[0]), float(point[1])) for point in geometry["coordinates"]]
                if len(line) >= 2:
                    roads.append(line)
                    if _matches(properties, tags["major_roads"]):
                        major.append(line)
                    if _matches(properties, tags["walkable_roads"]):
                        walkable.append(line)
            point = _point_for_geometry(geometry)
            if point is not None:
                projected = projection.project(*point)
                if _matches(properties, tags["stations"]):
                    stations.append(projected)
                if _matches(properties, tags["bus_stops"]):
                    buses.append(projected)
                if _matches(properties, tags["parking"]):
                    parking.append(projected)
    except (KeyError, TypeError, ValueError) as exc:
        raise OsmAdapterError(f"OSM GeoJSONのgeometryまたはタグが不正です: {exc}") from exc
    LOGGER.info("OSM GeoJSON読込: 道路%d、幹線%d、歩行可能%d、駅%d、バス停%d、駐車場%d", len(roads), len(major), len(walkable), len(stations), len(buses), len(parking))
    return OsmAccessibilityData(roads, major, walkable, stations, buses, parking)


def _clipped_segment_length(a: tuple[float, float], b: tuple[float, float], bounds: tuple[float, float, float, float]) -> float:
    """Liang-Barsky clipping length for an axis-aligned metric rectangle."""
    xmin, ymin, xmax, ymax = bounds
    dx, dy = b[0] - a[0], b[1] - a[1]
    p = (-dx, dx, -dy, dy)
    q = (a[0] - xmin, xmax - a[0], a[1] - ymin, ymax - a[1])
    start, end = 0.0, 1.0
    for pi, qi in zip(p, q, strict=True):
        if pi == 0:
            if qi < 0:
                return 0.0
            continue
        ratio = qi / pi
        if pi < 0:
            start = max(start, ratio)
        else:
            end = min(end, ratio)
        if start > end:
            return 0.0
    return math.hypot(dx, dy) * (end - start)


def _line_length_in_bounds(lines: list[list[tuple[float, float]]], bounds: tuple[float, float, float, float]) -> float:
    return sum(_clipped_segment_length(a, b, bounds) for line in lines for a, b in zip(line, line[1:], strict=False))


def _proximity(distance: float | None, maximum: float) -> float | None:
    return None if distance is None else max(0.0, 1.0 - distance / maximum)


def calculate_osm_accessibility(
    meshes: list[Mesh],
    mall: Mall,
    data: OsmAccessibilityData,
    projection: LocalProjection,
    config: dict[str, Any],
) -> None:
    weights = config.get("weights", {})
    thresholds = config.get("thresholds", {})
    expected = ("mall_proximity", "major_road_density", "walkable_road_density", "station_proximity", "bus_stop_proximity", "parking_availability")
    if set(weights) != set(expected) or any(float(weights[name]) < 0 for name in expected):
        raise ValueError("accessibility_weights.yamlのweightsに6要素の非負重みが必要です")
    total_weight = sum(float(weights[name]) for name in expected)
    if total_weight <= 0:
        raise ValueError("到達性要素の重み合計は正数である必要があります")
    mall_xy = projection.project(mall.longitude, mall.latitude)
    for mesh in meshes:
        projected_polygon = [projection.project(point[0], point[1]) for point in mesh.polygon]
        xs, ys = [p[0] for p in projected_polygon], [p[1] for p in projected_polygon]
        bounds = min(xs), min(ys), max(xs), max(ys)
        center = projection.project(mesh.center_longitude, mesh.center_latitude)
        width, height = bounds[2] - bounds[0], bounds[3] - bounds[1]
        area_km2 = width * height / 1_000_000
        mesh.road_length_m = round(_line_length_in_bounds(data.roads, bounds), 2) if data.roads else None
        mesh.major_road_length_m = round(_line_length_in_bounds(data.major_roads, bounds), 2) if data.major_roads else None
        mesh.walkable_road_length_m = round(_line_length_in_bounds(data.walkable_roads, bounds), 2) if data.walkable_roads else None
        mesh.nearest_station_distance_m = round(min((math.dist(center, point) for point in data.stations), default=math.inf), 2) if data.stations else None
        mesh.nearest_bus_stop_distance_m = round(min((math.dist(center, point) for point in data.bus_stops), default=math.inf), 2) if data.bus_stops else None
        mesh.parking_count = sum(bounds[0] <= p[0] <= bounds[2] and bounds[1] <= p[1] <= bounds[3] for p in data.parking) if data.parking else None
        mesh.straight_line_distance_to_mall_m = round(math.dist(center, mall_xy), 2)
        values = {
            "mall_proximity": _proximity(mesh.straight_line_distance_to_mall_m, float(thresholds["mall_max_distance_m"])),
            "major_road_density": min(1.0, (mesh.major_road_length_m / area_km2) / float(thresholds["major_road_saturation_m_per_km2"])) if mesh.major_road_length_m is not None else None,
            "walkable_road_density": min(1.0, (mesh.walkable_road_length_m / area_km2) / float(thresholds["walkable_road_saturation_m_per_km2"])) if mesh.walkable_road_length_m is not None else None,
            "station_proximity": _proximity(mesh.nearest_station_distance_m, float(thresholds["station_max_distance_m"])),
            "bus_stop_proximity": _proximity(mesh.nearest_bus_stop_distance_m, float(thresholds["bus_stop_max_distance_m"])),
            "parking_availability": min(1.0, mesh.parking_count / float(thresholds["parking_count_saturation"])) if mesh.parking_count is not None else None,
        }
        mesh.accessibility_used_components = [name for name in expected if values[name] is not None]
        available_weight = sum(float(weights[name]) for name in mesh.accessibility_used_components)
        mesh.accessibility_coverage = round(available_weight / total_weight, 6)
        mesh.accessibility_index = round(sum(values[name] * float(weights[name]) for name in mesh.accessibility_used_components) / available_weight, 6) if available_weight > 0 else None  # type: ignore[operator]
