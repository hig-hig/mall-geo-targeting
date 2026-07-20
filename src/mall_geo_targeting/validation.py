"""Preflight validation for manually acquired real-data inputs."""

from __future__ import annotations

import argparse
import json
import logging
import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from .analysis import generate_meshes, join_estat_statistics
from .commercial import load_commercial_geojson
from .config import NEUTRAL_ATTRACTIVENESS_METHOD, load_yaml, mall_from_dict
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
MALL_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


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
    query_bbox = metadata.get("query_bbox")
    if query_bbox is not None and not _valid_bbox(query_bbox):
        _issue(issues, "ERROR", source_name, "query_bboxはWGS84の[西,南,東,北]で指定してください")
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
    duplicates = sorted(identifier for identifier, count in Counter(ids).items() if count > 1)
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


def _bbox_within_margin(
    value: Iterable[float], container: Iterable[float], margin_m: float
) -> bool:
    west, south, east, north = (float(item) for item in container)
    latitude = (south + north) / 2
    latitude_margin = margin_m / 111_320
    longitude_margin = margin_m / (111_320 * math.cos(math.radians(latitude)))
    expanded = (
        west - longitude_margin,
        south - latitude_margin,
        east + longitude_margin,
        north + latitude_margin,
    )
    return _bbox_contains(expanded, value)


def _validate_attractiveness_metadata(
    metadata: dict[str, Any], issues: list[ValidationIssue]
) -> None:
    expected = {
        "size_measure": "gross_leasable_area_m2",
        "attractiveness_method": NEUTRAL_ATTRACTIVENESS_METHOD,
        "attractiveness_formula": "1.0",
        "attractiveness_method_version": "1.0",
    }
    for field, value in expected.items():
        if metadata.get(field) != value:
            _issue(issues, "ERROR", "malls", f"metadataの{field}は{value!r}が必要です")
    if any("attractiveness" in str(value) for value in metadata.get("provisional_fields", [])):
        _issue(issues, "ERROR", "malls", "正式仕様のattractivenessをprovisional_fieldsへ指定できません")
    for field in (
        "huff_size_term",
        "attractiveness_rationale",
        "double_counting_prevention",
        "future_calibration",
    ):
        if not str(metadata.get(field, "")).strip():
            _issue(issues, "ERROR", "malls", f"metadataに{field}の説明が必要です")


def _validate_malls(path: Path, issues: list[ValidationIssue]) -> tuple[float, float] | None:
    try:
        config = load_yaml(path)
        target_value = config["target_mall"]
        competitor_values = config.get("competitor_malls", [])
        all_values = [target_value, *competitor_values]
        methods = {str(value.get("attractiveness_method", "")) for value in all_values}
        if methods != {NEUTRAL_ATTRACTIVENESS_METHOD}:
            _issue(
                issues,
                "ERROR",
                "malls",
                "全登録モールに共通のneutral_non_size_multiplierが必要です",
            )
        target = mall_from_dict(target_value)
        competitors = [mall_from_dict(value) for value in competitor_values]
        malls = [target, *competitors]
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
    if target_value.get("coordinate_status") != "verified":
        _issue(issues, "WARNING", "malls", "対象モールの座標は未検証です")
    required = {
        "id", "name", "latitude", "longitude", "floor_area_m2", "attractiveness",
        "attractiveness_method", "coordinate_status",
    }
    for value, mall in zip(competitor_values, competitors):
        missing = sorted(required - value.keys())
        if missing:
            _issue(issues, "ERROR", "malls", f"{mall.id}の必須項目がありません: {', '.join(missing)}")
        if value.get("coordinate_status") != "verified":
            _issue(issues, "ERROR", "malls", f"{mall.id}のcoordinate_statusがverifiedではありません")
        distance_m = _haversine_m(target.latitude, target.longitude, mall.latitude, mall.longitude)
        if distance_m < 50:
            _issue(issues, "ERROR", "malls", f"{mall.id}の座標が対象モールと異常に近接しています: {distance_m:.1f}m")
    return target.latitude, target.longitude


def _haversine_m(latitude1: float, longitude1: float, latitude2: float, longitude2: float) -> float:
    phi1, phi2 = math.radians(latitude1), math.radians(latitude2)
    delta_phi = math.radians(latitude2 - latitude1)
    delta_lambda = math.radians(longitude2 - longitude1)
    value = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(value))


