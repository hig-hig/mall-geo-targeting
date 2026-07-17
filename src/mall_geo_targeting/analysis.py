"""Core mesh, Huff-model, scoring, and zoning logic."""

from __future__ import annotations

import csv
import logging
import math
from pathlib import Path

from .models import EstatMeshStatistics, Mall, Mesh, ValueStatus

LOGGER = logging.getLogger(__name__)
EARTH_RADIUS_M = 6_371_008.8


def standard_quarter_mesh_code(latitude: float, longitude: float) -> str:
    """Return the 10-digit Japanese quarter-mesh (approximately 250m) code."""
    if not 0 <= latitude < 66.6666667 or not 100 <= longitude < 180:
        raise ValueError("標準地域メッシュコードの対象範囲外の座標です")
    lat_units = latitude * 1.5
    first_lat = math.floor(lat_units)
    first_lon = math.floor(longitude) - 100
    lat_remainder = lat_units - first_lat
    lon_remainder = longitude - math.floor(longitude)
    second_lat = math.floor(lat_remainder * 8)
    second_lon = math.floor(lon_remainder * 8)
    lat_remainder = lat_remainder * 8 - second_lat
    lon_remainder = lon_remainder * 8 - second_lon
    third_lat = math.floor(lat_remainder * 10)
    third_lon = math.floor(lon_remainder * 10)
    lat_remainder = lat_remainder * 10 - third_lat
    lon_remainder = lon_remainder * 10 - third_lon
    half_lat = 1 if lat_remainder >= 0.5 else 0
    half_lon = 1 if lon_remainder >= 0.5 else 0
    half = 1 + half_lon + 2 * half_lat
    lat_remainder = lat_remainder * 2 - half_lat
    lon_remainder = lon_remainder * 2 - half_lon
    quarter_lat = 1 if lat_remainder >= 0.5 else 0
    quarter_lon = 1 if lon_remainder >= 0.5 else 0
    quarter = 1 + quarter_lon + 2 * quarter_lat
    return f"{first_lat:02d}{first_lon:02d}{second_lat}{second_lon}{third_lat}{third_lon}{half}{quarter}"


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def generate_meshes(mall: Mall, radius_m: int, mesh_size_m: int) -> list[Mesh]:
    if radius_m <= 0 or mesh_size_m <= 0:
        raise ValueError("radius_mとmesh_size_mは正数である必要があります")
    half_cells = math.ceil(radius_m / mesh_size_m)
    lat_m = 111_320.0
    lon_m = lat_m * math.cos(math.radians(mall.latitude))
    meshes: list[Mesh] = []
    for row, y_index in enumerate(range(-half_cells, half_cells)):
        for column, x_index in enumerate(range(-half_cells, half_cells)):
            south = mall.latitude + y_index * mesh_size_m / lat_m
            north = south + mesh_size_m / lat_m
            west = mall.longitude + x_index * mesh_size_m / lon_m
            east = west + mesh_size_m / lon_m
            center_lat, center_lon = (south + north) / 2, (west + east) / 2
            if haversine_m(mall.latitude, mall.longitude, center_lat, center_lon) > radius_m:
                continue
            polygon = [[west, south], [east, south], [east, north], [west, north], [west, south]]
            meshes.append(Mesh(f"M_{row:03d}_{column:03d}", row, column, center_lat, center_lon, polygon, standard_quarter_mesh_code(latitude=center_lat, longitude=center_lon)))
    LOGGER.info("%d個の%d mメッシュを生成しました", len(meshes), mesh_size_m)
    return meshes


def _optional_number(value: str, cast: type[int] | type[float]) -> int | float | None:
    return None if value.strip() == "" else cast(value)


def join_population(meshes: list[Mesh], csv_path: Path) -> None:
    """Join by mesh ID. Missing is None; numeric zero remains a valid observation."""
    try:
        with csv_path.open(encoding="utf-8", newline="") as stream:
            rows = {row["mesh_id"]: row for row in csv.DictReader(stream)}
    except (OSError, KeyError, csv.Error) as exc:
        raise ValueError(f"人口データを読み込めません: {csv_path}: {exc}") from exc
    for mesh in meshes:
        # Exact mesh statistics take precedence; row-band statistics are a compact
        # sample dataset that still exercises a real key-based join over the full area.
        row = rows.get(mesh.mesh_id) or rows.get(f"R_{mesh.row:03d}")
        if row is None:
            mesh.missing_fields = ["population", "young_adult_ratio", "smartphone_affinity"]
            continue
        try:
            mesh.population = _optional_number(row["population"], int)  # type: ignore[assignment]
            mesh.young_adult_ratio = _optional_number(row["young_adult_ratio"], float)  # type: ignore[assignment]
            mesh.smartphone_affinity = _optional_number(row["smartphone_affinity"], float)  # type: ignore[assignment]
        except (KeyError, ValueError) as exc:
            raise ValueError(f"人口データの値が不正です ({mesh.mesh_id}): {exc}") from exc
        mesh.missing_fields = [
            name for name in ("population", "young_adult_ratio", "smartphone_affinity")
            if getattr(mesh, name) is None
        ]


