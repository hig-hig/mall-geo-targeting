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
            mesh.missing_fields = [
                "population",
                "young_adult_ratio",
                "household_count",
                "accessibility_index",
                "commercial_concentration_index",
            ]
            continue
        try:
            mesh.population = _optional_number(row["population"], int)  # type: ignore[assignment]
            mesh.young_adult_ratio = _optional_number(row["young_adult_ratio"], float)  # type: ignore[assignment]
            mesh.household_count = _optional_number(row.get("household_count", ""), int)  # type: ignore[assignment]
            mesh.accessibility_index = _optional_number(row.get("accessibility_index", ""), float)  # type: ignore[assignment]
            mesh.commercial_concentration_index = _optional_number(row.get("commercial_concentration_index", ""), float)  # type: ignore[assignment]
            # Legacy input remains readable but is deprecated and not scored.
            mesh.smartphone_affinity = _optional_number(row.get("smartphone_affinity", ""), float)  # type: ignore[assignment]
        except (KeyError, ValueError) as exc:
            raise ValueError(f"人口データの値が不正です ({mesh.mesh_id}): {exc}") from exc
        mesh.missing_fields = [
            name for name in ("population", "young_adult_ratio", "household_count", "accessibility_index", "commercial_concentration_index")
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
            mesh.missing_fields = ["population", "household_count", "age_0_14_population", "age_15_64_population", "age_65_plus_population"]
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
        mesh.smartphone_affinity = None  # Deprecated; never generated from demographics.
        mesh.missing_fields = [name for name in ("population", "household_count", "age_0_14_population", "age_15_64_population", "age_65_plus_population") if getattr(mesh, name) is None]


def calculate_huff(
    meshes: list[Mesh],
    target: Mall,
    competitors: list[Mall],
    exponent: float,
    minimum_distance_m: float = 1.0,
) -> None:
    if exponent <= 0 or minimum_distance_m <= 0:
        raise ValueError("Huffモデルの距離指数と最低距離は正数である必要があります")
    malls = [target, *competitors]
    for mesh in meshes:
        utilities = []
        for mall in malls:
            distance = max(
                haversine_m(
                    mesh.center_latitude,
                    mesh.center_longitude,
                    mall.latitude,
                    mall.longitude,
                ),
                minimum_distance_m,
            )
            utilities.append((mall.floor_area_m2 * mall.attractiveness) / distance**exponent)
        denominator = sum(utilities)
        mesh.huff_probability = utilities[0] / denominator if denominator > 0 else None


TRANSPORT_MODE_FIELDS = {
    "car": ("car_choice_index", "car_availability"),
    "walk": ("walk_choice_index", "walk_availability"),
    "bike": ("bike_choice_index", "bike_availability"),
}
FACILITY_CHOICE_MODES = ("car", "bike", "walk")


def mode_availability(distance_m: float, config: dict[str, object]) -> float:
    """Return an explicit scenario availability in [0, 1], not an observed modal share."""
    kind = str(config.get("type", ""))
    if kind == "no_hard_limit":
        return 1.0
    if kind != "linear_decay":
        raise ValueError(f"未対応のavailability.typeです: {kind}")
    full = float(config["full_availability_until_m"])
    zero = float(config["zero_availability_from_m"])
    if not 0 <= full < zero:
        raise ValueError("linear_decayは0 <= full_availability_until_m < zero_availability_from_mが必要です")
    if distance_m <= full:
        return 1.0
    if distance_m >= zero:
        return 0.0
    return (zero - distance_m) / (zero - full)


def calculate_transport_choice_indices(
    meshes: list[Mesh],
    target: Mall,
    competitors: list[Mall],
    config: dict[str, object],
) -> None:
    """Calculate display-only, uncalibrated straight-line transport scenarios."""
    malls = [target, *competitors]
    modes = config.get("modes")
    if not isinstance(modes, dict):
        raise ValueError("transport_choice.modesはマッピングで指定してください")
    for mode, (index_field, availability_field) in TRANSPORT_MODE_FIELDS.items():
        mode_config = modes.get(mode)
        if not isinstance(mode_config, dict):
            raise ValueError(f"transport_choice.modes.{mode}がありません")
        if not mode_config.get("enabled"):
            for mesh in meshes:
                setattr(mesh, index_field, None)
                setattr(mesh, availability_field, None)
            continue
        beta = float(mode_config["beta"])
        minimum_distance_m = float(mode_config["minimum_distance_m"])
        availability_config = mode_config.get("availability")
        if beta <= 0 or minimum_distance_m <= 0:
            raise ValueError(f"{mode}のbetaとminimum_distance_mは正数である必要があります")
        if not isinstance(availability_config, dict):
            raise ValueError(f"{mode}のavailabilityが不正です")
        for mesh in meshes:
            utilities: list[float] = []
            target_availability = None
            for mall_index, mall in enumerate(malls):
                raw_distance = haversine_m(
                    mesh.center_latitude,
                    mesh.center_longitude,
                    mall.latitude,
                    mall.longitude,
                )
                availability = mode_availability(raw_distance, availability_config)
                if mall_index == 0:
                    target_availability = availability
                distance = max(raw_distance, minimum_distance_m)
                utilities.append(
                    availability
                    * (mall.floor_area_m2 * mall.attractiveness)
                    / distance**beta
                )
            denominator = sum(utilities)
            setattr(mesh, index_field, utilities[0] / denominator if denominator > 0 else None)
            setattr(mesh, availability_field, target_availability)


def calculate_facility_choice_indices(
    meshes: list[Mesh],
    weights: dict[str, float],
) -> None:
    """Combine available transport indices using normalized scenario weights."""
    if set(weights) != set(FACILITY_CHOICE_MODES):
        raise ValueError("facility_choice.transport_mode_weightsにはcar、bike、walkが必要です")
    normalized_input: dict[str, float] = {}
    for mode in FACILITY_CHOICE_MODES:
        weight = float(weights[mode])
        if not math.isfinite(weight) or weight < 0:
            raise ValueError(f"facility_choice.transport_mode_weights.{mode}は0以上の有限値が必要です")
        normalized_input[mode] = weight
    if sum(normalized_input.values()) <= 0:
        raise ValueError("facility_choice.transport_mode_weightsの重みを1つ以上正数にしてください")

    for mesh in meshes:
        available = [
            (mode, float(getattr(mesh, TRANSPORT_MODE_FIELDS[mode][0])), normalized_input[mode])
            for mode in FACILITY_CHOICE_MODES
            if getattr(mesh, TRANSPORT_MODE_FIELDS[mode][0]) is not None
            and normalized_input[mode] > 0
        ]
        available_weight = sum(weight for _, _, weight in available)
        mesh.facility_choice_used_modes = [mode for mode, _, _ in available]
        if available_weight <= 0:
            mesh.facility_choice_index = None
            mesh.facility_choice_used_weights = {}
            continue
        mesh.facility_choice_used_weights = {
            mode: weight / available_weight for mode, _, weight in available
        }
        mesh.facility_choice_index = sum(
            value * mesh.facility_choice_used_weights[mode]
            for mode, value, _ in available
        )


SCORE_FEATURES = (
    "target_age_population_index",
    "household_composition_index",
    "facility_choice_index",
    "accessibility_index",
    "commercial_concentration_index",
)

DEFAULT_REQUIRED_FEATURE_GROUPS: dict[str, dict[str, list[str]]] = {
    "demographic": {"require_any": ["target_age_population_index", "household_composition_index"]},
    "mall_relationship": {"require_all": ["facility_choice_index"]},
    "context": {"require_any": ["accessibility_index", "commercial_concentration_index"]},
}


def resolve_required_feature_groups(
    base_groups: dict[str, dict[str, list[str]]],
    overrides: dict[str, dict[str, object]] | None,
    app_value: str,
) -> dict[str, dict[str, list[str]]]:
    """Resolve common required groups with an optional app-value override."""
    resolved = {name: dict(rule) for name, rule in base_groups.items()}
    override = (overrides or {}).get(app_value)
    if override is None:
        return resolved
    groups = override.get("groups")
    if not isinstance(groups, dict):
        raise ValueError(f"{app_value}のrequired feature group overrideにgroupsが必要です")
    if bool(override.get("replace", False)):
        return {str(name): dict(rule) for name, rule in groups.items()}  # type: ignore[arg-type]
    resolved.update({str(name): dict(rule) for name, rule in groups.items()})  # type: ignore[arg-type]
    return resolved


def _evaluate_required_groups(
    feature_values: dict[str, float | None],
    groups: dict[str, dict[str, list[str]]],
) -> tuple[list[str], list[str]]:
    passed: list[str] = []
    missing: list[str] = []
    for group_name, rule in groups.items():
        rule_types = set(rule)
        if rule_types not in ({"require_any"}, {"require_all"}):
            raise ValueError(f"必須特徴量グループ{group_name}はrequire_anyまたはrequire_allの一方を指定してください")
        rule_type = next(iter(rule_types))
        features = rule[rule_type]
        if not features or any(name not in SCORE_FEATURES for name in features):
            raise ValueError(f"必須特徴量グループ{group_name}に有効な特徴量を指定してください")
        available = [feature_values[name] is not None for name in features]
        group_passed = any(available) if rule_type == "require_any" else all(available)
        (passed if group_passed else missing).append(group_name)
    return passed, missing


def _validate_index(name: str, value: float | None) -> float | None:
    if value is not None and not 0 <= value <= 1:
        raise ValueError(f"{name}は0から1の範囲で指定してください: {value}")
    return value


def score_quality_tier(coverage: float) -> str:
    """Classify score coverage at fixed, auditable boundaries."""
    if coverage >= 0.80:
        return "A"
    if coverage >= 0.60:
        return "B"
    if coverage >= 0.40:
        return "C"
    return "D"


def calculate_potential(
    meshes: list[Mesh],
    weights: dict[str, float] | None = None,
    missing_policy: str = "renormalize",
    enabled_features: dict[str, bool] | None = None,
    app_value: str = "custom",
    minimum_score_coverage: float = 0.40,
    required_feature_groups: dict[str, dict[str, list[str]]] | None = None,
) -> None:
    """Calculate an explainable potential score, never a download probability."""
    selected_weights = weights or {
        "target_age_population_index": 0.30,
        "household_composition_index": 0.15,
        "facility_choice_index": 0.20,
        "accessibility_index": 0.15,
        "commercial_concentration_index": 0.20,
    }
    enabled = enabled_features or {name: True for name in SCORE_FEATURES}
    required_groups = required_feature_groups or DEFAULT_REQUIRED_FEATURE_GROUPS
    if missing_policy not in ("renormalize", "strict"):
        raise ValueError("missing_policyはrenormalizeまたはstrictを指定してください")
    if not 0 <= minimum_score_coverage <= 1:
        raise ValueError("minimum_score_coverageは0から1の範囲で指定してください")
    unknown = set(selected_weights) - set(SCORE_FEATURES)
    if unknown:
        raise ValueError(f"未対応のスコア特徴量です: {', '.join(sorted(unknown))}")
    for name in SCORE_FEATURES:
        weight = selected_weights.get(name)
        if enabled.get(name, False) and (weight is None or weight < 0):
            raise ValueError(f"有効特徴量{name}の重みは0以上で指定してください")

    target_counts = [
        mesh.population * mesh.young_adult_ratio
        for mesh in meshes
        if mesh.population is not None and mesh.young_adult_ratio is not None
    ]
    max_target_count = max(target_counts, default=0.0)
    for mesh in meshes:
        target_count = (
            mesh.population * mesh.young_adult_ratio
            if mesh.population is not None and mesh.young_adult_ratio is not None
            else None
        )
        mesh.target_age_population_index = (
            target_count / max_target_count
            if target_count is not None and max_target_count > 0
            else (0.0 if target_count is not None else None)
        )
        mesh.household_composition_index = (
            mesh.household_count / mesh.population
            if mesh.household_count is not None and mesh.population is not None and mesh.population > 0
            else None
        )
        feature_values = {
            "target_age_population_index": mesh.target_age_population_index,
            "household_composition_index": mesh.household_composition_index,
            "facility_choice_index": mesh.facility_choice_index,
            "accessibility_index": mesh.accessibility_index,
            "commercial_concentration_index": mesh.commercial_concentration_index,
        }
        active = [name for name in SCORE_FEATURES if enabled.get(name, False)]
        total_enabled_weight = sum(selected_weights[name] for name in active)
        if total_enabled_weight <= 0:
            raise ValueError("有効特徴量の重み合計は正数である必要があります")
        for name in active:
            _validate_index(name, feature_values[name])
        mesh.used_features = [name for name in active if feature_values[name] is not None]
        mesh.missing_features = [name for name in active if feature_values[name] is None]
        mesh.feature_count_used = len(mesh.used_features)
        mesh.feature_count_enabled = len(active)
        available_weight = sum(selected_weights[name] for name in mesh.used_features)
        mesh.score_coverage = round(available_weight / total_enabled_weight, 6)
        mesh.score_quality_tier = score_quality_tier(mesh.score_coverage)
        mesh.required_groups_passed, mesh.required_groups_missing = _evaluate_required_groups(
            feature_values, required_groups
        )
        mesh.required_feature_gate_passed = not mesh.required_groups_missing
        mesh.used_weights = {}
        mesh.score_contributions = {}
        mesh.score_method = f"regional_features_v1:{app_value}:{missing_policy}"
        mesh.eligible_for_delivery = False
        if missing_policy == "strict" and mesh.missing_features:
            mesh.acquisition_potential_score = None
            continue
        if available_weight <= 0:
            mesh.acquisition_potential_score = None
            continue
        mesh.used_weights = {
            name: round(selected_weights[name] / available_weight, 6)
            for name in mesh.used_features
        }
        mesh.score_contributions = {
            name: round(float(feature_values[name]) * mesh.used_weights[name] * 100, 6)
            for name in mesh.used_features
        }
        raw = sum(feature_values[name] * mesh.used_weights[name] for name in mesh.used_features)  # type: ignore[operator]
        mesh.acquisition_potential_score = round(max(0.0, min(100.0, raw * 100)), 2)
        mesh.eligible_for_delivery = (
            mesh.score_coverage >= minimum_score_coverage
            and mesh.required_feature_gate_passed
        )


def assign_delivery_zones(meshes: list[Mesh], quantile: float) -> float | None:
    if not 0 <= quantile <= 1:
        raise ValueError("high_score_quantileは0から1の範囲で指定してください")
    for mesh in meshes:
        mesh.is_delivery_zone = False
    scores = sorted(
        m.acquisition_potential_score
        for m in meshes
        if m.acquisition_potential_score is not None and m.eligible_for_delivery
    )
    if not scores:
        return None
    index = min(len(scores) - 1, math.ceil(quantile * len(scores)) - 1)
    threshold = scores[max(0, index)]
    for mesh in meshes:
        mesh.is_delivery_zone = (
            mesh.eligible_for_delivery
            and mesh.acquisition_potential_score is not None
            and mesh.acquisition_potential_score >= threshold
        )
    return threshold
