#!/usr/bin/env python3
"""تحقق من مصدر لوحة الكاتب وإعداد Sveltia المولّد."""
from __future__ import annotations

import hashlib
import importlib.util
import os
import re
import sys
from urllib.parse import urlsplit


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADMIN = os.path.join(ROOT, "preview", "admin")
VENDOR = os.path.join(ADMIN, "vendor", "sveltia-cms.js")
INDEX = os.path.join(ADMIN, "index.html")
EXPECTED_VENDOR_SHA256 = "bc0fd1a08e46fc6b80d5dc4c90951bb0eeed346ce8fbadb7dd6dd230379abc03"
EXPECTED_SRI = "sha384-mVjEYeNjgFrDMldKYRXtGqYoTQX7l0LLf7wSUABCSIcQqRQPQckldCncpzRv0zHF"


def load_generator():
    path = os.path.join(ROOT, "tools", "generate_cms.py")
    spec = importlib.util.spec_from_file_location("generate_cms", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("تعذر تحميل مولّد Sveltia")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_base_url(value: str, placeholder: str, problems: list[str]) -> bool:
    if value == placeholder:
        return True
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        problems.append("oauth_base_url يجب أن يكون عنوان HTTPS حقيقيًا بلا بيانات دخول")
        return False
    if parsed.query or parsed.fragment:
        problems.append("oauth_base_url لا يقبل query أو fragment")
        return False
    return True


def main() -> int:
    problems: list[str] = []
    try:
        generator = load_generator()
        schema = generator.load_json(generator.SCHEMA_PATH)
        settings = generator.load_json(generator.SETTINGS_PATH)
        config = generator.build_config(schema, settings)
        expected = generator.expected_outputs()
    except Exception as error:  # تظهر مشكلة المصدر كاملة بدل traceback طويل للكاتب
        print(f"  ❌ تعذر فحص لوحة الكاتب: {error}")
        return 1

    for path, text in expected.items():
        if not os.path.isfile(path):
            problems.append(f"ملف مولّد مفقود: {os.path.relpath(path, ROOT)}")
            continue
        with open(path, encoding="utf-8") as handle:
            if handle.read() != text:
                problems.append(f"ملف مولّد قديم: {os.path.relpath(path, ROOT)}")

    if not os.path.isfile(VENDOR):
        problems.append("حزمة Sveltia المحلية مفقودة")
    elif sha256(VENDOR) != EXPECTED_VENDOR_SHA256:
        problems.append("بصمة حزمة Sveltia المحلية مختلفة")

    if not os.path.isfile(INDEX):
        problems.append("preview/admin/index.html مفقود")
    else:
        with open(INDEX, encoding="utf-8") as handle:
            index = handle.read()
        if EXPECTED_SRI not in index:
            problems.append("SRI المثبت لـSveltia مفقود أو مختلف")
        scripts = re.findall(r'<script\b[^>]*\bsrc=["\']([^"\']+)', index, flags=re.I)
        if scripts != ["./vendor/sveltia-cms.js"]:
            problems.append("index.html يجب أن يحمل نسخة Sveltia المحلية وحدها")
        if 'content="noindex, nofollow, noarchive"' not in index:
            problems.append("وسم noindex للوحة مفقود")

    backend = config.get("backend", {})
    if backend.get("name") != "github":
        problems.append("backend ليس GitHub")
    if backend.get("repo") != "zeroone01z21-alt/blog-content" or backend.get("branch") != "main":
        problems.append("وجهة المحتوى ليست zeroone01z21-alt/blog-content:main")
    if backend.get("auth_methods") != ["oauth"]:
        problems.append("يجب تعطيل الدخول بالرمز والإبقاء على OAuth فقط")
    oauth_pending = validate_base_url(
        str(backend.get("base_url", "")), generator.OAUTH_PLACEHOLDER, problems
    ) and backend.get("base_url") == generator.OAUTH_PLACEHOLDER

    i18n = config.get("i18n", {})
    if i18n.get("structure") != "multiple_files":
        problems.append("بنية i18n لا تنتج ملفات index.<lang>.md")
    if i18n.get("locales") != schema["languages"]["available"]:
        problems.append("لغات اللوحة انحرفت عن schema.json")

    collection_folder, public_folder = generator.bundle_locations(schema)
    if config.get("media_folder") != f"/{collection_folder}":
        problems.append("مجلد الوسائط الجذري مفقود أو خارج نطاق محتوى المدونة")
    if config.get("public_folder") != public_folder:
        problems.append("مسار الوسائط العام لا يطابق مسار المدونة")

    collections = config.get("collections", [])
    if len(collections) != 1 or collections[0].get("name") != "posts":
        problems.append("يجب أن تكون posts المجموعة التحريرية الوحيدة")
    else:
        posts = collections[0]
        if posts.get("delete") is not False:
            problems.append("زر حذف المقالات غير معطل")
        if posts.get("duplicate") is not False:
            problems.append("نسخ المقالات غير معطل")
        if posts.get("folder") != collection_folder or posts.get("path") != "{{slug}}/index":
            problems.append("مسار حزمة Hugo غير صحيح")
        if posts.get("media_folder") != "" or posts.get("public_folder") != "":
            problems.append("صور المقال يجب أن تبقى داخل حزمة Hugo وبمسار نسبي")

        fields = {field.get("name"): field for field in posts.get("fields", [])}
        expected_names = set(schema["fields"]) | {"body"}
        if set(fields) != expected_names:
            problems.append("حقول المقال لا تطابق schema.json + body")
        for name, rule in schema["fields"].items():
            field = fields.get(name, {})
            if field.get("required") != bool(rule.get("required", False)):
                problems.append(f"required للحقل {name} لا يطابق المخطط")
            if "min_length" in rule and field.get("minlength") != rule["min_length"]:
                problems.append(f"minlength للحقل {name} لا يطابق المخطط")
            if "max_length" in rule and field.get("maxlength") != rule["max_length"]:
                problems.append(f"maxlength للحقل {name} لا يطابق المخطط")
            if rule.get("pattern") and field.get("pattern", [None])[0] != rule["pattern"]:
                problems.append(f"pattern للحقل {name} لا يطابق المخطط")

        category = fields.get("categories", {})
        expected_slugs = [item["slug"] for item in schema["categories"]["items"]]
        actual_slugs = [item.get("value") for item in category.get("options", [])]
        if actual_slugs != expected_slugs or not category.get("multiple"):
            problems.append("قائمة التصنيفات لا تطابق slugs المخطط")
        if category.get("min") != schema["fields"]["categories"].get("min_items"):
            problems.append("الحد الأدنى للتصنيفات لا يطابق المخطط")
        if fields.get("featured_image", {}).get("choose_url") is not False:
            problems.append("اختيار صورة من رابط خارجي غير معطل")
        if fields.get("featured_image_alt", {}).get("required") is not True:
            problems.append("النص البديل للصورة غير إلزامي")

    media = config.get("media_libraries", {}).get("all", {})
    if media.get("max_file_size") != schema["bundle"]["max_image_bytes"]:
        problems.append("حد حجم الصور لا يطابق المخطط")
    transform = media.get("transformations", {}).get("raster_image", {})
    if transform.get("format") != "webp" or transform.get("width") != 1600 or transform.get("height") != 1600:
        problems.append("ضغط الصور في المتصفح غير مضبوط")

    if problems:
        print(f"  ❌ فحص لوحة الكاتب فشل — {len(problems)} مشكلة")
        for problem in problems:
            print(f"     - {problem}")
        return 1

    print("  ✅ لوحة الكاتب سليمة: Sveltia 0.179.0 محلية، الحقول من المخطط، والحذف معطل")
    if oauth_pending:
        print("  ⚠️ OAuth غير مفعّل: على المالك وضع oauth_base_url الحقيقي قبل النشر")
    return 0


if __name__ == "__main__":
    sys.exit(main())
