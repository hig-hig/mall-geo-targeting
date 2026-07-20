"""Validate a locally generated real-data map before publishing it to Vercel."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path


TARGET_MALL_NAME = "イオンモールむさし村山"
SAMPLE_MALL_NAME = "サンプル東京ベイモール"
LEGACY_LEAFLET_MARKERS = (
    "leaflet@",
    "leaflet.js",
    "leaflet.css",
    "L.map(",
    "L.tileLayer(",
)
CANVAS_MARKERS = (
    '<div class="basemap" id="basemap"',
    '<canvas class="map-canvas" id="map"></canvas>',
    "const BASEMAPS=",
    "const DATA=",
    ";const I=",
)
REAL_DATA_MODES = {
    "data_mode": "estat",
    "accessibility_mode": "osm",
    "commercial_mode": "osm",
}
ROBOTS_META = '<meta name="robots" content="noindex, nofollow, noarchive, nosnippet">'
ROBOTS_META_PATTERN = re.compile(
    r"<meta\b(?=[^>]*\bname\s*=\s*['\"]robots['\"])[^>]*>",
    re.IGNORECASE,
)
HEAD_END_PATTERN = re.compile(r"</head\s*>", re.IGNORECASE)


class PublicationValidationError(ValueError):
    """Raised when the generated map is not safe to publish."""


def _map_payload(html: str) -> dict[str, object]:
    try:
        raw_payload = html.split("const DATA=", 1)[1].split(";const I=", 1)[0]
        payload = json.loads(raw_payload)
    except (IndexError, json.JSONDecodeError) as exc:
        raise PublicationValidationError("Canvas版の埋め込みデータを解析できません") from exc
    if not isinstance(payload, dict):
        raise PublicationValidationError("埋め込みデータがJSONオブジェクトではありません")
    return payload


def validate_map_html(source: Path) -> tuple[bytes, list[str]]:
    """Return validated bytes and human-readable checks without changing destination files."""
    if not source.is_file():
        raise PublicationValidationError(f"入力HTMLが存在しません: {source}")
    content = source.read_bytes()
    if not content:
        raise PublicationValidationError(f"入力HTMLが空です: {source}")
    try:
        html = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PublicationValidationError("入力HTMLはUTF-8ではありません") from exc

    if TARGET_MALL_NAME not in html:
        raise PublicationValidationError(f"対象施設名がありません: {TARGET_MALL_NAME}")
    if SAMPLE_MALL_NAME in html:
        raise PublicationValidationError(f"サンプル施設名が含まれています: {SAMPLE_MALL_NAME}")
    legacy_markers = [marker for marker in LEGACY_LEAFLET_MARKERS if marker in html]
    if legacy_markers:
        raise PublicationValidationError(
            f"旧Leaflet版の参照が含まれています: {', '.join(legacy_markers)}"
        )
    missing_canvas_markers = [marker for marker in CANVAS_MARKERS if marker not in html]
    if missing_canvas_markers:
        raise PublicationValidationError(
            f"Canvas版の識別子が不足しています: {', '.join(missing_canvas_markers)}"
        )

    payload = _map_payload(html)
    context = payload.get("context")
    if not isinstance(context, dict):
        raise PublicationValidationError("実行モードを示すcontextがありません")
    invalid_modes = {
        name: context.get(name)
        for name, expected in REAL_DATA_MODES.items()
        if context.get(name) != expected
    }
    if invalid_modes:
        details = ", ".join(f"{name}={value!r}" for name, value in invalid_modes.items())
        raise PublicationValidationError(f"実データモードではありません: {details}")

    return content, [
        f"対象施設: {TARGET_MALL_NAME}",
        "サンプル施設: なし",
        "地図実装: Canvas版",
        "実行モード: estat + osm + osm",
    ]


def _add_robots_meta(html: str) -> str:
    html_without_robots = ROBOTS_META_PATTERN.sub("", html)
    head_end = HEAD_END_PATTERN.search(html_without_robots)
    if head_end is None:
        raise PublicationValidationError("HTMLのhead終了タグがありません")
    return (
        html_without_robots[: head_end.start()]
        + ROBOTS_META
        + html_without_robots[head_end.start() :]
    )


def prepare_publication(source: Path, destination: Path) -> tuple[int, list[str]]:
    """Atomically publish a validated map and return its size and validation checks."""
    content, checks = validate_map_html(source)
    publication_content = _add_robots_meta(content.decode("utf-8")).encode("utf-8")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            stream.write(publication_content)
            temporary_path = Path(stream.name)
        temporary_path.chmod(0o644)
        os.replace(temporary_path, destination)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    return len(publication_content), [*checks, "検索エンジン: noindex"]


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="検証済み実データ地図だけをVercel公開ディレクトリへ配置します。"
    )
    parser.add_argument("--source", type=Path, default=Path("outputs/map.html"))
    parser.add_argument("--destination", type=Path, default=Path("public/index.html"))
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    try:
        size, checks = prepare_publication(args.source, args.destination)
    except (OSError, PublicationValidationError) as exc:
        print(f"公開準備に失敗しました: {exc}", file=sys.stderr)
        return 1
    print(f"コピー元: {args.source}")
    print(f"コピー先: {args.destination}")
    print(f"ファイルサイズ: {size} bytes")
    print("検証結果:")
    for check in checks:
        print(f"- {check}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
