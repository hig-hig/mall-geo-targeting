import io
from pathlib import Path

from mall_geo_targeting.estat_processing import process_estat_tables


def _write_table(path: Path, ids: list[str], headers: list[str], values: list[str]) -> None:
    path.write_text(
        ",".join(["KEY_CODE", "HTKSYORI", *ids])
        + "\n,,"
        + ",".join(headers)
        + "\n5339000001,2,"
        + ",".join(values)
        + "\n",
        encoding="cp932",
    )


def test_processing_preserves_suppression_and_observed_zero(tmp_path: Path) -> None:
    table_102 = tmp_path / "102.txt"
    table_175 = tmp_path / "175.txt"
    _write_table(
        table_102,
        ["a", "b", "c", "d"],
        ["人口（総数）", "世帯総数", "０～１４歳人口　総数", "１５～６４歳人口　総数"],
        ["3", "1", "*", "0"],
    )
    age_headers = [
        "６５～６９歳人口　総数",
        "７０～７４歳人口　総数",
        "７５～７９歳人口　総数",
        "８０～８４歳人口　総数",
        "８５～８９歳人口　総数",
        "９０～９４歳人口　総数",
        "９５歳以上人口　総数",
    ]
    _write_table(table_175, list("abcdefg"), age_headers, ["1", "0", "0", "*", "0", "0", "0"])
    output = io.StringIO()

    assert process_estat_tables(table_102, table_175, output) == 1
    assert output.getvalue().splitlines()[1] == "5339000001,3,1,*,0,*"


def test_processing_sums_all_65_plus_age_bands(tmp_path: Path) -> None:
    table_102 = tmp_path / "102.txt"
    table_175 = tmp_path / "175.txt"
    _write_table(
        table_102,
        ["a", "b", "c", "d"],
        ["人口（総数）", "世帯総数", "０～１４歳人口　総数", "１５～６４歳人口　総数"],
        ["100", "40", "10", "60"],
    )
    age_headers = [
        "６５～６９歳人口　総数",
        "７０～７４歳人口　総数",
        "７５～７９歳人口　総数",
        "８０～８４歳人口　総数",
        "８５～８９歳人口　総数",
        "９０～９４歳人口　総数",
        "９５歳以上人口　総数",
    ]
    _write_table(table_175, list("abcdefg"), age_headers, ["1", "2", "3", "4", "5", "6", "7"])
    output = io.StringIO()

    process_estat_tables(table_102, table_175, output)

    assert output.getvalue().splitlines()[1].endswith(",28")
