import json
import shutil
import subprocess
from pathlib import Path

import pytest

from mall_geo_targeting.config import load_yaml, mall_from_dict
from mall_geo_targeting.map_output import MAP_FIELDS, build_map_html
from mall_geo_targeting.models import Mall, Mesh


def _mall(identifier: str, name: str, longitude: float, *, target: bool = False) -> Mall:
    return Mall(
        id=identifier,
        name=name,
        latitude=35.7,
        longitude=longitude,
        floor_area_m2=78_000 if target else 63_000,
    )


def _mesh(identifier: str, *, eligible: bool, zone: bool) -> Mesh:
    mesh = Mesh(
        mesh_id=identifier,
        row=0,
        column=0,
        center_latitude=35.7,
        center_longitude=139.4,
        polygon=[
            [139.39, 35.69],
            [139.41, 35.69],
            [139.41, 35.71],
            [139.39, 35.71],
            [139.39, 35.69],
        ],
    )
    mesh.acquisition_potential_score = 42.5 if eligible else None
    mesh.population = 125 if eligible else None
    mesh.huff_probability = 0.625 if eligible else None
    mesh.car_choice_index = 0.6 if eligible else None
    mesh.walk_choice_index = 0.5 if eligible else None
    mesh.bike_choice_index = 0.55 if eligible else None
    mesh.car_availability = 1.0 if eligible else None
    mesh.walk_availability = 0.75 if eligible else None
    mesh.bike_availability = 0.9 if eligible else None
    mesh.accessibility_index = 0.7 if eligible else None
    mesh.commercial_concentration_index = 0.4 if eligible else None
    mesh.score_coverage = 1.0 if eligible else None
    mesh.eligible_for_delivery = eligible
    mesh.is_delivery_zone = zone
    mesh.used_features = ["huff_visit_probability"] if eligible else []
    mesh.score_contributions = {"huff_visit_probability": 42.5} if eligible else {}
    return mesh


def _payload(html: str) -> dict[str, object]:
    raw = html.split("const DATA=", 1)[1].split(";const I=", 1)[0]
    return json.loads(raw)


def test_map_contains_metrics_controls_malls_and_sources() -> None:
    target = _mall("target", "対象モール", 139.4, target=True)
    competitor = _mall("competitor", "競合モール", 139.42)
    html = build_map_html(
        [_mesh("M_1", eligible=True, zone=True)],
        target,
        [competitor],
        {
            "mesh_size_m": 250,
            "analysis_radius_m": 10_000,
            "threshold": 42.5,
            "retrieved_at": {"estat": "2026-07-20", "osm": "2026-07-20"},
        },
    )

    for label in (
        "総合スコア",
        "人口",
        "施設相対選択指数",
        "車・到達条件付き選択指数",
        "徒歩・到達条件付き選択指数",
        "自転車・到達条件付き選択指数",
        "アクセシビリティ",
        "商業集積",
        "配信適格判定",
        "歩行道路密度",
        "商業POI数",
    ):
        assert label in html
    for control in ("eligible-only", "zones-only", "show-malls", "legend", "details"):
        assert f'id="{control}"' in html
    assert "対象モール" in html
    assert "競合モール" in html
    assert "78000" in html
    assert "政府統計の総合窓口 e-Stat" in html
    assert "© OpenStreetMap contributors" in html
    assert "完全な店舗網羅を保証しません" in html
    assert '<div class="basemap" id="basemap"' in html
    assert 'id="theme-light"' in html
    assert 'id="theme-dark"' in html
    assert 'id="theme-light" type="button" data-theme="light"' in html
    assert 'aria-pressed="true">ライト' in html
    assert 'aria-pressed="false">ダーク' in html
    assert "light_all/{z}/{x}/{y}.png" in html
    assert "dark_all/{z}/{x}/{y}.png" in html
    assert html.index('id="basemap"') < html.index('id="map"')
    assert ".basemap{position:absolute;inset:0;z-index:0" in html
    assert ".map-canvas{position:absolute;inset:0;z-index:1" in html
    assert "© CARTO" not in html
    assert "OpenStreetMap contributors</a> © <a" in html
    assert "CARTO</a>" in html
    assert "背景地図を読み込めませんでした" in html
    assert "img.onerror=()=>settled(false)" in html
    assert "localStorage.setItem" in html
    assert "localStorage.getItem" in html
    assert 'b.onclick=()=>{active=id;breakCache=null' in html
    assert 'b.onclick=()=>setTheme(b.dataset.theme)' in html
    assert "https://a.basemaps.cartocdn.com/" in html


