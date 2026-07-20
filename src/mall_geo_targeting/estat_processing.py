"""Prepare the two 2020 census quarter-mesh tables for the e-Stat adapter."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import TextIO


OUTPUT_COLUMNS = ("地域メッシュコード", "総人口", "世帯数", "0～14歳人口", "15～64歳人口", "65歳以上人口")
TABLE_102_COLUMNS = {
    "総人口": "人口（総数）",
    "世帯数": "世帯総数",
    "0～14歳人口": "０～１４歳人口　総数",
    "15～64歳人口": "１５～６４歳人口　総数",
}
AGE_65_PLUS_COLUMNS = (
    "６５～６９歳人口　総数",
    "７０～７４歳人口　総数",
    "７５～７９歳人口　総数",
    "８０～８４歳人口　総数",
    "８５～８９歳人口　総数",
    "９０～９４歳人口　総数",
    "９５歳以上人口　総数",
)


def _normalized_header(value: str) -> str:
    return " ".join(value.replace("　", " ").split())


def _read_table(path: Path) -> tuple[list[str], dict[str, dict[str, str]]]:
    with path.open(encoding="cp932", newline="") as stream:
        reader = csv.reader(stream)
        field_names = next(reader)
        japanese_headers = next(reader)
        if len(field_names) != len(japanese_headers):
            raise ValueError(f"列IDと日本語ヘッダーの列数が一致しません: {path}")
        header_to_field = {
            _normalized_header(header): field_name
            for field_name, header in zip(field_names, japanese_headers, strict=True)
            if header.strip()
        }
        rows: dict[str, dict[str, str]] = {}
        for line_number, values in enumerate(reader, start=3):
            row = dict(zip(field_names, values, strict=True))
            code = row["KEY_CODE"]
            if len(code) != 10 or not code.isdigit():
                continue
            if code in rows:
                raise ValueError(f"KEY_CODEが重複しています: {path}:{line_number}: {code}")
            rows[code] = row
    return [header_to_field[key] for key in header_to_field], rows


def _field_for_header(path: Path, field_names: list[str], header: str) -> str:
    normalized = _normalized_header(header)
    # _read_table returns fields in Japanese-header order. Re-read only two header rows
    # so column selection remains based on the supplied Japanese header, not fixed offsets.
    with path.open(encoding="cp932", newline="") as stream:
        reader = csv.reader(stream)
        ids = next(reader)
        names = next(reader)
    mapping = {_normalized_header(name): field for field, name in zip(ids, names, strict=True)}
    try:
        field = mapping[normalized]
    except KeyError as exc:
        raise ValueError(f"必要な日本語ヘッダーがありません: {path}: {header}") from exc
    if field not in field_names:
        raise ValueError(f"日本語ヘッダーに対応する列IDが不正です: {path}: {header}")
    return field


def _sum_age_cells(values: list[str]) -> str:
    stripped = [value.strip() for value in values]
    if "*" in stripped:
        return "*"
    if any(not value for value in stripped):
        return ""
    try:
        return str(sum(int(value.replace(",", "")) for value in stripped))
    except ValueError as exc:
        raise ValueError(f"65歳以上人口の階級値が整数・空欄・*のいずれでもありません: {values!r}") from exc


def process_estat_tables(table_102: Path, table_175: Path, output: TextIO) -> int:
    """Combine two e-Stat tables without imputing suppressed or missing values."""
    fields_102, rows_102 = _read_table(table_102)
    fields_175, rows_175 = _read_table(table_175)
    if rows_102.keys() != rows_175.keys():
        raise ValueError("2表の10桁KEY_CODEが一致しません")

    selected_102 = {
        output_name: _field_for_header(table_102, fields_102, source_name)
        for output_name, source_name in TABLE_102_COLUMNS.items()
    }
    age_fields = [_field_for_header(table_175, fields_175, name) for name in AGE_65_PLUS_COLUMNS]
    writer = csv.DictWriter(output, fieldnames=OUTPUT_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for code, row_102 in rows_102.items():
        row_175 = rows_175[code]
        writer.writerow(
            {
                "地域メッシュコード": code,
                **{name: row_102[field].strip() for name, field in selected_102.items()},
                "65歳以上人口": _sum_age_cells([row_175[field] for field in age_fields]),
            }
        )
    return len(rows_102)


def metadata() -> dict[str, object]:
    return {
        "dataset_name": "令和2年国勢調査 250m地域メッシュ人口（一次メッシュ5339）",
        "source": "政府統計の総合窓口 e-Stat 地図で見る統計（統計GIS）地域メッシュ統計",
        "source_url": "https://www.e-stat.go.jp/gis/statmap-search?page=1&type=1&toukeiCode=00200521",
        "license": "政府標準利用規約（第2.0版）",
        "commercial_use_allowed": True,
        "attribution_required": True,
        "retrieved_at": "2026-07-20",
        "coverage_area": [139.0, 35.3333333333, 140.0, 36.0],
        "processing": (
            "cp932の日本語ヘッダーで必要列を特定し、10桁KEY_CODEのみを保持。人口、世帯数、"
            "0～14歳、15～64歳はT001102から抽出。65歳以上はT001175の65～69歳から"
            "95歳以上までの総数7階級を合計し、いずれかが*なら*、空欄なら空欄とした。"
            "年齢不詳の按分は行っていない。HTKSYORI=2の合算元と=1の合算先を含め、"
            "e-Stat掲載値と秘匿状態を変更していない。"
        ),
        "is_sample": False,
        "survey_year": 2020,
        "mesh_level": 5,
        "mesh_size_m": 250,
        "primary_area_code": "5339",
        "source_files": ["tblT001102Q5339.txt", "tblT001175Q5339.txt"],
        "source_tables": ["T001102", "T001175"],
        "encoding": "cp932",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="2020年国勢調査250mメッシュ2表をe-Statアダプター形式へ加工")
    parser.add_argument("table_102", type=Path)
    parser.add_argument("table_175", type=Path)
    parser.add_argument("output_csv", type=Path)
    parser.add_argument("output_metadata", type=Path)
    args = parser.parse_args()
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.output_csv.open("w", encoding="utf-8-sig", newline="") as output:
        count = process_estat_tables(args.table_102, args.table_175, output)
    args.output_metadata.write_text(
        json.dumps(metadata(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"加工完了: {count}行: {args.output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
