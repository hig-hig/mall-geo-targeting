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
    parser.add_argument("--log-level", default="INFO", choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    args = parser.parse_args()
    logging.basicConfig(level=args.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        result = run(args.project_root.resolve(), data_mode=args.data_mode)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        logging.getLogger(__name__).error("分析に失敗しました: %s", exc)
        return 1
    print(f"モード: {result['data_mode']} / メッシュ: {result['mesh_count']} / スコア算出: {result['scored_count']} / 配信ゾーン: {result['delivery_zone_count']}")
    for kind, path in result["outputs"].items():
        print(f"{kind}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
