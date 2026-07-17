from pathlib import Path

import pytest

from mall_geo_targeting.analysis import assign_delivery_zones, calculate_huff, calculate_potential, generate_meshes, join_population, score_quality_tier
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
    assert mesh.missing_fields == [
        "household_count",
        "accessibility_index",
        "commercial_concentration_index",
    ]


def test_huff_probability_is_normalized() -> None:
    mesh = Mesh("x", 0, 0, 35, 139.001, [])
    calculate_huff([mesh], mall(), [mall("other", 139.002)], exponent=2)
    assert mesh.huff_probability == pytest.approx(0.5, rel=0.02)


def test_renormalize_scores_available_features_and_zero_is_observed() -> None:
    zero = Mesh("zero", 0, 0, 35, 139, [], population=0, young_adult_ratio=0.0, smartphone_affinity=0.0, huff_probability=0.0)
    missing = Mesh("missing", 0, 0, 35, 139, [], population=None, young_adult_ratio=0.2, smartphone_affinity=0.8, huff_probability=0.5)
    calculate_potential([zero, missing])
    assert zero.acquisition_potential_score == 0.0
    assert missing.acquisition_potential_score == 50.0
    assert missing.used_features == ["huff_visit_probability"]
    assert missing.used_weights == {"huff_visit_probability": 1.0}
    assert missing.score_coverage == 0.20
    assert missing.score_quality_tier == "D"
    assert missing.feature_count_used == 1
    assert missing.feature_count_enabled == 5
    assert not missing.eligible_for_delivery


def test_strict_mode_keeps_score_missing_when_an_enabled_feature_is_missing() -> None:
    mesh = Mesh("missing", 0, 0, 35, 139, [], population=100, young_adult_ratio=0.2, huff_probability=0.5)
    calculate_potential([mesh], missing_policy="strict")
    assert mesh.acquisition_potential_score is None
    assert "accessibility_index" in mesh.missing_features
    assert mesh.used_weights == {}


def test_smartphone_affinity_does_not_affect_score() -> None:
    common = dict(
        population=100,
        young_adult_ratio=0.3,
        household_count=50,
        huff_probability=0.6,
        accessibility_index=0.7,
        commercial_concentration_index=0.8,
    )
    low = Mesh("low", 0, 0, 35, 139, [], smartphone_affinity=0.0, **common)
    high = Mesh("high", 0, 0, 35, 139, [], smartphone_affinity=1.0, **common)
    calculate_potential([low, high])
    assert low.acquisition_potential_score == high.acquisition_potential_score
    assert "smartphone_affinity" not in low.used_features
    assert sum(low.used_weights.values()) == pytest.approx(1.0)


def test_delivery_zone_ignores_missing_scores() -> None:
    meshes = [Mesh(str(i), 0, 0, 0, 0, [], acquisition_potential_score=score, eligible_for_delivery=score is not None) for i, score in enumerate([10.0, 20.0, 30.0, None])]
    threshold = assign_delivery_zones(meshes, 0.8)
    assert threshold == 30.0
    assert [m.is_delivery_zone for m in meshes] == [False, False, True, False]


def test_coupon_demographics_and_huff_have_coverage_065() -> None:
    mesh = Mesh(
        "demographic",
        0,
        0,
        35,
        139,
        [],
        population=100,
        young_adult_ratio=0.3,
        household_count=50,
        huff_probability=0.6,
    )
    calculate_potential([mesh], app_value="coupon")
    assert mesh.score_coverage == 0.65
    assert mesh.score_quality_tier == "B"
    assert mesh.feature_count_used == 3
    assert mesh.feature_count_enabled == 5
    assert mesh.eligible_for_delivery


def test_huff_only_score_is_auditable_but_never_a_delivery_zone() -> None:
    huff_only = Mesh("huff", 0, 0, 35, 139, [], huff_probability=1.0)
    complete = Mesh(
        "complete",
        0,
        0,
        35,
        139,
        [],
        population=100,
        young_adult_ratio=0.3,
        household_count=50,
        huff_probability=0.5,
        accessibility_index=0.5,
        commercial_concentration_index=0.5,
    )
    calculate_potential([huff_only, complete], minimum_score_coverage=0.40)
    assert huff_only.acquisition_potential_score == 100.0
    assert huff_only.score_coverage == 0.20
    assert not huff_only.eligible_for_delivery
    assign_delivery_zones([huff_only, complete], 0.0)
    assert not huff_only.is_delivery_zone
    assert complete.is_delivery_zone


@pytest.mark.parametrize(
    ("coverage", "tier"),
    [(1.0, "A"), (0.80, "A"), (0.79, "B"), (0.60, "B"), (0.59, "C"), (0.40, "C"), (0.39, "D"), (0.0, "D")],
)
def test_score_quality_tier_boundaries(coverage: float, tier: str) -> None:
    assert score_quality_tier(coverage) == tier
