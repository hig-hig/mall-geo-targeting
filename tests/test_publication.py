import importlib.util
import json
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "prepare_vercel", ROOT / "scripts" / "prepare_vercel.py"
)
assert SPEC is not None and SPEC.loader is not None
PREPARE_VERCEL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREPARE_VERCEL)
PublicationValidationError = PREPARE_VERCEL.PublicationValidationError
prepare_publication = PREPARE_VERCEL.prepare_publication
ROBOTS_META = PREPARE_VERCEL.ROBOTS_META


@pytest.fixture
def publication_directory() -> Iterator[Path]:
    directory = Path(tempfile.mkdtemp(prefix="publication-", dir=ROOT / "tests"))
    try:
        yield directory
    finally:
        shutil.rmtree(directory)


def _valid_html(*, robots_meta: str = "") -> str:
    payload = {
        "context": {
            "accessibility_mode": "osm",
            "commercial_mode": "osm",
            "data_mode": "estat",
        }
    }
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return (
        f"<!doctype html><html><head><title>分析</title>{robots_meta}</head><body>"
        '<div class="basemap" id="basemap"></div>'
        '<canvas class="map-canvas" id="map"></canvas>'
        "<h1>イオンモールむさし村山</h1><script>"
        f"const BASEMAPS={{}};const DATA={data};const I={{}};"
        "</script></body></html>"
    )


def _write_source(directory: Path, html: str) -> Path:
    source = directory / "map.html"
    source.write_text(html, encoding="utf-8")
    return source


def test_valid_real_data_html_is_copied_with_noindex(publication_directory: Path) -> None:
    source_html = _valid_html()
    source = _write_source(publication_directory, source_html)
    destination = publication_directory / "public" / "index.html"

    size, checks = prepare_publication(source, destination)
    published_html = destination.read_text(encoding="utf-8")

    assert ROBOTS_META in published_html
    assert published_html.count(ROBOTS_META) == 1
    assert source.read_text(encoding="utf-8") == source_html
    assert size == len(published_html.encode())
    assert "実行モード: estat + osm + osm" in checks
    assert "検索エンジン: noindex" in checks
    assert destination.stat().st_mode & 0o777 == 0o644


def test_existing_robots_meta_is_not_duplicated(publication_directory: Path) -> None:
    source = _write_source(publication_directory, _valid_html(robots_meta=ROBOTS_META))
    destination = publication_directory / "public" / "index.html"

    prepare_publication(source, destination)

    assert destination.read_text(encoding="utf-8").count(ROBOTS_META) == 1


@pytest.mark.parametrize(
    ("html", "message"),
    [
        (_valid_html() + "サンプル東京ベイモール", "サンプル施設名"),
        (_valid_html().replace("イオンモールむさし村山", "別施設"), "対象施設名"),
        (_valid_html() + '<script src="leaflet.js"></script>', "旧Leaflet版"),
    ],
)
def test_invalid_html_is_rejected(
    publication_directory: Path, html: str, message: str
) -> None:
    source = _write_source(publication_directory, html)

    with pytest.raises(PublicationValidationError, match=message):
        prepare_publication(source, publication_directory / "public" / "index.html")


def test_validation_failure_does_not_overwrite_existing_public_file(
    publication_directory: Path,
) -> None:
    source = _write_source(publication_directory, _valid_html() + "サンプル東京ベイモール")
    destination = publication_directory / "public" / "index.html"
    destination.parent.mkdir()
    destination.write_text("existing", encoding="utf-8")

    with pytest.raises(PublicationValidationError):
        prepare_publication(source, destination)

    assert destination.read_text(encoding="utf-8") == "existing"


def test_robots_txt_rejects_all_crawlers() -> None:
    robots = (ROOT / "public" / "robots.txt").read_text(encoding="utf-8")

    assert robots == "User-agent: *\nDisallow: /\n"


def test_vercel_only_publishes_public_directory() -> None:
    config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))

    assert config["outputDirectory"] == "public"
    assert "rewrites" not in config
    assert "routes" not in config


def test_authentication_implementation_is_absent() -> None:
    assert not (ROOT / "middleware.ts").exists()
    assert not (ROOT / ".env.example").exists()
    assert not (ROOT / "package.json").exists()
    inspected = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            ROOT / "README.md",
            ROOT / "scripts" / "prepare_vercel.py",
            ROOT / "vercel.json",
        )
    )
    assert "SITE_AUTH_USER" not in inspected
    assert "SITE_AUTH_PASSWORD" not in inspected


def test_public_directory_contains_only_index_and_robots() -> None:
    published_files = {
        path.relative_to(ROOT / "public").as_posix()
        for path in (ROOT / "public").rglob("*")
        if path.is_file()
    }

    assert published_files == {"index.html", "robots.txt"}
