"""Typed domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


@dataclass(frozen=True)
class Mall:
    id: str
    name: str
    latitude: float
    longitude: float
    floor_area_m2: float
    attractiveness: float = 1.0
    app_value: str = "coupon"
    size_measurement_type: str = "gross_leasable_area"
    size_measurement_label: str = "GLA"
    size_measurement_note: str = ""
    facility_scope: str = ""


class ValueStatus(StrEnum):
    """Meaning of a statistical cell; observed zero is OBSERVED with value 0."""

    OBSERVED = "observed"
    MISSING = "missing"
    SUPPRESSED = "suppressed"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class StatisticalValue:
    value: int | None
    status: ValueStatus
    raw_value: str


@dataclass(frozen=True)
class EstatMeshStatistics:
    standard_mesh_code: str
    total_population: StatisticalValue
    households: StatisticalValue
    age_0_14: StatisticalValue
    age_15_64: StatisticalValue
    age_65_plus: StatisticalValue
    survey_year: int
    table_id: str


@dataclass
class Mesh:
    mesh_id: str
    row: int
    column: int
    center_latitude: float
    center_longitude: float
    polygon: list[list[float]]
    # M_... is this application's delivery-analysis grid. The standard code is
    # a separate Japanese statistical mesh identifier and never replaces it.
    standard_mesh_code: str | None = None
    source_standard_mesh_code: str | None = None
    population: int | None = None
    population_status: ValueStatus | None = None
    household_count: int | None = None
    household_count_status: ValueStatus | None = None
    age_0_14_population: int | None = None
    age_0_14_status: ValueStatus | None = None
    age_15_64_population: int | None = None
    age_15_64_status: ValueStatus | None = None
    age_65_plus_population: int | None = None
    age_65_plus_status: ValueStatus | None = None
    source_survey_year: int | None = None
    source_table_id: str | None = None
    young_adult_ratio: float | None = None
    target_age_population_index: float | None = None
    household_composition_index: float | None = None
    accessibility_index: float | None = None
    road_length_m: float | None = None
    major_road_length_m: float | None = None
    walkable_road_length_m: float | None = None
    nearest_station_distance_m: float | None = None
    nearest_bus_stop_distance_m: float | None = None
    parking_count: int | None = None
    straight_line_distance_to_mall_m: float | None = None
    accessibility_coverage: float | None = None
    accessibility_used_components: list[str] = field(default_factory=list)
    commercial_concentration_index: float | None = None
    retail_count: int | None = None
    supermarket_count: int | None = None
    convenience_store_count: int | None = None
    restaurant_count: int | None = None
    cafe_count: int | None = None
    entertainment_count: int | None = None
    service_count: int | None = None
    office_count: int | None = None
    hotel_count: int | None = None
    commercial_poi_total: int | None = None
    commercial_poi_density: float | None = None
    nearest_commercial_poi_distance_m: float | None = None
    commercial_coverage: float | None = None
    commercial_used_components: list[str] = field(default_factory=list)
    # Deprecated input retained only for backward-compatible CSV ingestion.
    # It is never used by the Step 3 score.
    smartphone_affinity: float | None = None
    huff_probability: float | None = None
    car_choice_index: float | None = None
    walk_choice_index: float | None = None
    bike_choice_index: float | None = None
    facility_choice_index: float | None = None
    facility_choice_used_modes: list[str] = field(default_factory=list)
    facility_choice_used_weights: dict[str, float] = field(default_factory=dict)
    car_availability: float | None = None
    walk_availability: float | None = None
    bike_availability: float | None = None
    acquisition_potential_score: float | None = None
    used_features: list[str] = field(default_factory=list)
    missing_features: list[str] = field(default_factory=list)
    used_weights: dict[str, float] = field(default_factory=dict)
    score_contributions: dict[str, float] = field(default_factory=dict)
    score_method: str | None = None
    score_coverage: float | None = None
    score_quality_tier: str | None = None
    feature_count_used: int = 0
    feature_count_enabled: int = 0
    required_groups_passed: list[str] = field(default_factory=list)
    required_groups_missing: list[str] = field(default_factory=list)
    required_feature_gate_passed: bool = False
    eligible_for_delivery: bool = False
    is_delivery_zone: bool = False
    missing_fields: list[str] = field(default_factory=list)
