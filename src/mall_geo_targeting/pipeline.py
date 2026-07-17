"""End-to-end orchestration."""

from __future__ import annotations

import logging
from pathlib import Path

from .analysis import assign_delivery_zones, calculate_huff, calculate_potential, generate_meshes, join_estat_statistics, join_population
from .config import load_yaml, mall_from_dict
from .estat import load_estat_csv
from .output import write_outputs

LOGGER = logging.getLogger(__name__)


def run(project_root: Path, data_mode: str | None = None) -> dict[str, object]:
    malls_config = load_yaml(project_root / "config" / "malls.yaml")
    analysis_config = load_yaml(project_root / "config" / "analysis.yaml")
    feature_config = load_yaml(project_root / "config" / "feature_weights.yaml")
    target = mall_from_dict(malls_config["target_mall"])
    competitors = [mall_from_dict(value) for value in malls_config.get("competitor_malls", [])]
    meshes = generate_meshes(target, int(analysis_config["radius_m"]), int(analysis_config["mesh_size_m"]))
    selected_mode = data_mode or str(analysis_config.get("data_mode", "sample"))
    if selected_mode == "sample":
        join_population(meshes, project_root / str(analysis_config["population_path"]))
    elif selected_mode == "estat":
        estat_config = analysis_config.get("estat")
        if not isinstance(estat_config, dict):
            raise ValueError("実データモードにはanalysis.yamlのestat設定が必要です")
        statistics = load_estat_csv(project_root / str(estat_config["path"]), estat_config)
        join_estat_statistics(meshes, statistics)
    else:
        raise ValueError(f"未対応のdata_modeです: {selected_mode!r} (sampleまたはestat)")
    calculate_huff(meshes, target, competitors, float(analysis_config["huff_distance_exponent"]))
    presets = feature_config.get("presets", {})
    if target.app_value not in presets:
        raise ValueError(f"app_valueに対応する重みプリセットがありません: {target.app_value}")
    calculate_potential(
        meshes,
        weights=presets[target.app_value],
        missing_policy=str(feature_config.get("missing_policy", "renormalize")),
        enabled_features=feature_config.get("enabled_features"),
        app_value=target.app_value,
        minimum_score_coverage=float(feature_config.get("minimum_score_coverage", 0.40)),
    )
    threshold = assign_delivery_zones(meshes, float(analysis_config["high_score_quantile"]))
    paths = write_outputs(meshes, target, project_root / str(analysis_config["output_directory"]))
    quality_counts = {
        tier: sum(mesh.score_quality_tier == tier for mesh in meshes)
        for tier in ("A", "B", "C", "D")
    }
    result = {"data_mode": selected_mode, "mesh_count": len(meshes), "scored_count": sum(m.acquisition_potential_score is not None for m in meshes), "eligible_count": sum(m.eligible_for_delivery for m in meshes), "excluded_by_coverage_count": sum(m.acquisition_potential_score is not None and not m.eligible_for_delivery for m in meshes), "quality_counts": quality_counts, "delivery_zone_count": sum(m.is_delivery_zone for m in meshes), "threshold": threshold, "outputs": paths}
    LOGGER.info("パイプライン完了: %s", result)
    return result
