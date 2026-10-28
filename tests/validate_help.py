"""Gate documental. Artigos publicados necessitam screenshots e manual real.

Rode na raiz do build kit. Não atesta qualidade visual ou captura verdadeira.
"""
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
manifest = yaml.safe_load((ROOT / "docs/help/screenshot-manifest.yaml").read_text(encoding="utf-8"))
assert manifest.get("version") == 1
slugs = set()
for article in manifest["articles"]:
    slug, status = article["slug"], article["status"]
    assert slug not in slugs and ".." not in slug
    slugs.add(slug)
    assert status in {"draft", "published"}
    assert article.get("ui_route", "").startswith("/")
    if status == "published":
        screenshots = article.get("images", [])
        assert len(screenshots) >= 2, f"published requires desktop/mobile screenshots: {slug}"
        names = [Path(x).name for x in screenshots]
        assert "desktop.png" in names and "mobile.png" in names
        assert article.get("e2e_test"), f"E2E test required: {slug}"
        article_path = ROOT / "docs/help/how-to" / f"{slug}.md"
        assert article_path.is_file(), f"missing published how-to: {article_path}"
        manual = article_path.read_text(encoding="utf-8")
        assert "last_verified:" in manual and "product_version:" in manual, f"missing published metadata: {slug}"
        for shot in screenshots:
            path = (ROOT / "docs/help" / shot).resolve()
            assert path.is_relative_to((ROOT / "docs/help").resolve())
            assert path.is_file() and path.stat().st_size > 100, f"missing screenshot: {shot}"
            assert path.name in manual and "![" in manual, f"screenshot must appear in how-to: {shot}"
print(f"PASS: help manifest has {len(slugs)} unique articles; published assets checked")
