from pathlib import Path

import pytest

from mall_geo_targeting.analysis import assign_delivery_zones, calculate_huff, calculate_potential, calculate_transport_choice_indices, generate_meshes, join_population, mode_availability, resolve_required_feature_groups, score_quality_tier
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


def test_huff_uses_gross_leasable_area_linearly() -> None:
    mesh = Mesh("x", 0, 0, 35, 139.001, [])
    small = Mall("small", "small", 35, 139.0, 10_000, 1.0)
    large = Mall("large", "large", 35, 139.002, 20_000, 1.0)
    calculate_huff([mesh], small, [large], exponent=2)
    assert mesh.huff_probability == pytest.approx(1 / 3, rel=0.02)


def test_huff_applies_same_rule_when_target_and_competitor_are_swapped() -> None:
    point = (35, 139.001)
    small = Mall("small", "small", 35, 139.0, 10_000, 1.0)
    large = Mall("large", "large", 35, 139.002, 20_000, 1.0)
    small_target = Mesh("small-target", 0, 0, *point, [])
    large_target = Mesh("large-target", 0, 0, *point, [])
    calculate_huff([small_target], small, [large], exponent=2)
    calculate_huff([large_target], large, [small], exponent=2)
    assert small_target.huff_probability + large_target.huff_probability == pytest.approx(1.0)


def test_huff_is_invariant_to_common_attractiveness_multiplier() -> None:
    point = (35, 139.001)
    baseline = Mesh("baseline", 0, 0, *point, [])
    scaled = Mesh("scaled", 0, 0, *point, [])
    calculate_huff(
        [baseline],
        Mall("a", "a", 35, 139.0, 10_000, 1.0),
        [Mall("b", "b", 35, 139.002, 20_000, 1.0)],
        exponent=2,
    )
    calculate_huff(
        [scaled],
        Mall("a", "a", 35, 139.0, 10_000, 3.0),
        [Mall("b", "b", 35, 139.002, 20_000, 3.0)],
        exponent=2,
    )
    assert scaled.huff_probability == pytest.approx(baseline.huff_probability)


def test_additional_competitor_reduces_target_probability_and_order_is_irrelevant() -> None:
    point = (35.0, 139.001)
    target = Mall("target", "target", 35.0, 139.0, 78_000, 1.0)
    first = Mall("first", "first", 35.0, 139.002, 63_000, 1.0)
    added = Mall("added", "added", 35.0, 139.003, 59_747, 1.0)
    baseline = Mesh("baseline", 0, 0, *point, [])
    ordered = Mesh("ordered", 0, 0, *point, [])
    reversed_order = Mesh("reversed", 0, 0, *point, [])
    calculate_huff([baseline], target, [first], exponent=2)
    calculate_huff([ordered], target, [first, added], exponent=2)
    calculate_huff([reversed_order], target, [added, first], exponent=2)
    assert ordered.huff_probability <= baseline.huff_probability
    assert reversed_order.huff_probability == pytest.approx(ordered.huff_probability)


def test_competitor_outside_analysis_radius_still_enters_huff_denominator() -> None:
    target = Mall("target", "target", 35.0, 139.0, 78_000, 1.0)
    outside = Mall("outside", "outside", 35.2, 139.0, 59_747, 1.0)
    mesh = Mesh("mesh", 0, 0, 35.0, 139.001, [])
    calculate_huff([mesh], target, [outside], exponent=2)
    assert mesh.huff_probability is not None
    assert 0 < mesh.huff_probability < 1


def test_four_mall_huff_probabilities_sum_to_one() -> None:
    point = (35.72, 139.36)
    malls = [
        Mall("target", "target", 35.74639, 139.38475, 78_000, 1.0),
        Mall("tachikawa", "tachikawa", 35.71238, 139.4174, 63_000, 1.0),
        Mall("hinode", "hinode", 35.7348, 139.27524, 64_000, 1.0),
        Mall("moritown", "moritown", 35.71364, 139.36306, 59_747, 1.0),
    ]
    probabilities = []
    for target in malls:
        mesh = Mesh(target.id, 0, 0, *point, [])
        calculate_huff([mesh], target, [mall for mall in malls if mall is not target], exponent=2)
        probabilities.append(mesh.huff_probability)
    assert sum(value for value in probabilities if value is not None) == pytest.approx(1.0)


def _transport_config() -> dict[str, object]:
    return {
        "modes": {
            "car": {"enabled": True, "beta": 2.0, "minimum_distance_m": 1.0, "availability": {"type": "no_hard_limit"}},
            "walk": {"enabled": True, "beta": 2.5, "minimum_distance_m": 1.0, "availability": {"type": "linear_decay", "full_availability_until_m": 1000, "zero_availability_from_m": 4000}},
            "bike": {"enabled": True, "beta": 2.2, "minimum_distance_m": 1.0, "availability": {"type": "linear_decay", "full_availability_until_m": 3000, "zero_availability_from_m": 10000}},
        }
    }


def test_mode_availability_boundaries_are_explicit_scenarios() -> None:
    linear = {"type": "linear_decay", "full_availability_until_m": 1000, "zero_availability_from_m": 4000}
    assert mode_availability(500, linear) == 1.0
    assert mode_availability(2500, linear) == pytest.approx(0.5)
    assert mode_availability(4000, linear) == 0.0
    assert mode_availability(100_000, {"type": "no_hard_limit"}) == 1.0


