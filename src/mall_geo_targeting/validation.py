"""Preflight validation for manually acquired real-data inputs."""

from __future__ import annotations

import argparse
import json
import logging
import math
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from .analysis import generate_meshes, join_estat_statistics
from .commercial import load_commercial_geojson
from .config import load_yaml, mall_from_dict
from .estat import load_estat_csv
from .osm import LocalProjection, load_osm_geojson

LOGGER = logging.getLogger(__name__)
METADATA_FIELDS = (
    "dataset_name",
    "source",
    "source_url",
    "license",
    "commercial_use_allowed",
    "attribution_required",
    "retrieved_at",
    "coverage_area",
    "processing",
    "is_sample",
)
REAL_NAME_PATTERN = re.compile(
    r"^[a-z0-9]+(?:-[a-z0-9]+)*__(?:mall-profile|estat-population-mesh|osm-features|commercial-poi)__\d{8}\.(?:yaml|csv|geojson)$"
)


@dataclass(frozen=True)
class ValidationIssue:
    severity: str
    source: str
    message: str


@dataclass(frozen=True)
class ValidationReport:
    issues: list[ValidationIssue]

    @property
    def errors(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "ERROR"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "WARNING"]


def _issue(issues: list[ValidationIssue], severity: str, source: str, message: str) -> None:
    issues.append(ValidationIssue(severity, source, message))


def _validate_metadata(
    source_name: str,
    metadata: dict[str, Any],
    require_real: bool,
    issues: list[ValidationIssue],
) -> None:
    missing = [field for field in METADATA_FIELDS if field not in metadata]
    if missing:
        _issue(issues, "ERROR", source_name, f"metadata必須項目がありません: {', '.join(missing)}")
        return
    try:
        date.fromisoformat(str(metadata["retrieved_at"]))
    except ValueError:
        _issue(issues, "ERROR", source_name, "retrieved_atはYYYY-MM-DDで指定してください")
    if not isinstance(metadata["commercial_use_allowed"], bool):
        _issue(issues, "ERROR", source_name, "commercial_use_allowedは真偽値で指定してください")
    if not isinstance(metadata["attribution_required"], bool):
        _issue(issues, "ERROR", source_name, "attribution_requiredは真偽値で指定してください")
    bbox = metadata["coverage_area"]
    if not _valid_bbox(bbox):
        _issue(issues, "ERROR", source_name, "coverage_areaはWGS84の[西,南,東,北]で指定してください")
    if metadata["is_sample"] is True:
        severity = "ERROR" if require_real else "WARNING"
        _issue(issues, severity, source_name, "サンプルデータです。実分析には使用できません")
    elif metadata["is_sample"] is not False:
        _issue(issues, "ERROR", source_name, "is_sampleは真偽値で指定してください")
    if metadata["commercial_use_allowed"] is not True:
        _issue(issues, "ERROR" if require_real else "WARNING", source_name, "商用利用可能であることを確認できません")
    provisional_fields = metadata.get("provisional_fields", [])
    if provisional_fields:
        _issue(
            issues,
            "WARNING",
            source_name,
            f"暫定値を人手で再確認してください: {', '.join(str(value) for value in provisional_fields)}",
        )


def _valid_bbox(value: Any) -> bool:
    if not isinstance(value, list) or len(value) != 4:
        return False
    try:
        west, south, east, north = (float(item) for item in value)
    except (TypeError, ValueError):
        return False
    return -180 <= west < east <= 180 and -90 <= south < north <= 90


def _coordinates(geometry: dict[str, Any]) -> Iterable[tuple[float, float]]:
    def walk(value: Any) -> Iterable[tuple[float, float]]:
        if isinstance(value, list) and len(value) >= 2 and all(isinstance(item, (int, float)) for item in value[:2]):
            yield float(value[0]), float(value[1])
        elif isinstance(value, list):
            for child in value:
                yield from walk(child)

    yield from walk(geometry.get("coordinates"))


def _load_geojson(path: Path, source_name: str, issues: list[ValidationIssue]) -> dict[str, Any] | None:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        _issue(issues, "ERROR", source_name, f"GeoJSONを読み込めません: {exc}")
        return None
    if document.get("type") != "FeatureCollection" or not isinstance(document.get("features"), list):
        _issue(issues, "ERROR", source_name, "GeoJSONはFeatureCollectionである必要があります")
        return None
    return document


