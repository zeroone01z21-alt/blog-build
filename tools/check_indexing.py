#!/usr/bin/env python3
"""تحقق مخرجات الفهرسة: خرائط اللغات، RSS، ومفتاح IndexNow العام."""

from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "controls" / "indexnow.json"
SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
XHTML_NS = "http://www.w3.org/1999/xhtml"
ATOM_NS = "http://www.w3.org/2005/Atom"
KEY_RE = re.compile(r"^[A-Za-z0-9-]{8,128}$")


class Check:
    def __init__(self) -> None:
        self.problems: list[str] = []

    def require(self, condition: bool, message: str) -> None:
        if not condition:
            self.problems.append(message)


def read_xml(path: Path, check: Check) -> ET.Element | None:
    try:
        return ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        check.problems.append(f"XML غير صالح: {path.name} — {exc}")
        return None


def child_text(parent: ET.Element, name: str) -> str:
    node = parent.find(name)
    return (node.text or "").strip() if node is not None else ""


def validate_config(public: Path, check: Check) -> dict[str, str] | None:
    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        check.problems.append(f"تعذّر قراءة controls/indexnow.json: {exc}")
        return None

    required = {
        "endpoint", "host", "key_file", "key_location",
        "deployment_marker", "url_prefix",
    }
    if not isinstance(config, dict):
        check.problems.append("إعداد IndexNow يجب أن يكون كائن JSON")
        return None
    check.require(required <= config.keys(), "إعداد IndexNow ناقص حقولًا إلزامية")
    if not required <= config.keys():
        return None

    valid_strings = True
    for field in required:
        valid = isinstance(config[field], str) and bool(config[field])
        check.require(valid, f"قيمة IndexNow غير صالحة: {field}")
        valid_strings = valid_strings and valid
    if not valid_strings:
        return None

    endpoint = urlparse(config["endpoint"])
    location = urlparse(config["key_location"])
    marker = urlparse(config["deployment_marker"])
    prefix = urlparse(config["url_prefix"])
    check.require(endpoint.geturl() == "https://api.indexnow.org/indexnow",
                  "نقطة IndexNow غير معتمدة")
    check.require(config["host"] == "zero2one.sa", "مضيف IndexNow يجب أن يكون zero2one.sa")
    check.require(prefix.scheme == "https" and prefix.netloc == config["host"],
                  "بادئة روابط IndexNow لا تطابق المضيف")
    check.require(config["url_prefix"] == "https://zero2one.sa/blog/",
                  "IndexNow في هذا المشروع محصور في /blog/")
    check.require(location.scheme == "https" and location.netloc == config["host"],
                  "موقع مفتاح IndexNow ليس على المضيف نفسه")
    check.require(config["key_location"].startswith(config["url_prefix"]),
                  "ملف المفتاح يجب أن يكون داخل /blog/ ليحصر ملكيته في المدونة")
    check.require(marker.scheme == "https" and marker.netloc == config["host"],
                  "موقع علامة النشر ليس على المضيف نفسه")
    check.require(config["deployment_marker"].startswith(config["url_prefix"]),
                  "علامة النشر يجب أن تبقى داخل /blog/")
    check.require(config["deployment_marker"] ==
                  "https://zero2one.sa/blog/indexnow-deploy.txt",
                  "موقع علامة النشر غير معتمد")

    key_rel = Path(config["key_file"])
    check.require(not key_rel.is_absolute() and ".." not in key_rel.parts,
                  "مسار مفتاح IndexNow يجب أن يكون نسبيًا وآمنًا")
    check.require(key_rel.parts and key_rel.parts[0] == "static",
                  "ملف مفتاح IndexNow يجب أن يكون تحت static/")
    source_key = ROOT / key_rel
    output_key = public / key_rel.name
    check.require(source_key.is_file(), f"ملف مفتاح IndexNow مفقود: {key_rel}")
    check.require(output_key.is_file(), f"مفتاح IndexNow لم يصل إلى المخرجات: {key_rel.name}")
    if source_key.is_file() and output_key.is_file():
        source_value = source_key.read_text(encoding="utf-8").strip()
        output_value = output_key.read_text(encoding="utf-8").strip()
        check.require(bool(KEY_RE.fullmatch(source_value)), "صيغة مفتاح IndexNow غير صالحة")
        check.require(source_value == output_value, "مفتاح IndexNow في المخرجات لا يطابق المصدر")
        check.require(Path(location.path).name == key_rel.name,
                      "اسم ملف key_location لا يطابق الملف المنشور")
        check.require(config["key_location"] == f'{config["url_prefix"]}{key_rel.name}',
                      "موقع مفتاح IndexNow غير معتمد")
    return config


