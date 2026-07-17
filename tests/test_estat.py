from pathlib import Path

import pytest

from mall_geo_targeting.analysis import join_estat_statistics, standard_quarter_mesh_code
from mall_geo_targeting.estat import EstatAdapterError, MarkerSet, load_estat_csv, parse_statistical_value
from mall_geo_targeting.models import Mesh, ValueStatus


MARKERS = MarkerSet(
    missing=frozenset({"", "NA"}),
    suppressed=frozenset({"X"}),
    not_applicable=frozenset({"-"}),
)


def config() -> dict[str, object]:
    return {
        "encoding": "utf-8-sig",
        "delimiter": ",",
        "survey_year": 2020,
        "table_id": "TEST-TABLE",
        "columns": {
            "standard_mesh_code": "mesh",
            "total_population": "population",
            "households": "households",
            "age_0_14": "children",
            "age_15_64": "working_age",
            "age_65_plus": "seniors",
        },
        "markers": {"missing": ["", "NA"], "suppressed": ["X"], "not_applicable": ["-"]},
    }


@pytest.mark.parametrize(
    ("raw", "value", "status"),
    [
        ("0", 0, ValueStatus.OBSERVED),
        ("", None, ValueStatus.MISSING),
        ("NA", None, ValueStatus.MISSING),
        ("X", None, ValueStatus.SUPPRESSED),
        ("-", None, ValueStatus.NOT_APPLICABLE),
    ],
)
def test_statistical_value_states_are_distinct(raw: str, value: int | None, status: ValueStatus) -> None:
    parsed = parse_statistical_value(raw, MARKERS)
    assert parsed.value == value
    assert parsed.status is status


def test_configurable_encoding_columns_and_metadata(tmp_path: Path) -> None:
    path = tmp_path / "estat.csv"
    path.write_text("mesh;population;households;children;working_age;seniors\n5339368013;0;12;X;-;NA\n", encoding="cp932")
    custom = config()
    custom["encoding"] = "cp932"
    custom["delimiter"] = ";"
    records = load_estat_csv(path, custom)
    record = records["5339368013"]
    assert record.total_population.value == 0
    assert record.total_population.status is ValueStatus.OBSERVED
    assert record.age_0_14.status is ValueStatus.SUPPRESSED
    assert record.age_15_64.status is ValueStatus.NOT_APPLICABLE
    assert record.age_65_plus.status is ValueStatus.MISSING
    assert record.survey_year == 2020
    assert record.table_id == "TEST-TABLE"


def test_invalid_unconfigured_marker_fails(tmp_path: Path) -> None:
    path = tmp_path / "estat.csv"
    path.write_text("mesh,population,households,children,working_age,seniors\n5339368013,***,1,1,1,1\n", encoding="utf-8")
    with pytest.raises(EstatAdapterError, match="2行目"):
        load_estat_csv(path, config())


def test_application_mesh_id_is_not_replaced_by_standard_code(tmp_path: Path) -> None:
    path = tmp_path / "estat.csv"
    path.write_text("mesh,population,households,children,working_age,seniors\n5339368013,100,40,10,60,30\n", encoding="utf-8")
    statistics = load_estat_csv(path, config())
    mesh = Mesh("M_011_010", 11, 10, 35.65, 139.75, [], standard_mesh_code="5339368013")
    join_estat_statistics([mesh], statistics)
    assert mesh.mesh_id == "M_011_010"
    assert mesh.standard_mesh_code == "5339368013"
    assert mesh.source_standard_mesh_code == "5339368013"
    assert mesh.population == 100
    assert mesh.household_count == 40
    assert mesh.source_survey_year == 2020
    assert mesh.source_table_id == "TEST-TABLE"


def test_standard_quarter_mesh_code_is_ten_digits_and_stable() -> None:
    code = standard_quarter_mesh_code(35.655, 139.756)
    assert code == "5339368032"
    assert len(code) == 10


def test_coarser_estat_mesh_is_joined_without_changing_analysis_mesh_code(tmp_path: Path) -> None:
    path = tmp_path / "estat.csv"
    path.write_text("mesh,population,households,children,working_age,seniors\n53393680,100,40,10,60,30\n", encoding="utf-8")
    statistics = load_estat_csv(path, config())
    mesh = Mesh("M_011_010", 11, 10, 35.65, 139.75, [], standard_mesh_code="5339368013")
    join_estat_statistics([mesh], statistics)
    assert mesh.standard_mesh_code == "5339368013"
    assert mesh.source_standard_mesh_code == "53393680"
    assert mesh.population == 100
