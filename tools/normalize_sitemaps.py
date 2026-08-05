#!/usr/bin/env python3
"""Move Hugo's multilingual sitemaps to the highest shared URL directory.

Hugo writes the default-language map to ``en/sitemap.xml`` even when English
pages live directly below ``/blog/``. Sitemap scope follows the map's URL
directory, so that file cannot validly describe its parent ``/blog/`` URLs.

This post-build step moves the two maps to ``sitemap-en.xml`` and
``sitemap-ar.xml`` beside the root index, then rewrites the index atomically.
It validates the complete source set before changing any file and is safe to
run repeatedly on the same output directory.

Usage:
    python3 tools/normalize_sitemaps.py public
"""

from __future__ import annotations

import os
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlsplit


NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
ET.register_namespace("", NS)
LANGUAGES = ("en", "ar")


def fail(message: str) -> None:
    raise ValueError(message)


def read_xml(path: Path) -> ET.ElementTree:
    if not path.is_file() or path.is_symlink():
        fail(f"ملف خريطة مفقود أو غير آمن: {path}")
    try:
        return ET.parse(path)
    except ET.ParseError as error:
        fail(f"XML غير صالح في {path}: {error}")


def sitemap_locations(tree: ET.ElementTree, expected_tag: str) -> list[str]:
    root = tree.getroot()
    if root.tag != f"{{{NS}}}{expected_tag}":
        fail(f"الجذر المتوقع {expected_tag} وليس {root.tag}")
    locations = [
        (node.text or "").strip()
        for node in root.findall(f".//{{{NS}}}loc")
    ]
    if not locations or any(not value for value in locations):
        fail("الخريطة تحوي loc فارغًا أو لا تحوي روابط")
    if len(locations) != len(set(locations)):
        fail("الخريطة تحوي روابط مكررة")
    return locations


def validate_url(value: str, prefix: str) -> None:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or not value.startswith(prefix)
    ):
        fail(f"رابط خارج نطاق الخريطة أو غير صالح: {value}")


def validate_and_rewrite(output: Path) -> None:
    if not output.is_dir() or output.is_symlink():
        fail(f"مجلد المخرج غير صالح: {output}")

    index_path = output / "sitemap.xml"
    index_tree = read_xml(index_path)
    index_mode = index_path.stat().st_mode & 0o777
    index_locations = sitemap_locations(index_tree, "sitemapindex")
    index_nodes = index_tree.getroot().findall(f"{{{NS}}}sitemap")
    if len(index_nodes) != len(LANGUAGES):
        fail(f"فهرس الخرائط يجب أن يحوي خريطتين، الموجود {len(index_nodes)}")

    old_suffixes = {lang: f"{lang}/sitemap.xml" for lang in LANGUAGES}
    new_names = {lang: f"sitemap-{lang}.xml" for lang in LANGUAGES}

    # A second run sees the already-normalized index and destination files.
    normalized_prefixes = []
    for location in index_locations:
        for lang, name in new_names.items():
            if location.endswith(name):
                normalized_prefixes.append(location[: -len(name)])
    if len(normalized_prefixes) == len(LANGUAGES):
        if len(set(normalized_prefixes)) != 1:
            fail("روابط الخرائط المطبّعة لا تشترك في جذر واحد")
        for suffix in old_suffixes.values():
            if (output / suffix).exists():
                fail(f"خريطة قديمة زائدة بعد التطبيع: {suffix}")
        prefix = normalized_prefixes[0]
        for lang, name in new_names.items():
            tree = read_xml(output / name)
            urls = sitemap_locations(tree, "urlset")
            required_prefix = prefix if lang == "en" else prefix + "ar/"
            for value in urls:
                validate_url(value, required_prefix)
                if lang == "en" and value.startswith(prefix + "ar/"):
                    fail(f"رابط عربي داخل خريطة الإنجليزية: {value}")
        print("  ✅ الخرائط مطبّعة مسبقًا في جذر المدونة")
        return

    prefix_by_language: dict[str, str] = {}
    for lang, suffix in old_suffixes.items():
        matches = [value for value in index_locations if value.endswith(suffix)]
        if len(matches) != 1:
            fail(f"فهرس الخرائط لا يحوي {suffix} مرة واحدة")
        prefix_by_language[lang] = matches[0][: -len(suffix)]
    if len(set(prefix_by_language.values())) != 1:
        fail("خرائط اللغات لا تشترك في جذر URL واحد")
    prefix = prefix_by_language["en"]
    validate_url(prefix, prefix)
    if not prefix.endswith("/"):
        fail("جذر الخرائط يجب أن ينتهي بشرطة مائلة")

    for lang, suffix in old_suffixes.items():
        source = output / suffix
        tree = read_xml(source)
        urls = sitemap_locations(tree, "urlset")
        required_prefix = prefix if lang == "en" else prefix + "ar/"
        for value in urls:
            validate_url(value, required_prefix)
            if lang == "en" and value.startswith(prefix + "ar/"):
                fail(f"رابط عربي داخل خريطة الإنجليزية: {value}")

    # Rewrite only the two index loc values; retain each optional lastmod.
    for node in index_nodes:
        loc = node.find(f"{{{NS}}}loc")
        if loc is None or not (loc.text or "").strip():
            fail("عنصر sitemap بلا loc")
        current = (loc.text or "").strip()
        for lang, suffix in old_suffixes.items():
            if current.endswith(suffix):
                loc.text = prefix + new_names[lang]
                break
        else:
            fail(f"رابط خريطة غير متوقع في الفهرس: {current}")

    # All validation completed. Moves stay on the same filesystem and replace
    # stale destinations left by a previous non-clean local build.
    for lang, suffix in old_suffixes.items():
        os.replace(output / suffix, output / new_names[lang])

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".sitemap-index-", suffix=".xml", dir=output,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        os.chmod(temporary, index_mode)
        index_tree.write(temporary, encoding="utf-8", xml_declaration=True)
        os.replace(temporary, index_path)
    finally:
        if temporary.exists():
            temporary.unlink()

    # The English directory existed only to hold Hugo's sitemap. Removing it
    # lets the server's explicit /blog/en/ -> /blog/ rule remain authoritative.
    english_dir = output / "en"
    try:
        english_dir.rmdir()
    except OSError:
        fail("مجلد en يحوي مخرجات غير متوقعة بعد نقل الخريطة")

    print(
        "  ✅ نُقلت خرائط اللغات إلى sitemap-en.xml وsitemap-ar.xml "
        "في جذر المدونة"
    )


def main() -> int:
    if len(sys.argv) != 2:
        print("الاستخدام: python3 tools/normalize_sitemaps.py <output-dir>")
        return 2
    try:
        validate_and_rewrite(Path(sys.argv[1]).resolve())
    except (OSError, ValueError) as error:
        print(f"  ❌ تعذّر تطبيع الخرائط: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