def join_estat_statistics(meshes: list[Mesh], statistics: dict[str, EstatMeshStatistics]) -> None:
    """Join e-Stat values by standard code while preserving the application mesh ID."""
    for mesh in meshes:
        code = mesh.standard_mesh_code or ""
        # Prefer the most detailed available record. An e-Stat table may be
        # published at quarter (10), half (9), or third (8-digit, 1km) mesh level.
        record = next((statistics[candidate] for candidate in (code, code[:9], code[:8]) if candidate in statistics), None)
        if record is None:
            mesh.population_status = ValueStatus.MISSING
            mesh.household_count_status = ValueStatus.MISSING
            mesh.age_0_14_status = ValueStatus.MISSING
            mesh.age_15_64_status = ValueStatus.MISSING
            mesh.age_65_plus_status = ValueStatus.MISSING
            mesh.missing_fields = ["population", "household_count", "age_0_14_population", "age_15_64_population", "age_65_plus_population", "smartphone_affinity"]
            continue
        mesh.population = record.total_population.value
        mesh.source_standard_mesh_code = record.standard_mesh_code
        mesh.population_status = record.total_population.status
        mesh.household_count = record.households.value
        mesh.household_count_status = record.households.status
        mesh.age_0_14_population = record.age_0_14.value
        mesh.age_0_14_status = record.age_0_14.status
        mesh.age_15_64_population = record.age_15_64.value
        mesh.age_15_64_status = record.age_15_64.status
        mesh.age_65_plus_population = record.age_65_plus.value
        mesh.age_65_plus_status = record.age_65_plus.status
        mesh.source_survey_year = record.survey_year
        mesh.source_table_id = record.table_id
        if mesh.population is not None and mesh.population > 0 and mesh.age_15_64_population is not None:
            mesh.young_adult_ratio = mesh.age_15_64_population / mesh.population
        mesh.smartphone_affinity = None  # Not supplied by the required e-Stat population table.
        mesh.missing_fields = [name for name in ("population", "household_count", "age_0_14_population", "age_15_64_population", "age_65_plus_population", "smartphone_affinity") if getattr(mesh, name) is None]


def calculate_huff(meshes: list[Mesh], target: Mall, competitors: list[Mall], exponent: float) -> None:
    if exponent <= 0:
        raise ValueError("Huffモデルの距離指数は正数である必要があります")
    malls = [target, *competitors]
    for mesh in meshes:
        utilities = []
        for mall in malls:
            distance = max(haversine_m(mesh.center_latitude, mesh.center_longitude, mall.latitude, mall.longitude), 1.0)
            utilities.append((mall.floor_area_m2 * mall.attractiveness) / distance**exponent)
        denominator = sum(utilities)
        mesh.huff_probability = utilities[0] / denominator if denominator > 0 else None


def calculate_potential(meshes: list[Mesh]) -> None:
    """Score acquisition potential (0-100), not historical download probability."""
    known_populations = [m.population for m in meshes if m.population is not None]
    max_population = max(known_populations, default=0)
    for mesh in meshes:
        required = (mesh.population, mesh.young_adult_ratio, mesh.smartphone_affinity, mesh.huff_probability)
        if any(value is None for value in required):
            mesh.acquisition_potential_score = None
            continue
        population_factor = mesh.population / max_population if max_population > 0 else 0.0
        raw = (
            0.35 * population_factor
            + 0.25 * mesh.young_adult_ratio
            + 0.20 * mesh.smartphone_affinity
            + 0.20 * mesh.huff_probability
        )
        mesh.acquisition_potential_score = round(max(0.0, min(100.0, raw * 100)), 2)


def assign_delivery_zones(meshes: list[Mesh], quantile: float) -> float | None:
    if not 0 <= quantile <= 1:
        raise ValueError("high_score_quantileは0から1の範囲で指定してください")
    scores = sorted(m.acquisition_potential_score for m in meshes if m.acquisition_potential_score is not None)
    if not scores:
        return None
    index = min(len(scores) - 1, math.ceil(quantile * len(scores)) - 1)
    threshold = scores[max(0, index)]
    for mesh in meshes:
        mesh.is_delivery_zone = mesh.acquisition_potential_score is not None and mesh.acquisition_potential_score >= threshold
    return threshold
