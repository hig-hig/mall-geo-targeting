"""Typed domain models."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Mall:
    id: str
    name: str
    latitude: float
    longitude: float
    floor_area_m2: float
    attractiveness: float = 1.0


@dataclass
class Mesh:
    mesh_id: str
    row: int
    column: int
    center_latitude: float
    center_longitude: float
    polygon: list[list[float]]
    population: int | None = None
    young_adult_ratio: float | None = None
    smartphone_affinity: float | None = None
    huff_probability: float | None = None
    acquisition_potential_score: float | None = None
    is_delivery_zone: bool = False
    missing_fields: list[str] = field(default_factory=list)

