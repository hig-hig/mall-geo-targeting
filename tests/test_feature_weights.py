from pathlib import Path

from mall_geo_targeting.analysis import SCORE_FEATURES
from mall_geo_targeting.config import load_yaml, mall_from_dict


def test_all_app_value_presets_cover_score_features() -> None:
    root = Path(__file__).parents[1]
    config = load_yaml(root / "config" / "feature_weights.yaml")
    assert set(config["presets"]) == {"coupon", "parking", "event", "crm", "tenant_info"}
    for weights in config["presets"].values():
        assert set(weights) == set(SCORE_FEATURES)
        assert abs(sum(weights.values()) - 1.0) < 1e-9


def test_target_mall_selects_existing_app_value_preset() -> None:
    root = Path(__file__).parents[1]
    mall_config = load_yaml(root / "config" / "malls.yaml")
    feature_config = load_yaml(root / "config" / "feature_weights.yaml")
    target = mall_from_dict(mall_config["target_mall"])
    assert target.app_value in feature_config["presets"]