def test_map_summary_is_generated_from_meshes_and_handles_missing_values() -> None:
    target = _mall("target", "対象モール", 139.4, target=True)
    html = build_map_html(
        [
            _mesh("M_eligible", eligible=True, zone=True),
            _mesh("M_missing", eligible=False, zone=False),
        ],
        target,
        [],
        {"mesh_size_m": 250, "threshold": 42.5},
    )
    payload = _payload(html)

    assert payload["summary"] == {
        "above_threshold_count": 1,
        "delivery_zone_count": 1,
        "eligible_count": 1,
        "ineligible_above_threshold_count": 0,
        "mean_score_coverage": 1.0,
        "mesh_count": 2,
        "threshold": 42.5,
    }
    score_index = 4 + MAP_FIELDS.index("acquisition_potential_score")
    assert payload["meshes"][1][score_index] is None
    assert 'return"欠損"' in html


def test_other_numeric_map_legends_keep_quantile_ranges_and_dynamic_threshold_note() -> None:
    target = _mall("target", "対象モール", 139.4, target=True)
    html = build_map_html(
        [_mesh(f"M_{index}", eligible=True, zone=index == 4) for index in range(5)],
        target,
        [],
        {"mesh_size_m": 250, "threshold": 42.5, "delivery_quantile": 0.8},
    )
    assert "[0,.2,.4,.6,.8,1]" in html
    assert 'format(lower,metric)+"超～"+format(b[i+1],metric)' in html
    assert 'format(b[i],metric)+" 以上"' not in html
    assert "分類対象" in html
    assert "フィルター変更時に区切りも再計算" in html
    assert "データなし" in html
    assert 'note.hidden=active!=="score"' in html
    assert "配信適格メッシュ内の上位" in html


