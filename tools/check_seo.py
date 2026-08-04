#!/usr/bin/env python3
"""بوابة SEO لمخرجات Hugo النهائية.

تفحص HTML كما يراه المتصفح (بمحلل HTML من المكتبة القياسية)، لا بتعابير
منتظمة هشة. تشمل العناصر داخل الصفحة والعلاقة بين الصفحات، لذلك تستطيع كشف
hreflang أحادي الاتجاه حتى لو بدت كل صفحة سليمة وحدها.

الاستخدام:
    python3 tools/check_seo.py public
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse


SITE_PREFIX = "https://zero2one.sa/blog/"
KNOWN_LANGUAGES = {"en": "ltr", "ar": "rtl"}
SPACE_RE = re.compile(r"\s+")


def clean_text(value: str) -> str:
    return SPACE_RE.sub(" ", value).strip()


def attr_map(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
    return {name.lower(): value or "" for name, value in attrs}


@dataclass
class Page:
    path: Path
    relative: str
    html: dict[str, str] = field(default_factory=dict)
    titles: list[str] = field(default_factory=list)
    metas: list[dict[str, str]] = field(default_factory=list)
    links: list[dict[str, str]] = field(default_factory=list)
    images: list[dict[str, str]] = field(default_factory=list)
    headings: list[tuple[int, str]] = field(default_factory=list)
    jsonld_raw: list[str] = field(default_factory=list)
    canonical: str = ""
    language: str = ""
    noindex: bool = False
    alternates: dict[str, str] = field(default_factory=dict)
    schemas: list[dict[str, Any]] = field(default_factory=list)

    @property
    def is_404(self) -> bool:
        return self.path.name == "404.html"


class DocumentParser(HTMLParser):
    def __init__(self, page: Page) -> None:
        super().__init__(convert_charrefs=True)
        self.page = page
        self._title: list[str] | None = None
        self._heading_level: int | None = None
        self._heading: list[str] = []
        self._jsonld: list[str] | None = None

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]],
    ) -> None:
        tag = tag.lower()
        values = attr_map(attrs)
        if tag == "html" and not self.page.html:
            self.page.html = values
        elif tag == "title":
            self._title = []
        elif tag == "meta":
            self.page.metas.append(values)
        elif tag == "link":
            self.page.links.append(values)
        elif tag == "img":
            self.page.images.append(values)
        elif len(tag) == 2 and tag[0] == "h" and tag[1] in "123456":
            self._heading_level = int(tag[1])
            self._heading = []
        elif tag == "script" and values.get("type", "").lower() == "application/ld+json":
            self._jsonld = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title" and self._title is not None:
            self.page.titles.append(clean_text("".join(self._title)))
            self._title = None
        elif (
            self._heading_level is not None
            and tag == f"h{self._heading_level}"
        ):
            self.page.headings.append(
                (self._heading_level, clean_text("".join(self._heading)))
            )
            self._heading_level = None
            self._heading = []
        elif tag == "script" and self._jsonld is not None:
            self.page.jsonld_raw.append("".join(self._jsonld).strip())
            self._jsonld = None

    def handle_data(self, data: str) -> None:
        if self._title is not None:
            self._title.append(data)
        if self._heading_level is not None:
            self._heading.append(data)
        if self._jsonld is not None:
            self._jsonld.append(data)


class Check:
    def __init__(self) -> None:
        self.problems: list[tuple[str, str]] = []

    def add(self, page: Page | str, message: str) -> None:
        name = page.relative if isinstance(page, Page) else page
        self.problems.append((name, message))

    def require(self, page: Page | str, condition: bool, message: str) -> None:
        if not condition:
            self.add(page, message)


def expected_url(relative: str) -> str:
    # Hugo percent-encodes non-ASCII path segments in canonical URLs, while
    # Path gives us their decoded filesystem names.
    relative = quote(relative, safe="/")
    if relative == "index.html":
        return SITE_PREFIX
    if relative.endswith("/index.html"):
        return SITE_PREFIX + relative[: -len("index.html")]
    return SITE_PREFIX + relative


def meta_values(page: Page, key: str, *, property_name: bool = False) -> list[str]:
    attr = "property" if property_name else "name"
    return [
        item.get("content", "").strip()
        for item in page.metas
        if item.get(attr, "").lower() == key.lower()
    ]


def link_values(page: Page, rel: str) -> list[dict[str, str]]:
    wanted = rel.lower()
    return [
        item for item in page.links
        if wanted in {part.lower() for part in item.get("rel", "").split()}
    ]


def one_value(
    page: Page,
    values: list[str],
    label: str,
    check: Check,
) -> str:
    check.require(page, len(values) == 1, f"يجب وجود {label} مرة واحدة (الموجود {len(values)})")
    if len(values) != 1:
        return ""
    value = clean_text(values[0])
    check.require(page, bool(value), f"{label} فارغ")
    return value


def valid_absolute_blog_url(value: str) -> bool:
    parsed = urlparse(value)
    return (
        parsed.scheme == "https"
        and parsed.netloc == "zero2one.sa"
        and parsed.path.startswith("/blog/")
        and not parsed.params
        and not parsed.query
        and not parsed.fragment
    )


def flatten_schema(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        result: list[dict[str, Any]] = []
        for item in value:
            result.extend(flatten_schema(item))
        return result
    if not isinstance(value, dict):
        return []
    result = [value] if "@type" in value else []
    graph = value.get("@graph")
    if isinstance(graph, list):
        for item in graph:
            result.extend(flatten_schema(item))
    return result


def schema_types(page: Page) -> set[str]:
    found: set[str] = set()
    for item in page.schemas:
        value = item.get("@type")
        if isinstance(value, str):
            found.add(value)
        elif isinstance(value, list):
            found.update(x for x in value if isinstance(x, str))
    return found


def schema_of_type(page: Page, wanted: str) -> dict[str, Any] | None:
    for item in page.schemas:
        value = item.get("@type")
        if value == wanted or (isinstance(value, list) and wanted in value):
            return item
    return None


def validate_page(page: Page, check: Check) -> None:
    title = one_value(page, page.titles, "عنصر title", check)
    if title:
        check.require(page, 10 <= len(title) <= 70,
                      f"طول title خارج 10–70 محرفًا ({len(title)})")

    description = one_value(
        page, meta_values(page, "description"), "meta description", check,
    )
    if description:
        check.require(page, 50 <= len(description) <= 160,
                      f"طول الوصف خارج 50–160 محرفًا ({len(description)})")

    canonicals = [item.get("href", "") for item in link_values(page, "canonical")]
    page.canonical = one_value(page, canonicals, "canonical", check)
    if page.canonical:
        check.require(page, valid_absolute_blog_url(page.canonical),
                      f"canonical ليس رابط HTTPS مطلقًا داخل /blog/: {page.canonical}")
        check.require(page, page.canonical == expected_url(page.relative),
                      f"canonical لا يطابق مسار الملف: {page.canonical}")

    page.language = page.html.get("lang", "").lower()
    check.require(page, page.language in KNOWN_LANGUAGES,
                  f"lang غير صالح: {page.language or 'مفقود'}")
    if page.language in KNOWN_LANGUAGES:
        check.require(page, page.html.get("dir", "").lower() == KNOWN_LANGUAGES[page.language],
                      f"dir لا يطابق lang={page.language}")
        expected_language = "ar" if page.relative.startswith("ar/") else "en"
        check.require(page, page.language == expected_language,
                      f"لغة HTML لا تطابق مسار الصفحة ({expected_language})")

    robots = ",".join(meta_values(page, "robots")).lower()
    page.noindex = "noindex" in {token.strip() for token in re.split(r"[,\s]+", robots)}
    if page.is_404:
        check.require(page, page.noindex, "صفحة 404 يجب أن تحمل noindex")

    h1 = [text for level, text in page.headings if level == 1]
    check.require(page, len(h1) == 1, f"يجب وجود h1 واحد (الموجود {len(h1)})")
    for level, text in page.headings:
        check.require(page, bool(text), f"h{level} فارغ")
    for (previous, _), (current, text) in zip(page.headings, page.headings[1:]):
        check.require(
            page,
            current <= previous + 1,
            f"قفزة في تسلسل العناوين h{previous} ← h{current}: {text or '(فارغ)'}",
        )

    for index, image in enumerate(page.images, start=1):
        check.require(page, "alt" in image,
                      f"الصورة #{index} بلا خاصية alt: {image.get('src', '')}")
        if "alt" in image:
            check.require(page, bool(clean_text(image["alt"])),
                          f"الصورة #{index} لها alt فارغ: {image.get('src', '')}")

    # عناصر المشاركة إلزامية كذلك؛ فشلها لا يظهر في الصفحة لكنه يكسر واتساب/X.
    social = {
        "og:title": meta_values(page, "og:title", property_name=True),
        "og:description": meta_values(page, "og:description", property_name=True),
        "og:image": meta_values(page, "og:image", property_name=True),
        "og:image:alt": meta_values(page, "og:image:alt", property_name=True),
        "og:url": meta_values(page, "og:url", property_name=True),
        "twitter:card": meta_values(page, "twitter:card"),
        "twitter:title": meta_values(page, "twitter:title"),
        "twitter:description": meta_values(page, "twitter:description"),
        "twitter:image": meta_values(page, "twitter:image"),
    }
    social_values = {
        name: one_value(page, values, name, check) for name, values in social.items()
    }
    if social_values["og:url"] and page.canonical:
        check.require(page, social_values["og:url"] == page.canonical,
                      "og:url لا يطابق canonical")
    for name in ("og:image", "twitter:image"):
        value = social_values[name]
        parsed = urlparse(value)
        if value:
            check.require(page, parsed.scheme == "https" and bool(parsed.netloc),
                          f"{name} يجب أن يكون رابط HTTPS مطلقًا")
    if social_values["twitter:card"]:
        check.require(page, social_values["twitter:card"] == "summary_large_image",
                      "twitter:card يجب أن يكون summary_large_image")

    alternate_links = [
        item for item in link_values(page, "alternate") if item.get("hreflang")
    ]
    for item in alternate_links:
        language = item.get("hreflang", "").lower()
        href = item.get("href", "").strip()
        check.require(page, language in {*KNOWN_LANGUAGES, "x-default"},
                      f"hreflang غير معروف: {language}")
        check.require(page, language not in page.alternates,
                      f"hreflang مكرر: {language}")
        check.require(page, valid_absolute_blog_url(href),
                      f"href غير صالح لـhreflang={language}: {href}")
        if language and language not in page.alternates:
            page.alternates[language] = href
    if page.language:
        check.require(page, page.alternates.get(page.language) == page.canonical,
                      "hreflang الذاتي مفقود أو لا يطابق canonical")
    if "en" in page.alternates:
        check.require(page, "x-default" in page.alternates,
                      "كل صفحة لها بديل إنجليزي تحتاج x-default")
    if "x-default" in page.alternates:
        check.require(page, "en" in page.alternates,
                      "x-default موجود بلا بديل إنجليزي")
        check.require(page, page.alternates.get("x-default") == page.alternates.get("en"),
                      "x-default يجب أن يطابق رابط الإنجليزية")
    for raw in page.jsonld_raw:
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            check.add(page, f"JSON-LD غير صالح: {exc}")
            continue
        page.schemas.extend(flatten_schema(value))

    # الاستثناء الوحيد للبيانات المنظمة هو 404 ذات noindex. لا نعمم الاستثناء
    # على أي صفحة noindex أخرى كي لا يتحول الوسم إلى طريقة لإخفاء خطأ القالب.
    if page.is_404 and page.noindex:
        return

    types = schema_types(page)
    check.require(page, "BreadcrumbList" in types,
                  "BreadcrumbList مفقود من JSON-LD")
    is_paginator = bool(re.fullmatch(
        r"(?:ar/)?(?:categories(?:/[^/]+)?/)?page/\d+/index\.html",
        page.relative,
    ))
    is_collection = page.canonical in {
        SITE_PREFIX, f"{SITE_PREFIX}ar/",
    } or "/categories/" in page.canonical or is_paginator
    expected_type = "CollectionPage" if is_collection else "BlogPosting"
    check.require(page, expected_type in types,
                  f"{expected_type} مفقود من JSON-LD")

    entity = schema_of_type(page, expected_type)
    if entity is not None:
        if expected_type == "BlogPosting":
            main = entity.get("mainEntityOfPage")
            main_id = main.get("@id") if isinstance(main, dict) else main
            check.require(page, main_id == page.canonical,
                          "mainEntityOfPage لا يطابق canonical")
            check.require(page, entity.get("inLanguage") == page.language,
                          "لغة BlogPosting لا تطابق الصفحة")
        else:
            entity_url = entity.get("url") or entity.get("@id")
            check.require(page, entity_url == page.canonical,
                          "رابط CollectionPage لا يطابق canonical")
            check.require(page, entity.get("inLanguage") == page.language,
                          "لغة CollectionPage لا تطابق الصفحة")

    breadcrumb = schema_of_type(page, "BreadcrumbList")
    if breadcrumb is not None:
        items = breadcrumb.get("itemListElement")
        check.require(page, isinstance(items, list) and bool(items),
                      "BreadcrumbList بلا عناصر")
        if isinstance(items, list) and items:
            positions = [item.get("position") for item in items if isinstance(item, dict)]
            check.require(page, positions == list(range(1, len(items) + 1)),
                          "ترتيب BreadcrumbList غير متسلسل")
            last = items[-1] if isinstance(items[-1], dict) else {}
            check.require(page, last.get("item") == page.canonical,
                          "آخر عنصر BreadcrumbList لا يطابق canonical")


def validate_reciprocal_hreflang(pages: list[Page], check: Check) -> None:
    by_canonical: dict[str, Page] = {}
    for page in pages:
        if not page.canonical:
            continue
        if page.canonical in by_canonical:
            check.add(page, f"canonical مكرر مع {by_canonical[page.canonical].relative}")
        else:
            by_canonical[page.canonical] = page

    for page in pages:
        if not page.canonical or not page.language:
            continue
        for language, target_url in page.alternates.items():
            if language == "x-default":
                continue
            target = by_canonical.get(target_url)
            check.require(page, target is not None,
                          f"هدف hreflang غير موجود في البناء: {target_url}")
            if target is None:
                continue
            check.require(page, target.language == language,
                          f"لغة هدف hreflang={language} لا تطابق HTML: {target_url}")
            check.require(
                page,
                target.alternates.get(page.language) == page.canonical,
                f"hreflang غير متبادل مع {target.relative}",
            )


def validate_unique_metadata(pages: list[Page], check: Check) -> None:
    for label, getter in (
        ("title", lambda page: page.titles[0] if len(page.titles) == 1 else ""),
        ("description", lambda page: (
            meta_values(page, "description")[0]
            if len(meta_values(page, "description")) == 1 else ""
        )),
    ):
        seen: dict[str, Page] = {}
        for page in pages:
            if page.noindex:
                continue
            value = clean_text(getter(page))
            if not value:
                continue
            key = value.casefold()
            if key in seen:
                check.add(page, f"{label} مكرر مع {seen[key].relative}")
            else:
                seen[key] = page


def validate_server_files(public: Path, check: Check) -> None:
    root = public / ".htaccess"
    arabic = public / "ar" / ".htaccess"
    check.require(".htaccess", root.is_file(), ".htaccess لم يصل إلى جذر /blog/")
    check.require("ar/.htaccess", arabic.is_file(),
                  ".htaccess العربي لم يصل إلى /blog/ar/")
    if not root.is_file():
        return
    text = root.read_text(encoding="utf-8")
    active = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )
    check.require(".htaccess", not re.search(r"(?im)^\s*Header\b", active),
                  "تعليمة Header ممنوعة في .htaccess المدونة")
    check.require(".htaccess", "ErrorDocument 404 /blog/404.html" in active,
                  "ErrorDocument 404 الإنجليزي مفقود")
    check.require(".htaccess", "ErrorDocument 410 /blog/404.html" in active,
                  "ErrorDocument 410 مفقود")
    check.require(".htaccess", bool(re.search(
        r"(?m)^\s*RewriteRule\s+\^en/\?\$\s+/blog/\s+\[R=301,L,NE\]\s*$",
        active,
    )), "تحويل /blog/en/ الدائم مفقود أو أوسع من المسار المطلوب")
    check.require(".htaccess", "BEGIN verified 410 rules" in text
                  and "END verified 410 rules" in text,
                  "منطقة قواعد 410 الموثقة مفقودة")
    if arabic.is_file():
        ar_text = arabic.read_text(encoding="utf-8")
        check.require("ar/.htaccess", "ErrorDocument 404 /blog/ar/404.html" in ar_text,
                      "ErrorDocument العربي مفقود")
        check.require("ar/.htaccess", "ErrorDocument 410 /blog/ar/404.html" in ar_text,
                      "ErrorDocument 410 العربي مفقود")
        check.require("ar/.htaccess", "BEGIN verified Arabic 410 rules" in ar_text
                      and "END verified Arabic 410 rules" in ar_text,
                      "منطقة قواعد 410 العربية الموثقة مفقودة")
        check.require("ar/.htaccess", not re.search(r"(?im)^\s*Header\b", ar_text),
                      "تعليمة Header ممنوعة في .htaccess العربي")


def report(pages: list[Page], check: Check) -> int:
    if not check.problems:
        images = sum(len(page.images) for page in pages)
        print(f"  ✅ SEO سليم — {len(pages)} صفحة، {images} صورة، hreflang متبادل")
        return 0
    print(f"  ❌ فحص SEO فشل — {len(check.problems)} مشكلة\n")
    last = ""
    for name, message in check.problems:
        if name != last:
            print(f"  ── {name}")
            last = name
        print(f"     • {message}")
    return 1


def main() -> int:
    if len(sys.argv) != 2:
        print("  الاستخدام: check_seo.py <مجلد المخرجات>")
        return 2
    public = Path(sys.argv[1]).resolve()
    check = Check()
    if not public.is_dir():
        check.add(str(public), "مجلد المخرجات غير موجود")
        return report([], check)

    paths = sorted(public.rglob("*.html"))
    check.require(str(public), bool(paths), "لا توجد صفحات HTML")
    pages: list[Page] = []
    for path in paths:
        relative = path.relative_to(public).as_posix()
        page = Page(path=path, relative=relative)
        parser = DocumentParser(page)
        try:
            parser.feed(path.read_text(encoding="utf-8"))
            parser.close()
        except (OSError, UnicodeError) as exc:
            check.add(page, f"تعذّر قراءة HTML: {exc}")
            continue
        pages.append(page)
        validate_page(page, check)

    validate_reciprocal_hreflang(pages, check)
    validate_unique_metadata(pages, check)
    validate_server_files(public, check)
    return report(pages, check)


if __name__ == "__main__":
    sys.exit(main())
