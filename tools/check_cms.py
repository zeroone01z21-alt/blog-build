#!/usr/bin/env python3
"""تحقق من مصدر لوحة الكاتب وإعداد Sveltia المولّد."""
from __future__ import annotations

import hashlib
import importlib.util
import os
import io
import re
import sys
from urllib.parse import urlsplit


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADMIN = os.path.join(ROOT, "preview", "admin")
VENDOR = os.path.join(ADMIN, "vendor", "sveltia-cms.js")
INDEX = os.path.join(ADMIN, "index.html")
EXPECTED_VENDOR_SHA256 = "bc0fd1a08e46fc6b80d5dc4c90951bb0eeed346ce8fbadb7dd6dd230379abc03"
EXPECTED_SRI = "sha384-mVjEYeNjgFrDMldKYRXtGqYoTQX7l0LLf7wSUABCSIcQqRQPQckldCncpzRv0zHF"


def known_mode_names() -> set[str]:
    """أسماء أوضاع المحرّر التي تقبلها نسخة Sveltia المرفقة.

    مثل الأزرار تمامًا: الاسم المجهول يُحذف صامتًا. والفرق أن قائمة أوضاع
    فارغة تُعطّل شريط الأدوات **كلَّه** لا زرًّا واحدًا — حدث فعليًّا مع
    ‏"rich-text"/"markdown" بدل "rich_text"/"raw".
    """
    try:
        blob = io.open(VENDOR, encoding="utf-8", errors="ignore").read()
    except OSError:
        return set()
    match = re.search(r"\{rich_text:`[^`]+`,raw:`[^`]+`\}", blob)
    if not match:
        return set()
    return set(re.findall(r"(\w+):`", match.group(0)))


def known_button_names() -> set[str]:
    """أسماء أزرار المحرّر التي تقبلها نسخة Sveltia المرفقة.

    المحرّر يمرّر كل اسم في `buttons` عبر خريطة أسماء Netlify القديمة ثم
    يُسقط ما ليس فيها بلا تحذير ولا خطأ — .map(e => MAP[e]).filter(Boolean)
    في الحزمة. فزرٌّ باسم خاطئ لا يظهر، ولا شيء يقول لماذا. حدث فعليًّا مع
    «blockquote»: الاسم المقبول «quote».

    تُقرأ الخريطة من الحزمة نفسها لا من قائمة مكتوبة هنا، فتبقى صحيحة إذا
    رُقّيت Sveltia وتغيّرت أسماؤها.
    """
    try:
        blob = io.open(VENDOR, encoding="utf-8", errors="ignore").read()
    except OSError:
        return set()
    anchor = blob.find('"heading-one":')
    if anchor == -1:
        return set()
    start = blob.rfind("{", 0, anchor)
    end = blob.find("}", anchor)
    if start == -1 or end == -1:
        return set()
    pairs = re.findall(r'(?:"([a-z-]+)"|\b([a-z-]+))\s*:\s*`', blob[start:end])
    return {quoted or bare for quoted, bare in pairs}


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

    # مجموعة لكل لغة — لا مجموعة i18n واحدة.
    #
    # ‏Sveltia لا تتيح تعطيل default_locale، فمجموعة واحدة تفرض لغةً ما على
    # كل مقال. المجموعتان تحرّران الاتجاهين، وهذا الحارس يفرض القواعد نفسها
    # على كلٍّ منهما بلا تخفيف.
    # مجموعة تحريرية لكل لغة — لا مجموعة i18n واحدة.
    #
    # ‏Sveltia لا تتيح تعطيل default_locale، فمجموعة واحدة تفرض لغةً ما على
    # كل مقال. المجموعتان تحرّران الاتجاهين، وهذا الحارس يفرض القواعد نفسها
    # على كلٍّ منهما بلا تخفيف.
    collections = config.get("collections", [])
    languages = schema["languages"]["available"]
    expected_collections = [f"posts_{lang}" for lang in languages]
    if [c.get("name") for c in collections] != expected_collections:
        problems.append(
            "المجموعات التحريرية يجب أن تكون " + " و".join(expected_collections)
        )
    else:
        allowed_buttons = known_button_names()
        allowed_modes = known_mode_names()
        for lang, posts in zip(languages, collections):
            expected_path = "{{slug}}/index." + lang
            if posts.get("delete") is not False:
                problems.append(f"[{lang}] زر حذف المقالات غير معطل")
            if posts.get("duplicate") is not False:
                problems.append(f"[{lang}] نسخ المقالات غير معطل")
            if posts.get("folder") != collection_folder or posts.get("path") != expected_path:
                problems.append(f"[{lang}] مسار حزمة Hugo غير صحيح")
            if posts.get("media_folder") != "" or posts.get("public_folder") != "":
                problems.append(f"[{lang}] صور المقال يجب أن تبقى داخل حزمة Hugo وبمسار نسبي")
            if posts.get("i18n"):
                problems.append(f"[{lang}] المجموعة تشترك في i18n فتفرض اللغة الأخرى")

            fields = {field.get("name"): field for field in posts.get("fields", [])}
            expected_names = set(schema["fields"]) | {"body"}
            if set(fields) != expected_names:
                problems.append(f"[{lang}] حقول المقال لا تطابق schema.json + body")
            for name, rule in schema["fields"].items():
                field = fields.get(name, {})
                if field.get("required") != bool(rule.get("required", False)):
                    problems.append(f"[{lang}] required للحقل {name} لا يطابق المخطط")
                if "min_length" in rule and field.get("minlength") != rule["min_length"]:
                    problems.append(f"[{lang}] minlength للحقل {name} لا يطابق المخطط")
                if "max_length" in rule and field.get("maxlength") != rule["max_length"]:
                    problems.append(f"[{lang}] maxlength للحقل {name} لا يطابق المخطط")
                if rule.get("pattern") and field.get("pattern", [None])[0] != rule["pattern"]:
                    problems.append(f"[{lang}] pattern للحقل {name} لا يطابق المخطط")

            category = fields.get("categories", {})
            expected_slugs = [item["slug"] for item in schema["categories"]["items"]]
            actual_slugs = [item.get("value") for item in category.get("options", [])]
            if actual_slugs != expected_slugs or not category.get("multiple"):
                problems.append(f"[{lang}] قائمة التصنيفات لا تطابق slugs المخطط")
            if category.get("min") != schema["fields"]["categories"].get("min_items"):
                problems.append(f"[{lang}] الحد الأدنى للتصنيفات لا يطابق المخطط")
            if fields.get("featured_image", {}).get("choose_url") is not False:
                problems.append(f"[{lang}] اختيار صورة من رابط خارجي غير معطل")
            if fields.get("featured_image_alt", {}).get("required") is not True:
                problems.append(f"[{lang}] النص البديل للصورة غير إلزامي")

            # أوضاع المحرّر: القائمة الفارغة تُعطّل الشريط كلَّه.
            modes = fields.get("body", {}).get("modes", [])
            bad_modes = sorted(set(modes) - allowed_modes)
            if allowed_modes and bad_modes:
                problems.append(
                    f"[{lang}] أوضاع محرّر مجهولة تُعطّل شريط الأدوات كلَّه: "
                    + "، ".join(bad_modes)
                )

            # أزرار المحرّر: الاسم المجهول يُحذف بلا صوت ولا خطأ.
            unknown = sorted(set(fields.get("body", {}).get("buttons", [])) - allowed_buttons)
            if allowed_buttons and unknown:
                problems.append(
                    f"[{lang}] أزرار لا تعرفها Sveltia فستختفي صامتة: " + "، ".join(unknown)
                )

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
