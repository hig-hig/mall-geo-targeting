"""Command-line entry point."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .pipeline import run


def main() -> int:
    parser = argparse.ArgumentParser(description="モールアプリ獲得ポテンシャル分析")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--data-mode", choices=("sample", "estat"), default=None, help="analysis.yamlのdata_modeを一時的に上書き")
    parser.add_argument("--accessibility-mode", choices=("sample", "osm", "none"), default=None, help="到達性データ源を一時的に上書き")
    parser.add_argument("--commercial-mode", choices=("sample", "osm", "file", "none"), default=None, help="商業POIデータ源を一時的に上書き")
    parser.add_argument("--log-level", default="INFO", choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    args = parser.parse_args()
    logging.basicConfig(level=args.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        result = run(args.project_root.resolve(), data_mode=args.data_mode, accessibility_mode=args.accessibility_mode, commercial_mode=args.commercial_mode)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        logging.getLogger(__name__).error("分析に失敗しました: %s", exc)
        return 1
    print(f"モード: {result['data_mode']}+{result['accessibility_mode']}+{result['commercial_mode']} / メッシュ: {result['mesh_count']} / スコア算出: {result['scored_count']} / 配信ゾーン: {result['delivery_zone_count']}")
    print(f"到達性coverage: {result['accessibility_coverage_count']}件 / 平均: {result['mean_accessibility_coverage']}")
    print(f"商業coverage: {result['commercial_coverage_count']}件 / 平均: {result['mean_commercial_coverage']}")
    print(f"配信適格: {result['eligible_count']} / coverage除外: {result['excluded_by_coverage_count']} / 品質ランク: {result['quality_counts']}")
    for kind, path in result["outputs"].items():
        print(f"{kind}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
