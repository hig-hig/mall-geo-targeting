"""Configuration loading and validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import Mall


class ConfigurationError(ValueError):
    """Raised when a configuration is invalid."""


def load_yaml(path: Path) -> dict[str, Any]:
    """Load YAML; JSON-compatible YAML works without optional runtime imports."""
    try:
        import yaml

        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except ModuleNotFoundError:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigurationError(f"設定ファイルを読み込めません: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigurationError(f"設定のルートはマッピングである必要があります: {path}")
    return value


def gross_leasable_area_ratio(floor_area_m2: float, target_floor_area_m2: float) -> float:
    """Calculate provisional attractiveness from gross leasable areas."""
    if floor_area_m2 <= 0 or target_floor_area_m2 <= 0:
        raise ConfigurationError("総賃貸面積は正数である必要があります")
    return floor_area_m2 / target_floor_area_m2


def mall_from_dict(value: dict[str, Any], target_floor_area_m2: float | None = None) -> Mall:
    try:
        floor_area_m2 = float(value["floor_area_m2"])
        attractiveness = float(value.get("attractiveness", 1.0))
        if value.get("attractiveness_method") == "gross_leasable_area_ratio":
            if target_floor_area_m2 is None:
                raise ConfigurationError("面積比の計算には対象モールの総賃貸面積が必要です")
            attractiveness = gross_leasable_area_ratio(floor_area_m2, target_floor_area_m2)
        mall = Mall(
            id=str(value["id"]),
            name=str(value["name"]),
            latitude=float(value["latitude"]),
            longitude=float(value["longitude"]),
            floor_area_m2=floor_area_m2,
            attractiveness=attractiveness,
            app_value=str(value.get("app_value", "coupon")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigurationError(f"モール設定が不正です: {exc}") from exc
    if mall.floor_area_m2 <= 0 or mall.attractiveness <= 0:
        raise ConfigurationError("floor_area_m2とattractivenessは正数である必要があります")
    return mall