def _validate_geojson_common(
    source_name: str,
    document: dict[str, Any],
    require_ids: bool,
    issues: list[ValidationIssue],
) -> tuple[float, float, float, float] | None:
    ids: list[str] = []
    coordinates: list[tuple[float, float]] = []
    missing_id_count = 0
    for index, feature in enumerate(document["features"]):
        identifier = feature.get("id")
        if identifier is None:
            missing_id_count += 1
        else:
            ids.append(str(identifier))
        geometry = feature.get("geometry")
        if not isinstance(geometry, dict):
            _issue(issues, "ERROR", source_name, f"Feature {index}にgeometryがありません")
            continue
        coordinates.extend(_coordinates(geometry))
    duplicates = sorted({identifier for identifier in ids if ids.count(identifier) > 1})
    if duplicates:
        _issue(issues, "ERROR", source_name, f"Feature IDが重複しています: {', '.join(duplicates)}")
    if missing_id_count:
        _issue(
            issues,
            "ERROR" if require_ids else "WARNING",
            source_name,
            f"Feature IDがない地物が{missing_id_count}件あります",
        )
    invalid = [(lon, lat) for lon, lat in coordinates if not -180 <= lon <= 180 or not -90 <= lat <= 90]
    if invalid:
        _issue(issues, "ERROR", source_name, f"緯度経度範囲外の座標が{len(invalid)}件あります")
    if not coordinates:
        _issue(issues, "ERROR", source_name, "座標を含む地物がありません")
        return None
    return (
        min(point[0] for point in coordinates),
        min(point[1] for point in coordinates),
        max(point[0] for point in coordinates),
        max(point[1] for point in coordinates),
    )


def _required_bbox(latitude: float, longitude: float, radius_m: float) -> tuple[float, float, float, float]:
    latitude_delta = radius_m / 111_320
    longitude_delta = radius_m / (111_320 * math.cos(math.radians(latitude)))
    return longitude - longitude_delta, latitude - latitude_delta, longitude + longitude_delta, latitude + latitude_delta


def _bbox_contains(container: Iterable[float], required: Iterable[float]) -> bool:
    west, south, east, north = (float(item) for item in container)
    req_west, req_south, req_east, req_north = (float(item) for item in required)
    return west <= req_west and south <= req_south and east >= req_east and north >= req_north


def _validate_malls(path: Path, issues: list[ValidationIssue]) -> tuple[float, float] | None:
    try:
        config = load_yaml(path)
        values = [config["target_mall"], *config.get("competitor_malls", [])]
        malls = [mall_from_dict(value) for value in values]
    except (OSError, KeyError, TypeError, ValueError) as exc:
        _issue(issues, "ERROR", "malls", f"モール設定が不正です: {exc}")
        return None
    ids = [mall.id for mall in malls]
    duplicates = sorted({identifier for identifier in ids if ids.count(identifier) > 1})
    if duplicates:
        _issue(issues, "ERROR", "malls", f"モールIDが重複しています: {', '.join(duplicates)}")
    for mall in malls:
        if not -90 <= mall.latitude <= 90 or not -180 <= mall.longitude <= 180:
            _issue(issues, "ERROR", "malls", f"{mall.id}の緯度経度が範囲外です")
    if "app_value" not in config["target_mall"]:
        _issue(issues, "ERROR", "malls", "対象モールにapp_valueがありません")
    target = malls[0]
    return target.latitude, target.longitude


