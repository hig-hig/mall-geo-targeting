"""End-to-end orchestration."""

from __future__ import annotations

import logging
from pathlib import Path

from .analysis import assign_delivery_zones, calculate_huff, calculate_potential, generate_meshes, join_population
from .config import load_yaml, mall_from_dict
from .output import write_outputs

LOGGER = logging.getLogger(__name__)


def run(project_root: Path) -> dict[str, object]:
    malls_config = load_yaml(project_root / "config" / "malls.yaml")
    analysis_config = load_yaml(project_root / "config" / "analysis.yaml")
    target = mall_from_dict(malls_config["target_mall"])
    competitors = [mall_from_dict(value) for value in malls_config.get("competitor_malls", [])]
    meshes = generate_meshes(target, int(analysis_config["radius_m"]), int(analysis_config["mesh_size_m"]))
    join_population(meshes, project_root / str(analysis_config["population_path"]))
    calculate_huff(meshes, target, competitors, float(analysis_config["huff_distance_exponent"]))
    calculate_potential(meshes)
    threshold = assign_delivery_zones(meshes, float(analysis_config["high_score_quantile"]))
    paths = write_outputs(meshes, target, project_root / str(analysis_config["output_directory"]))
    result = {"mesh_count": len(meshes), "scored_count": sum(m.acquisition_potential_score is not None for m in meshes), "delivery_zone_count": sum(m.is_delivery_zone for m in meshes), "threshold": threshold, "outputs": paths}
    LOGGER.info("パイプライン完了: %s", result)
    return result