def validate_competitor_candidates(candidates_path: Path, malls_path: Path) -> list[ValidationIssue]:
    """Validate the candidate ledger and prevent premature competitor registration."""
    issues: list[ValidationIssue] = []
    if not candidates_path.is_file():
        _issue(issues, "ERROR", "competitor_candidates", f"候補台帳がありません: {candidates_path}")
        return issues
    try:
        document = load_yaml(candidates_path)
        mall_config = load_yaml(malls_path)
    except (OSError, TypeError, ValueError) as exc:
        _issue(issues, "ERROR", "competitor_candidates", f"候補台帳を読み込めません: {exc}")
        return issues
    candidates = document.get("competitor_candidates")
    if not isinstance(candidates, list):
        _issue(issues, "ERROR", "competitor_candidates", "competitor_candidatesはリストで指定してください")
        return issues
    candidate_ids: list[str] = []
    by_id: dict[str, dict[str, Any]] = {}
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            _issue(issues, "ERROR", "competitor_candidates", f"候補{index}はマッピングで指定してください")
            continue
        identifier = str(candidate.get("id", ""))
        candidate_ids.append(identifier)
        by_id[identifier] = candidate
        if not MALL_ID_PATTERN.fullmatch(identifier):
            _issue(issues, "ERROR", "competitor_candidates", f"候補IDの形式が不正です: {identifier or '(empty)'}")
        if not str(candidate.get("name", "")).strip():
            _issue(issues, "ERROR", "competitor_candidates", f"{identifier}に名称がありません")
        if not str(candidate.get("address", "")).strip():
            _issue(issues, "ERROR", "competitor_candidates", f"{identifier}に住所がありません")
        try:
            date.fromisoformat(str(candidate.get("retrieved_at", "")))
        except ValueError:
            _issue(issues, "ERROR", "competitor_candidates", f"{identifier}のretrieved_atが不正です")
        facts = candidate.get("confirmed_facts")
        if not isinstance(facts, dict):
            _issue(issues, "ERROR", "competitor_candidates", f"{identifier}のconfirmed_factsが不正です")
            continue
        floor_area = candidate.get("gross_leasable_area_m2")
        if floor_area is not None and (not isinstance(floor_area, (int, float)) or floor_area <= 0):
            _issue(issues, "ERROR", "competitor_candidates", f"{identifier}の総賃貸面積が不正です")
        status = candidate.get("registration_status")
        if status in {"awaiting_coordinate_verification", "registered"} and floor_area is None:
            _issue(issues, "ERROR", "competitor_candidates", f"{identifier}に分析用床面積がありません")
        if status not in {
            "awaiting_coordinate_verification",
            "awaiting_floor_area_and_coordinate_verification",
            "awaiting_floor_area_verification",
            "ready_for_registration",
            "registered",
        }:
            _issue(issues, "ERROR", "competitor_candidates", f"{identifier}のregistration_statusが不正です")
        source_url = candidate.get("source_url")
        if facts and (not isinstance(source_url, str) or not source_url.startswith("https://")):
            _issue(issues, "ERROR", "competitor_candidates", f"{identifier}に確認済み情報のsource_urlがありません")
        if candidate.get("coordinate_status") == "verified":
            if candidate.get("latitude") is None or candidate.get("longitude") is None:
                _issue(issues, "ERROR", "competitor_candidates", f"{identifier}の検証済み座標がありません")
            if not isinstance(candidate.get("coordinate_sources"), list) or len(candidate["coordinate_sources"]) < 2:
                _issue(issues, "ERROR", "competitor_candidates", f"{identifier}の座標参照元が不足しています")
            distance = candidate.get("coordinate_source_distance_m")
            if not isinstance(distance, (int, float)) or not 0 <= distance <= 150:
                _issue(issues, "ERROR", "competitor_candidates", f"{identifier}の参照元間距離が不正です")
    duplicates = sorted({identifier for identifier in candidate_ids if candidate_ids.count(identifier) > 1})
    if duplicates:
        _issue(issues, "ERROR", "competitor_candidates", f"候補IDが重複しています: {', '.join(duplicates)}")
    for registered in mall_config.get("competitor_malls", []):
        identifier = str(registered.get("id", ""))
        candidate = by_id.get(identifier)
        if candidate is not None and (
            candidate.get("registration_status") not in {"ready_for_registration", "registered"}
            or candidate.get("coordinate_status") != "verified"
            or registered.get("coordinate_status") != "verified"
            or candidate.get("latitude") is None
            or candidate.get("longitude") is None
        ):
            _issue(issues, "ERROR", "competitor_candidates", f"座標未確認の候補をcompetitor_mallsへ登録できません: {identifier}")
            continue
        if candidate is not None:
            if registered.get("coordinate_status") != "verified":
                _issue(issues, "ERROR", "competitor_candidates", f"本番競合の座標検証状態が不正です: {identifier}")
            try:
                distance_m = _haversine_m(
                    float(candidate["latitude"]),
                    float(candidate["longitude"]),
                    float(registered["latitude"]),
                    float(registered["longitude"]),
                )
            except (KeyError, TypeError, ValueError):
                _issue(issues, "ERROR", "competitor_candidates", f"本番競合の座標が不正です: {identifier}")
            else:
                if distance_m > 1:
                    _issue(issues, "ERROR", "competitor_candidates", f"候補台帳と本番競合の座標が一致しません: {identifier}")
    return issues


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
        if source_name == "malls":
            _validate_attractiveness_metadata(metadata, issues)
        if str(source_config.get("license_record_name")) not in license_names:
            _issue(issues, "ERROR", source_name, "config/licenses.yamlに対応するライセンス記録がありません")
        if metadata.get("is_sample") is False and not REAL_NAME_PATTERN.match(path.name):
            _issue(issues, "ERROR", source_name, "実データのファイル名が命名規則に一致しません")

    target = _validate_malls(paths["malls"], issues) if paths["malls"].is_file() else None
    issues.extend(
        validate_competitor_candidates(
            project_root / "data" / "raw" / "malls" / "competitor_candidates.yaml",
            paths["malls"],
        )
    )
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
            metadata = metadata_by_source.get(source_name, {})
            acquisition_bbox = metadata.get("query_bbox", metadata.get("coverage_area"))
            if _valid_bbox(acquisition_bbox) and not _bbox_contains(acquisition_bbox, required_bbox):
                _issue(issues, "WARNING" if sample and not require_real else "ERROR", source_name, "GeoJSONが分析半径＋bufferを十分に覆っていません")
            if _valid_bbox(acquisition_bbox) and actual_bbox is not None:
                tolerance_m = float(
                    requirements.get("geospatial_feature_bbox_tolerance_m", 5000)
                )
                if not _bbox_within_margin(actual_bbox, acquisition_bbox, tolerance_m):
                    _issue(
                        issues,
                        "ERROR",
                        source_name,
                        "GeoJSON実座標がmetadataの取得範囲を許容値以上に逸脱しています",
                    )
            del document
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