def validate_inputs(project_root: Path, require_real: bool = False) -> ValidationReport:
    issues: list[ValidationIssue] = []
    registry = load_yaml(project_root / "config" / "data_sources.yaml")
    requirements = registry.get("real_data_requirements", {})
    licenses = load_yaml(project_root / "config" / "licenses.yaml")
    license_names = {str(item.get("name")) for item in licenses.get("datasets", [])}
    sources = registry.get("sources")
    if not isinstance(sources, dict) or set(sources) != {"malls", "estat", "osm", "commercial"}:
        return ValidationReport([ValidationIssue("ERROR", "registry", "data_sources.yamlには4データソースが必要です")])
    metadata_by_source: dict[str, dict[str, Any]] = {}
    paths: dict[str, Path] = {}
    for source_name, source_config in sources.items():
        path = project_root / str(source_config["path"])
        metadata_path = project_root / str(source_config["metadata_path"])
        paths[source_name] = path
        if not path.is_file():
            _issue(issues, "ERROR", source_name, f"入力ファイルがありません: {path}")
        if not metadata_path.is_file():
            _issue(issues, "ERROR", source_name, f"metadataがありません: {metadata_path}")
            continue
        try:
            metadata = load_yaml(metadata_path)
        except ValueError as exc:
            _issue(issues, "ERROR", source_name, f"metadataを読み込めません: {exc}")
            continue
        metadata_by_source[source_name] = metadata
        _validate_metadata(source_name, metadata, require_real, issues)
        if str(source_config.get("license_record_name")) not in license_names:
            _issue(issues, "ERROR", source_name, "config/licenses.yamlに対応するライセンス記録がありません")
        if metadata.get("is_sample") is False and not REAL_NAME_PATTERN.match(path.name):
            _issue(issues, "ERROR", source_name, "実データのファイル名が命名規則に一致しません")

    target = _validate_malls(paths["malls"], issues) if paths["malls"].is_file() else None
    analysis_config = load_yaml(project_root / "config" / "analysis.yaml")
    mall_document = load_yaml(paths["malls"]) if paths["malls"].is_file() else {}
    mall_analysis = mall_document.get("analysis", {})
    analysis_radius_m = int(mall_analysis.get("radius_m", analysis_config["radius_m"]))
    target_mall = None
    if target is not None:
        target_mall = mall_from_dict(load_yaml(paths["malls"])["target_mall"])
    if paths["estat"].is_file() and target_mall is not None:
        try:
            statistics = load_estat_csv(paths["estat"], analysis_config["estat"])
            meshes = generate_meshes(target_mall, analysis_radius_m, int(analysis_config["mesh_size_m"]))
            join_estat_statistics(meshes, statistics)
            coverage_ratio = sum(mesh.source_standard_mesh_code is not None for mesh in meshes) / len(meshes)
            minimum = float(requirements.get("minimum_estat_mesh_coverage_ratio", 0.80))
            if coverage_ratio < minimum:
                sample = metadata_by_source.get("estat", {}).get("is_sample") is True
                _issue(issues, "WARNING" if sample and not require_real else "ERROR", "estat", f"分析メッシュcoverageが不足しています: {coverage_ratio:.1%} < {minimum:.1%}")
        except (KeyError, TypeError, ValueError) as exc:
            _issue(issues, "ERROR", "estat", str(exc))

    if target is not None:
        buffer_m = float(mall_analysis.get("geospatial_buffer_m", requirements.get("geospatial_coverage_buffer_m", 1000)))
        required_bbox = _required_bbox(target[0], target[1], analysis_radius_m + buffer_m)
        projection = LocalProjection(target[0], target[1])
        for source_name in ("osm", "commercial"):
            if not paths[source_name].is_file():
                continue
            document = _load_geojson(paths[source_name], source_name, issues)
            if document is None:
                continue
            sample = metadata_by_source.get(source_name, {}).get("is_sample") is True
            actual_bbox = _validate_geojson_common(
                source_name,
                document,
                bool(requirements.get("require_feature_ids", True)) and (require_real or not sample),
                issues,
            )
            if actual_bbox is not None and not _bbox_contains(actual_bbox, required_bbox):
                _issue(issues, "WARNING" if sample and not require_real else "ERROR", source_name, "GeoJSONが分析半径＋bufferを十分に覆っていません")
            declared_bbox = metadata_by_source.get(source_name, {}).get("coverage_area")
            if _valid_bbox(declared_bbox) and actual_bbox is not None and not _bbox_contains(declared_bbox, actual_bbox):
                _issue(issues, "ERROR", source_name, "metadataのcoverage_areaが実座標範囲を含んでいません")
            try:
                if source_name == "osm":
                    load_osm_geojson(paths[source_name], load_yaml(project_root / "config" / "osm.yaml"), projection)
                else:
                    load_commercial_geojson(paths[source_name], load_yaml(project_root / "config" / "commercial.yaml"), projection)
            except ValueError as exc:
                _issue(issues, "ERROR", source_name, str(exc))
    return ValidationReport(issues)


def warn_for_sample_sources(project_root: Path, source_names: Iterable[str]) -> None:
    """Log a prominent warning whenever configured sample inputs are selected."""
    try:
        registry = load_yaml(project_root / "config" / "data_sources.yaml")
        for source_name in source_names:
            source = registry["sources"][source_name]
            metadata = load_yaml(project_root / str(source["metadata_path"]))
            if metadata.get("is_sample") is True:
                LOGGER.warning("%sはサンプルデータです: %s", source_name, source["path"])
    except (OSError, KeyError, TypeError, ValueError) as exc:
        LOGGER.warning("データソースmetadataを確認できません: %s", exc)


def main() -> int:
    parser = argparse.ArgumentParser(description="実データ投入前の入力検査")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--require-real", action="store_true", help="サンプル・範囲不足・ID不足をエラーにする")
    args = parser.parse_args()
    try:
        report = validate_inputs(args.project_root.resolve(), require_real=args.require_real)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        print(f"ERROR registry: {exc}")
        return 1
    for issue in report.issues:
        print(f"{issue.severity} {issue.source}: {issue.message}")
    print(f"検査完了: errors={len(report.errors)} warnings={len(report.warnings)}")
    return 1 if report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
