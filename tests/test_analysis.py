from pathlib import Path

import pytest

from mall_geo_targeting.analysis import assign_delivery_zones, calculate_huff, calculate_potential, generate_meshes, join_population
from mall_geo_targeting.models import Mall, Mesh


def mall(identifier: str = "target", longitude: float = 139.0) -> Mall:
    return Mall(identifier, identifier, 35.0, longitude, 10_000, 1.0)


def test_meshes_are_near_target_and_unique() -> None:
    meshes = generate_meshes(mall(), radius_m=500, mesh_size_m=250)
    assert meshes
    assert len({m.mesh_id for m in meshes}) == len(meshes)
    assert all(len(m.polygon) == 5 for m in meshes)


def test_population_join_distinguishes_zero_and_missing(tmp_path: Path) -> None:
    path = tmp_path / "population.csv"
    path.write_text("mesh_id,population,young_adult_ratio,smartphone_affinity\nM_000_000,0,0.2,\n", encoding="utf-8")
    mesh = Mesh("M_000_000", 0, 0, 35, 139, [])
    join_population([mesh], path)
    assert mesh.population == 0
    assert mesh.smartphone_affinity is None
    assert mesh.missing_fields == ["smartphone_affinity"]


def test_huff_probability_is_normalized() -> None:
    mesh = Mesh("x", 0, 0, 35, 139.001, [])
    calculate_huff([mesh], mall(), [mall("other", 139.002)], exponent=2)
    assert mesh.huff_probability == pytest.approx(0.5, rel=0.02)


def test_missing_input_produces_missing_score_but_zero_is_scored() -> None:
    zero = Mesh("zero", 0, 0, 35, 139, [], population=0, young_adult_ratio=0.0, smartphone_affinity=0.0, huff_probability=0.0)
    missing = Mesh("missing", 0, 0, 35, 139, [], population=None, young_adult_ratio=0.2, smartphone_affinity=0.8, huff_probability=0.5)
    calculate_potential([zero, missing])
    assert zero.acquisition_potential_score == 0.0
    assert missing.acquisition_potential_score is None


def test_delivery_zone_ignores_missing_scores() -> None:
    meshes = [Mesh(str(i), 0, 0, 0, 0, [], acquisition_potential_score=score) for i, score in enumerate([10.0, 20.0, 30.0, None])]
    threshold = assign_delivery_zones(meshes, 0.8)
    assert threshold == 30.0
    assert [m.is_delivery_zone for m in meshes] == [False, False, True, False]

