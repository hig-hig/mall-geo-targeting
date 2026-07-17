"""End-to-end orchestration."""

from __future__ import annotations

import logging
from pathlib import Path

from .analysis import assign_delivery_zones, calculate_huff, calculate_potential, generate_meshes, join_estat_statistics, join_population, resolve_required_feature_groups
from .config import load_yaml, mall_from_dict
from .commercial import calculate_commercial_concentration, load_commercial_geojson
from .estat import load_estat_csv
from .output import write_outputs
from .osm import LocalProjection, calculate_osm_accessibility, load_osm_geojson
from .validation import warn_for_sample_sources

LOGGER = logging.getLogger(__name__)


def run(project_root: Path, data_mode: str | None = None, accessibility_mode: str | None = None, commercial_mode: str | None = None) -> dict[str, object]:
    data_sources = load_yaml(project_root / "config" / "data_sources.yaml")["sources"]
    malls_config = load_yaml(project_root / str(data_sources["malls"]["path"]))
    analysis_config = load_yaml(project_root / "config" / "analysis.yaml")
    feature_config = load_yaml(project_root / "config" / "feature_weights.yaml")
    target = mall_from_dict(malls_config["target_mall"])
    competitors = [mall_from_dict(value) for value in malls_config.get("competitor_malls", [])]
    meshes = generate_meshes(target, int(analysis_config["radius_m"]), int(analysis_config["mesh_size_m"]))
    selected_mode = data_mode or str(analysis_config.get("data_mode", "sample"))
    selected_source_names = ["malls", "estat" if selected_mode == "estat" else "malls"]
    if selected_mode == "sample":
        LOGGER.warning("sample人口モードは模擬データを使用します。実分析には使用しないでください")
    if selected_mode == "sample":
        join_population(meshes, project_root / str(analysis_config["population_path"]))
    elif selected_mode == "estat":
        estat_config = analysis_config.get("estat")
        if not isinstance(estat_config, dict):
            raise ValueError("実データモードにはanalysis.yamlのestat設定が必要です")
        statistics = load_estat_csv(project_root / str(data_sources["estat"]["path"]), estat_config)
        join_estat_statistics(meshes, statistics)
    else:
        raise ValueError(f"未対応のdata_modeです: {selected_mode!r} (sampleまたはestat)")
    selected_accessibility_mode = accessibility_mode or str(analysis_config.get("accessibility_mode", "sample"))
    if selected_accessibility_mode == "sample":
        LOGGER.warning("sample到達性モードは模擬指数を使用します")
    if selected_accessibility_mode == "osm":
        selected_source_names.append("osm")
    if selected_accessibility_mode == "osm":
        osm_config = load_yaml(project_root / "config" / "osm.yaml")
        accessibility_config = load_yaml(project_root / "config" / "accessibility_weights.yaml")
        projection = LocalProjection(target.latitude, target.longitude)
        osm_data = load_osm_geojson(project_root / str(data_sources["osm"]["path"]), osm_config, projection)
        calculate_osm_accessibility(meshes, target, osm_data, projection, accessibility_config)
    elif selected_accessibility_mode == "none":
        for mesh in meshes:
            mesh.accessibility_index = None
    elif selected_accessibility_mode != "sample":
        raise ValueError(f"未対応のaccessibility_modeです: {selected_accessibility_mode!r} (sample、osm、none)")
    selected_commercial_mode = commercial_mode or str(analysis_config.get("commercial_mode", "sample"))
    if selected_commercial_mode == "sample":
        LOGGER.warning("sample商業モードは模擬指数を使用します")
    if selected_commercial_mode == "file":
        selected_source_names.append("commercial")
    elif selected_commercial_mode == "osm":
        selected_source_names.append("osm")
    if selected_commercial_mode in ("osm", "file"):
        commercial_config = load_yaml(project_root / "config" / "commercial.yaml")
        commercial_weights = load_yaml(project_root / "config" / "commercial_weights.yaml")
        projection = LocalProjection(target.latitude, target.longitude)
        if selected_commercial_mode == "osm":
            osm_config = load_yaml(project_root / "config" / "osm.yaml")
            commercial_path = project_root / str(data_sources["osm"]["path"])
        else:
            commercial_path = project_root / str(data_sources["commercial"]["path"])
        commercial_data = load_commercial_geojson(commercial_path, commercial_config, projection)
        calculate_commercial_concentration(meshes, commercial_data, projection, commercial_weights)
    elif selected_commercial_mode == "none":
        for mesh in meshes:
            mesh.commercial_concentration_index = None
    elif selected_commercial_mode != "sample":
        raise ValueError(f"未対応のcommercial_modeです: {selected_commercial_mode!r} (sample、osm、file、none)")
    warn_for_sample_sources(project_root, dict.fromkeys(selected_source_names))
    calculate_huff(meshes, target, competitors, float(analysis_config["huff_distance_exponent"]))
    presets = feature_config.get("presets", {})
    if target.app_value not in presets:
        raise ValueError(f"app_valueに対応する重みプリセットがありません: {target.app_value}")
    required_groups = resolve_required_feature_groups(
        feature_config.get("required_feature_groups", {}),
        feature_config.get("required_feature_group_overrides"),
        target.app_value,
    )
    calculate_potential(
        meshes,
        weights=presets[target.app_value],
        missing_policy=str(feature_config.get("missing_policy", "renormalize")),
        enabled_features=feature_config.get("enabled_features"),
        app_value=target.app_value,
        minimum_score_coverage=float(feature_config.get("minimum_score_coverage", 0.40)),
        required_feature_groups=required_groups,
    )
    threshold = assign_delivery_zones(meshes, float(analysis_config["high_score_quantile"]))
    paths = write_outputs(meshes, target, project_root / str(analysis_config["output_directory"]))
    quality_counts = {
        tier: sum(mesh.score_quality_tier == tier for mesh in meshes)
        for tier in ("A", "B", "C", "D")
    }
    accessibility_coverages = [m.accessibility_coverage for m in meshes if m.accessibility_coverage is not None]
    commercial_coverages = [m.commercial_coverage for m in meshes if m.commercial_coverage is not None]
    scored = [m for m in meshes if m.acquisition_potential_score is not None]
    coverage_eligible_count = sum(m.score_coverage is not None and m.score_coverage >= float(feature_config.get("minimum_score_coverage", 0.40)) for m in scored)
    result = {"data_mode": selected_mode, "accessibility_mode": selected_accessibility_mode, "commercial_mode": selected_commercial_mode, "mesh_count": len(meshes), "scored_count": len(scored), "coverage_eligible_count": coverage_eligible_count, "required_gate_eligible_count": sum(m.required_feature_gate_passed for m in scored), "demographic_missing_count": sum("demographic" in m.required_groups_missing for m in scored), "eligible_count": sum(m.eligible_for_delivery for m in meshes), "excluded_by_coverage_count": sum(m.score_coverage is not None and m.score_coverage < float(feature_config.get("minimum_score_coverage", 0.40)) for m in scored), "excluded_by_required_gate_count": sum(not m.required_feature_gate_passed for m in scored), "quality_counts": quality_counts, "accessibility_coverage_count": len(accessibility_coverages), "mean_accessibility_coverage": round(sum(accessibility_coverages) / len(accessibility_coverages), 6) if accessibility_coverages else None, "commercial_coverage_count": len(commercial_coverages), "mean_commercial_coverage": round(sum(commercial_coverages) / len(commercial_coverages), 6) if commercial_coverages else None, "delivery_zone_count": sum(m.is_delivery_zone for m in meshes), "threshold": threshold, "outputs": paths}
    LOGGER.info("パイプライン完了: %s", result)
    return result