def test_transport_choice_indices_are_display_only_and_do_not_change_existing_results() -> None:
    target = Mall("target", "target", 35.0, 139.0, 78_000, 1.0)
    competitors = [Mall("other", "other", 35.0, 139.02, 63_000, 1.0)]
    mesh = Mesh("mesh", 0, 0, 35.0, 139.005, [], population=100, young_adult_ratio=0.3, household_count=50, accessibility_index=0.7, commercial_concentration_index=0.8)
    calculate_huff([mesh], target, competitors, exponent=2.0)
    calculate_potential([mesh])
    before = (mesh.huff_probability, mesh.acquisition_potential_score, mesh.eligible_for_delivery)
    calculate_transport_choice_indices([mesh], target, competitors, _transport_config())
    assert (mesh.huff_probability, mesh.acquisition_potential_score, mesh.eligible_for_delivery) == before
    assert all(0 <= value <= 1 for value in (mesh.car_choice_index, mesh.walk_choice_index, mesh.bike_choice_index) if value is not None)
    assert not {"car_choice_index", "walk_choice_index", "bike_choice_index"} & set(mesh.score_contributions)


def test_transport_choice_is_independent_of_competitor_order() -> None:
    target = Mall("target", "target", 35.0, 139.0, 78_000, 1.0)
    competitors = [Mall("a", "a", 35.0, 139.02, 63_000, 1.0), Mall("b", "b", 35.02, 139.0, 64_000, 1.0)]
    first = Mesh("first", 0, 0, 35.005, 139.005, [])
    second = Mesh("second", 0, 0, 35.005, 139.005, [])
    calculate_transport_choice_indices([first], target, competitors, _transport_config())
    calculate_transport_choice_indices([second], target, list(reversed(competitors)), _transport_config())
    assert (first.car_choice_index, first.walk_choice_index, first.bike_choice_index) == pytest.approx((second.car_choice_index, second.walk_choice_index, second.bike_choice_index))


def test_transport_choice_is_missing_when_no_mall_is_available() -> None:
    target = Mall("target", "target", 35.0, 139.0, 78_000, 1.0)
    mesh = Mesh("far", 0, 0, 36.0, 140.0, [])
    calculate_transport_choice_indices([mesh], target, [], _transport_config())
    assert mesh.car_choice_index == 1.0
    assert mesh.walk_choice_index is None
    assert mesh.bike_choice_index is None
    assert mesh.walk_availability == 0.0
    assert mesh.bike_availability == 0.0


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


def test_score_contributions_sum_to_unchanged_score() -> None:
    mesh = Mesh(
        "contributions",
        0,
        0,
        35,
        139,
        [],
        population=100,
        young_adult_ratio=0.3,
        household_count=50,
        huff_probability=0.6,
        accessibility_index=0.7,
        commercial_concentration_index=0.8,
    )
    calculate_potential([mesh])
    score = mesh.acquisition_potential_score
    assert score is not None
    assert sum(mesh.score_contributions.values()) == pytest.approx(score, abs=0.01)
    assert set(mesh.score_contributions) == set(mesh.used_features)


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
    assert not mesh.eligible_for_delivery
    assert mesh.required_groups_passed == ["demographic", "mall_relationship"]
    assert mesh.required_groups_missing == ["context"]


def test_huff_accessibility_and_commercial_without_demographics_is_not_eligible() -> None:
    mesh = Mesh("no-demographics", 0, 0, 35, 139, [], huff_probability=0.7, accessibility_index=0.8, commercial_concentration_index=0.9)
    calculate_potential([mesh], app_value="coupon")
    assert mesh.acquisition_potential_score is not None
    assert mesh.score_coverage == 0.55
    assert mesh.required_groups_missing == ["demographic"]
    assert not mesh.required_feature_gate_passed
    assert not mesh.eligible_for_delivery


@pytest.mark.parametrize("context_values", [{"accessibility_index": 0.8}, {"commercial_concentration_index": 0.8}])
def test_demographics_huff_and_either_context_can_be_eligible(context_values: dict[str, float]) -> None:
    mesh = Mesh("eligible", 0, 0, 35, 139, [], population=100, young_adult_ratio=0.3, huff_probability=0.7, **context_values)
    calculate_potential([mesh], app_value="coupon")
    assert mesh.acquisition_potential_score is not None
    assert mesh.required_groups_missing == []
    assert mesh.required_feature_gate_passed
    assert mesh.eligible_for_delivery


def test_app_value_override_can_relax_demographic_group() -> None:
    base = {
        "demographic": {"require_any": ["target_age_population_index"]},
        "mall_relationship": {"require_all": ["huff_visit_probability"]},
        "context": {"require_any": ["accessibility_index"]},
    }
    overrides = {
        "parking": {
            "replace": True,
            "groups": {
                "mall_relationship": {"require_all": ["huff_visit_probability"]},
                "context": {"require_any": ["accessibility_index"]},
            },
        }
    }
    groups = resolve_required_feature_groups(base, overrides, "parking")
    mesh = Mesh("parking", 0, 0, 35, 139, [], huff_probability=0.7, accessibility_index=0.8)
    weights = {
        "target_age_population_index": 0.15,
        "household_composition_index": 0.20,
        "huff_visit_probability": 0.20,
        "accessibility_index": 0.35,
        "commercial_concentration_index": 0.10,
    }
    calculate_potential([mesh], weights=weights, app_value="parking", required_feature_groups=groups)
    assert mesh.required_feature_gate_passed
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