def test_score_legend_uses_fixed_twenty_point_ranges_and_keeps_threshold_separate() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("nodeが利用できないため境界値のJavaScript検査を省略")
    target = _mall("target", "対象モール", 139.4, target=True)
    map_display = {
        "legend_method": "visible_mesh_quintiles",
        "score_legend": {
            "method": "fixed_score_intervals",
            "boundaries": [0, 20, 40, 60, 80, 100],
            "unit": "points",
            "comparable_across_projects": True,
        },
    }
    html = build_map_html(
        [_mesh("M_1", eligible=True, zone=True)],
        target,
        [],
        {
            "mesh_size_m": 250,
            "threshold": 33.7,
            "delivery_quantile": 0.8,
            "map_display": map_display,
        },
    )
    payload = _payload(html)
    function_body = html.split("function fixedIntervalClass", 1)[1].split(
        "function fillFor", 1
    )[0]
    script = (
        "function fixedIntervalClass"
        + function_body
        + "console.log(JSON.stringify([0,19.999,20,40,60,80,100].map("
        + "value=>fixedIntervalClass(value,[0,20,40,60,80,100]))));"
    )
    result = subprocess.run(
        [node, "-e", script], capture_output=True, check=False, text=True
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [0, 0, 1, 2, 3, 4, 4]
    assert payload["context"]["map_display"] == map_display
    assert payload["summary"]["threshold"] == 33.7
    assert 'fixedScore:true' in html
    assert "metric.fixedScore?scoreBoundaries()" in html
    assert "metric.fixedScore||metric.fixedChoice" in html
    assert '`${lower}点以上～${b[i+1]}点${i===4?"以下":"未満"}`' in html
    assert "総合スコアは0～100点を20点刻みで固定表示しています。" in html
    assert "配信判定は別途、閾値" in html
    assert 'metric.fixedChoice?"到達候補なし／No-data":"データなし"' in html
    assert 'note.hidden=active!=="score"' in html
    assert "配信ゾーン輪郭" in html
    assert "必須データ条件" in html


def test_choice_index_legend_uses_fixed_twenty_point_ranges() -> None:
    target = _mall("target", "対象モール", 139.4, target=True)
    map_display = {
        "legend_method": "visible_mesh_quintiles",
        "choice_index_legend": {
            "method": "fixed_percentage_intervals",
            "boundaries": [0, 20, 40, 60, 80, 100],
            "unit": "percent",
            "comparable_across_modes": True,
        },
    }
    html = build_map_html(
        [_mesh("M_1", eligible=True, zone=False)],
        target,
        [],
        {"mesh_size_m": 250, "threshold": 42.5, "map_display": map_display},
    )
    payload = _payload(html)

    assert payload["context"]["map_display"] == map_display
    assert html.count("fixedChoice:true") == 4
    assert 'key:"huff_probability",unit:"%",scale:100,digits:1,fixedChoice:true' in html
    for key in ("car_choice_index", "walk_choice_index", "bike_choice_index"):
        assert f'key:"{key}",unit:"%",scale:100,digits:1,fixedChoice:true' in html
    assert "[0,20,40,60,80,100]" in html
    assert "while(n<4&&v>=b[n+1])n++" in html
    assert "0%以上～20%未満" not in html  # Labels are generated dynamically in JavaScript.
    assert '`${lower}%以上～${b[i+1]}%${i===4?"以下":"未満"}`' in html
    assert 'metric.fixedChoice?"到達候補なし／No-data":"データなし"' in html
    assert "[0,.2,.4,.6,.8,1]" in html
    assert "if(metric.fixedScore||metric.fixedChoice)n=fixedIntervalClass(v,b);else while" in html


def test_map_explains_all_delivery_decision_patterns_and_score_contributions() -> None:
    target = _mall("target", "対象モール", 139.4, target=True)
    html = build_map_html(
        [_mesh("M_1", eligible=True, zone=True)],
        target,
        [],
        {"mesh_size_m": 250, "threshold": 42.5},
    )
    for phrase in (
        "必要データが揃い、総合スコアが配信候補基準以上です。",
        "必要データは揃っていますが、総合スコアが配信候補基準未満です。",
        "総合スコアは基準以上ですが、必須データ条件を満たしていないため配信対象外です。",
        "必須データ条件を満たさず、総合スコアも配信候補基準未満です。",
    ):
        assert phrase in html
    assert "スコア寄与" in html
    assert "閾値との差" in html
    assert "不足している必須グループ" in html


def test_real_mall_configuration_serializes_target_and_three_competitors() -> None:
    root = Path(__file__).parents[1]
    config = load_yaml(root / "data/raw/malls/aeon-mall-musashimurayama__mall-profile__20260718.yaml")
    target = mall_from_dict(config["target_mall"])
    competitors = [mall_from_dict(value) for value in config["competitor_malls"]]
    html = build_map_html([], target, competitors, {"analysis_radius_m": 10_000})
    malls = _payload(html)["malls"]
    assert len(malls) == 4
    assert {mall["name"] for mall in malls} == {
        "イオンモールむさし村山",
        "ららぽーと立川立飛",
        "イオンモール日の出",
        "モリタウン",
    }
    assert not {"MOVIX昭島", "モリパーク アウトドアヴィレッジ", "ニトリ", "スポーツデポ"} & {
        mall["name"] for mall in malls
    }
    by_name = {mall["name"]: mall for mall in malls}
    assert by_name["モリタウン"]["size_measurement_type"] == "official_store_area"
    assert by_name["モリタウン"]["size_measurement_label"] == "公表店舗面積"
    assert "GLA相当値" in by_name["モリタウン"]["size_measurement_note"]
    assert {
        mall["size_measurement_type"]
        for name, mall in by_name.items()
        if name != "モリタウン"
    } == {"gross_leasable_area"}


def test_map_analysis_conditions_use_payload_context() -> None:
    target = _mall("target", "対象モール", 139.4, target=True)
    html = build_map_html(
        [_mesh("M_1", eligible=True, zone=True)],
        target,
        [_mall("competitor", "競合モール", 139.42)],
        {
            "analysis_radius_m": 10_000,
            "mesh_size_m": 250,
            "threshold": 42.5,
            "population_survey_year": 2020,
            "score_weights": {"huff_visit_probability": 0.2},
        },
    )
    assert 'Number(c.analysis_radius_m||0)/1000' in html
    assert "c.mesh_size_m||250" in html
    assert "c.score_weights||{}" in html
    assert "重みは統計的な正解値ではなく、現在の分析シナリオ" in html
    assert "実来館確率ではありません" in html


def test_transport_scenario_context_is_displayed_without_score_integration() -> None:
    target = _mall("target", "対象モール", 139.4, target=True)
    html = build_map_html(
        [_mesh("M_1", eligible=True, zone=True)],
        target,
        [],
        {
            "threshold": 42.5,
            "scenario_metadata": {"label": "標準シナリオ", "calibration_status": "uncalibrated_scenario"},
            "transport_choice": {"method": "straight_line_distance_with_mode_availability", "score_integration": "display_only"},
        },
    )
    payload = _payload(html)
    assert payload["context"]["transport_choice"]["score_integration"] == "display_only"
    assert "未校正・表示専用" in html
    assert "交通手段割合は未実装" in html


def test_map_html_generation_is_deterministic() -> None:
    target = _mall("target", "対象モール", 139.4, target=True)
    meshes = [_mesh("M_1", eligible=True, zone=False)]
    context = {"mesh_size_m": 250, "threshold": 40.0}

    assert build_map_html(meshes, target, [], context) == build_map_html(
        meshes, target, [], context
    )


def test_generated_javascript_has_valid_syntax() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("nodeが利用できないためJavaScript構文検査を省略")
    target = _mall("target", "対象モール", 139.4, target=True)
    html = build_map_html(
        [_mesh("M_1", eligible=True, zone=False)],
        target,
        [],
        {"mesh_size_m": 250, "threshold": 40.0},
    )
    script = html.split("<script>", 1)[1].split("</script>", 1)[0]

    result = subprocess.run(
        [node, "--check", "-"],
        input=script,
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stderr