def validate_sitemap_index(public: Path, config: dict[str, str], check: Check) -> None:
    root = read_xml(public / "sitemap.xml", check)
    if root is None:
        return
    check.require(root.tag == f"{{{SITEMAP_NS}}}sitemapindex",
                  "sitemap.xml ليس فهرس خرائط")
    locations = {
        child_text(node, f"{{{SITEMAP_NS}}}loc")
        for node in root.findall(f"{{{SITEMAP_NS}}}sitemap")
    }
    expected = {
        f'{config["url_prefix"]}sitemap-en.xml',
        f'{config["url_prefix"]}sitemap-ar.xml',
    }
    check.require(locations == expected,
                  f"فهرس الخرائط لا يطابق اللغتين: {sorted(locations)}")


def validate_language_sitemap(
    path: Path,
    sitemap_url: str,
    language: str,
    config: dict[str, str],
    check: Check,
) -> tuple[set[str], dict[str, dict[str, str]]]:
    root = read_xml(path, check)
    if root is None:
        return set(), {}
    check.require(root.tag == f"{{{SITEMAP_NS}}}urlset", f"{path} ليست urlset")
    parsed_sitemap = urlparse(sitemap_url)
    sitemap_parent = parsed_sitemap.path.rsplit("/", 1)[0] + "/"
    urls: set[str] = set()
    translations: dict[str, dict[str, str]] = {}
    for node in root.findall(f"{{{SITEMAP_NS}}}url"):
        location = child_text(node, f"{{{SITEMAP_NS}}}loc")
        check.require(bool(location), f"رابط فارغ في {path.name}")
        check.require(location not in urls, f"رابط مكرر في {path.name}: {location}")
        if not location:
            continue
        urls.add(location)
        parsed_location = urlparse(location)
        check.require(
            parsed_location.scheme == parsed_sitemap.scheme
            and parsed_location.netloc == parsed_sitemap.netloc
            and parsed_location.path.startswith(sitemap_parent),
            f"رابط خارج نطاق دليل ملف الخريطة {sitemap_url}: {location}",
        )
        check.require(location.startswith(config["url_prefix"]),
                      f"رابط خارج /blog/ في {path.name}: {location}")
        if language == "ar":
            check.require(location.startswith(f'{config["url_prefix"]}ar/'),
                          f"رابط غير عربي في خريطة العربية: {location}")
        else:
            check.require(not location.startswith(f'{config["url_prefix"]}ar/'),
                          f"رابط عربي في خريطة الإنجليزية: {location}")
            check.require(not location.startswith(f'{config["url_prefix"]}en/'),
                          f"بادئة /en/ غير مسموحة للصفحات الإنجليزية: {location}")

        alternates: dict[str, str] = {}
        for link in node.findall(f"{{{XHTML_NS}}}link"):
            hreflang = link.attrib.get("hreflang", "")
            href = link.attrib.get("href", "")
            check.require(hreflang in {"en", "ar"},
                          f"hreflang غير متوقع في الخريطة: {hreflang}")
            check.require(bool(href), f"href فارغ لـhreflang={hreflang}")
            if hreflang and href:
                check.require(hreflang not in alternates,
                              f"hreflang مكرر ({hreflang}): {location}")
                alternates[hreflang] = href
        check.require(alternates.get(language) == location,
                      f"hreflang الذاتي مفقود أو خاطئ: {location}")
        translations[location] = alternates

    home = config["url_prefix"] if language == "en" else f'{config["url_prefix"]}ar/'
    check.require(home in urls, f"صفحة المدونة الرئيسية غائبة من خريطة {language}")
    return urls, translations


def validate_reciprocal_translations(
    en_urls: set[str],
    ar_urls: set[str],
    translations: dict[str, dict[str, str]],
    check: Check,
) -> None:
    for location, alternates in translations.items():
        if "en" in alternates:
            check.require(alternates["en"] in en_urls,
                          f"hreflang=en لا يظهر في خريطة الإنجليزية: {location}")
        if "ar" in alternates:
            check.require(alternates["ar"] in ar_urls,
                          f"hreflang=ar لا يظهر في خريطة العربية: {location}")
        if {"en", "ar"} <= alternates.keys():
            for target in (alternates["en"], alternates["ar"]):
                target_alternates = translations.get(target, {})
                check.require(target_alternates.get("en") == alternates["en"] and
                              target_alternates.get("ar") == alternates["ar"],
                              f"hreflang غير متبادل بين: {location} و{target}")


