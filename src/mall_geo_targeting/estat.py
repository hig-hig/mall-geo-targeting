"""Adapter for manually downloaded e-Stat regional-mesh CSV files."""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import EstatMeshStatistics, StatisticalValue, ValueStatus

LOGGER = logging.getLogger(__name__)
REQUIRED_COLUMN_KEYS = (
    "standard_mesh_code",
    "total_population",
    "households",
    "age_0_14",
    "age_15_64",
    "age_65_plus",
)


class EstatAdapterError(ValueError):
    """Raised when a manually supplied e-Stat file cannot be interpreted."""


@dataclass(frozen=True)
class MarkerSet:
    missing: frozenset[str]
    suppressed: frozenset[str]
    not_applicable: frozenset[str]


def _marker_set(config: dict[str, Any]) -> MarkerSet:
    markers = config.get("markers", {})
    return MarkerSet(
        frozenset(str(v).strip() for v in markers.get("missing", [""])),
        frozenset(str(v).strip() for v in markers.get("suppressed", ["X"])),
        frozenset(str(v).strip() for v in markers.get("not_applicable", ["-"])),
    )


def parse_statistical_value(raw: str, markers: MarkerSet) -> StatisticalValue:
    """Parse a cell without collapsing missing/suppressed/N/A into numeric zero."""
    normalized = raw.strip()
    if normalized in markers.suppressed:
        return StatisticalValue(None, ValueStatus.SUPPRESSED, raw)
    if normalized in markers.not_applicable:
        return StatisticalValue(None, ValueStatus.NOT_APPLICABLE, raw)
    if normalized in markers.missing:
        return StatisticalValue(None, ValueStatus.MISSING, raw)
    try:
        value = int(normalized.replace(",", ""))
    except ValueError as exc:
        raise EstatAdapterError(f"整数または設定済み欠損記号ではありません: {raw!r}") from exc
    if value < 0:
        raise EstatAdapterError(f"人口・世帯数に負数は指定できません: {raw!r}")
    return StatisticalValue(value, ValueStatus.OBSERVED, raw)


def load_estat_csv(path: Path, config: dict[str, Any]) -> dict[str, EstatMeshStatistics]:
    """Load a user-downloaded CSV according to configurable headers and markers."""
    columns = config.get("columns")
    if not isinstance(columns, dict):
        raise EstatAdapterError("estat.columnsを設定してください")
    missing_keys = [key for key in REQUIRED_COLUMN_KEYS if key not in columns]
    if missing_keys:
        raise EstatAdapterError(f"estat.columnsに必須キーがありません: {', '.join(missing_keys)}")
    encoding = str(config.get("encoding", "utf-8-sig"))
    delimiter = str(config.get("delimiter", ","))
    if len(delimiter) != 1:
        raise EstatAdapterError("delimiterは1文字で指定してください")
    markers = _marker_set(config)
    try:
        stream = path.open(encoding=encoding, newline="")
    except (OSError, LookupError) as exc:
        raise EstatAdapterError(f"e-Stat CSVを開けません: {path}: {exc}") from exc
    result: dict[str, EstatMeshStatistics] = {}
    try:
        with stream:
            reader = csv.DictReader(stream, delimiter=delimiter)
            actual = set(reader.fieldnames or [])
            expected = {str(columns[key]) for key in REQUIRED_COLUMN_KEYS}
            absent = sorted(expected - actual)
            if absent:
                raise EstatAdapterError(f"e-Stat CSVに設定列がありません: {', '.join(absent)}")
            for line_number, row in enumerate(reader, start=2):
                code = row[str(columns["standard_mesh_code"])].strip()
                if not code.isdigit() or len(code) not in (8, 9, 10):
                    raise EstatAdapterError(f"{line_number}行目の標準地域メッシュコードが不正です: {code!r}")
                if code in result:
                    raise EstatAdapterError(f"標準地域メッシュコードが重複しています: {code}")
                try:
                    values = {key: parse_statistical_value(row[str(columns[key])], markers) for key in REQUIRED_COLUMN_KEYS[1:]}
                except EstatAdapterError as exc:
                    raise EstatAdapterError(f"{line_number}行目: {exc}") from exc
                result[code] = EstatMeshStatistics(
                    standard_mesh_code=code,
                    total_population=values["total_population"],
                    households=values["households"],
                    age_0_14=values["age_0_14"],
                    age_15_64=values["age_15_64"],
                    age_65_plus=values["age_65_plus"],
                    survey_year=int(config["survey_year"]),
                    table_id=str(config["table_id"]),
                )
    except (csv.Error, UnicodeError, KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, EstatAdapterError):
            raise
        raise EstatAdapterError(f"e-Stat CSVを読み込めません: {path}: {exc}") from exc
    LOGGER.info("e-Stat CSVから%d標準地域メッシュを読み込みました", len(result))
    return result
