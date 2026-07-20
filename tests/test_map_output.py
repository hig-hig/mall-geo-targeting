import json
import shutil
import subprocess

import pytest

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
    mesh.accessibility_index = 0.7 if eligible else None
    mesh.commercial_concentration_index = 0.4 if eligible else None
    mesh.score_coverage = 1.0 if eligible else None
    mesh.eligible_for_delivery = eligible
    mesh.is_delivery_zone = zone
    mesh.used_features = ["huff_visit_probability"] if eligible else []
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
        "Huff来館確率",
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
        "delivery_zone_count": 1,
        "eligible_count": 1,
        "mean_score_coverage": 1.0,
        "mesh_count": 2,
        "threshold": 42.5,
    }
    score_index = 4 + MAP_FIELDS.index("acquisition_potential_score")
    assert payload["meshes"][1][score_index] is None
    assert 'return"欠損"' in html


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