def validate_rss(
    path: Path,
    language: str,
    sitemap_urls: set[str],
    config: dict[str, str],
    check: Check,
) -> int:
    root = read_xml(path, check)
    if root is None:
        return 0
    check.require(root.tag == "rss" and root.attrib.get("version") == "2.0",
                  f"{path.name} ليست RSS 2.0")
    channel = root.find("channel")
    if channel is None:
        check.problems.append(f"قناة RSS مفقودة: {path}")
        return 0

    home = config["url_prefix"] if language == "en" else f'{config["url_prefix"]}ar/'
    expected_self = f"{home}index.xml"
    check.require(child_text(channel, "title") != "", f"عنوان RSS فارغ: {path}")
    check.require(child_text(channel, "description") != "", f"وصف RSS فارغ: {path}")
    check.require(child_text(channel, "link") == home, f"رابط قناة RSS خاطئ: {path}")
    check.require(child_text(channel, "language") == language, f"لغة RSS خاطئة: {path}")
    self_link = channel.find(f"{{{ATOM_NS}}}link")
    check.require(self_link is not None and self_link.attrib.get("href") == expected_self,
                  f"رابط RSS الذاتي خاطئ: {path}")

    items = channel.findall("item")
    # بعد T8 تحتوي الخريطة صفحات التصنيفات حتى لو لم يوجد أي مقال منشور.
    # لذلك لا نستنتج وجوب عناصر RSS من عدد روابط الخريطة، بل من روابط
    # المقالات نفسها (كل ما ليس الرئيسية/تصنيفًا/صفحة ترقيم).
    expected_items = {
        url for url in sitemap_urls
        if url != home
        and "/categories/" not in url
        and not url.removeprefix(home).startswith("page/")
    }
    actual_items: set[str] = set()
    for item in items:
        link = child_text(item, "link")
        check.require(link not in actual_items, f"عنصر RSS مكرر: {link}")
        if link:
            actual_items.add(link)
        check.require(child_text(item, "title") != "", f"عنصر RSS بلا عنوان: {path}")
        check.require(link in sitemap_urls, f"عنصر RSS غير موجود في الخريطة: {link}")
        check.require(child_text(item, "guid") == link, f"guid لا يطابق الرابط: {link}")
        check.require(child_text(item, "description") != "", f"عنصر RSS بلا وصف: {link}")
    check.require(actual_items == expected_items,
                  f"عناصر RSS لا تطابق المقالات المنشورة: {path}")
    return len(items)


def main() -> int:
    if len(sys.argv) != 2:
        print("  الاستخدام: check_indexing.py <مجلد المخرجات>")
        return 2
    public = Path(sys.argv[1]).resolve()
    check = Check()
    check.require(public.is_dir(), f"مجلد المخرجات غير موجود: {public}")
    if not public.is_dir():
        return report(check)

    required = [
        "index.xml", "ar/index.xml", "sitemap.xml",
        "sitemap-en.xml", "sitemap-ar.xml",
    ]
    for rel in required:
        check.require((public / rel).is_file(), f"مخرج فهرسة مفقود: {rel}")
    check.require(not (public / "en" / "index.html").exists(),
                  "Hugo ولّد تحويل /en/ غير المرغوب؛ فعّل disableDefaultSiteRedirect")
    check.require(not (public / "en" / "sitemap.xml").exists(),
                  "خريطة الإنجليزية القديمة ما زالت متداخلة تحت /en/")
    check.require(not (public / "ar" / "sitemap.xml").exists(),
                  "خريطة العربية القديمة ما زالت متداخلة تحت /ar/")

    config = validate_config(public, check)
    if config is None or any(not (public / rel).is_file() for rel in required):
        return report(check)

    validate_sitemap_index(public, config, check)
    en_urls, en_translations = validate_language_sitemap(
        public / "sitemap-en.xml", f'{config["url_prefix"]}sitemap-en.xml',
        "en", config, check)
    ar_urls, ar_translations = validate_language_sitemap(
        public / "sitemap-ar.xml", f'{config["url_prefix"]}sitemap-ar.xml',
        "ar", config, check)
    translations = {**en_translations, **ar_translations}
    validate_reciprocal_translations(en_urls, ar_urls, translations, check)
    en_items = validate_rss(public / "index.xml", "en", en_urls, config, check)
    ar_items = validate_rss(public / "ar" / "index.xml", "ar", ar_urls, config, check)

    if check.problems:
        return report(check)
    print(f"  ✅ الفهرسة سليمة — EN {len(en_urls)} URL/{en_items} RSS · "
          f"AR {len(ar_urls)} URL/{ar_items} RSS · IndexNow جاهز")
    return 0


def report(check: Check) -> int:
    print(f"  ❌ فحص الفهرسة فشل — {len(check.problems)} مشكلة\n")
    for problem in check.problems:
        print(f"    - {problem}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
