"""Configuration loading and validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import Mall

NEUTRAL_ATTRACTIVENESS_METHOD = "neutral_non_size_multiplier"


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


def mall_from_dict(value: dict[str, Any]) -> Mall:
    try:
        floor_area_m2 = float(value["floor_area_m2"])
        method = str(value["attractiveness_method"])
        if method != NEUTRAL_ATTRACTIVENESS_METHOD:
            raise ConfigurationError(f"未対応のattractiveness_methodです: {method}")
        if float(value["attractiveness"]) != 1.0:
            raise ConfigurationError("neutral_non_size_multiplierのattractivenessは1.0が必要です")
        mall = Mall(
            id=str(value["id"]),
            name=str(value["name"]),
            latitude=float(value["latitude"]),
            longitude=float(value["longitude"]),
            floor_area_m2=floor_area_m2,
            attractiveness=1.0,
            app_value=str(value.get("app_value", "coupon")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigurationError(f"モール設定が不正です: {exc}") from exc
    if mall.floor_area_m2 <= 0 or mall.attractiveness <= 0:
        raise ConfigurationError("floor_area_m2とattractivenessは正数である必要があります")
    return mall
