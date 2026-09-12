#!/usr/bin/env python3
"""ولّد إعداد Sveltia ودليل الكاتب من عقد المحتوى المركزي.

لا توجد حدود حقول أو أسماء تصنيفات مكررة هنا. كل قاعدة تحريرية تأتي من
controls/schema.json، بينما preview/admin/settings.json يحوي فقط إعدادات
التشغيل غير السرية التي يملكها صاحب المشروع.

الاستخدام:
    python3 tools/generate_cms.py
    python3 tools/generate_cms.py --check
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_PATH = os.path.join(ROOT, "controls", "schema.json")
ADMIN_DIR = os.path.join(ROOT, "preview", "admin")
SETTINGS_PATH = os.path.join(ADMIN_DIR, "settings.json")
CONFIG_PATH = os.path.join(ADMIN_DIR, "config.yml")
GUIDE_PATH = os.path.join(ROOT, "WRITER_GUIDE_AR.md")
OAUTH_PLACEHOLDER = "OWNER_MUST_SET_OAUTH_BASE_URL"

LABELS = {
    "title": "عنوان المقال",
    "meta_title": "عنوان محركات البحث (اختياري)",
    "focus_keyword": "الكلمة المفتاحية المستهدفة (اختياري)",
    "description": "الوصف الذي يظهر في نتائج البحث",
    "slug": "الرابط القصير بالإنجليزية",
    "date": "تاريخ النشر",
    "lastmod": "تاريخ آخر تعديل",
    "draft": "حالة النشر",
    "archived": "أرشفة المقال",
    "categories": "التصنيفات",
    "featured_image": "صورة المشاركة",
    "featured_image_alt": "وصف صورة المشاركة",
}

HINTS = {
    "meta_title": "اتركه فارغًا ليُستعمل عنوان المقال. املأه حين تريد عنوانًا مختلفًا في نتائج جوجل — يظهر كما تكتبه تمامًا، بلا إضافة اسم المدونة. لا يغيّر العنوان داخل الصفحة ولا بطاقة المشاركة.",
    "focus_keyword": "العبارة التي تريد أن يجدك بها الزائر في جوجل. حين تملأها يتحقّق النظام من ورودها في عنوان المقال وفي الوصف وفي نصّه، ويمنع النشر إن غابت عن أحدها. اتركها فارغة إن لم تكن مستهدِفًا عبارة بعينها.",
    "slug": "استخدم حروفًا إنجليزية صغيرة وأرقامًا وشرطات. لا تغيّره بعد أول نشر؛ تغيير الرابط يحتاج تحويل 301 من المالك.",
    "date": "يُملأ تلقائيًا عند إنشاء المقال. عدّله فقط عند جدولة تاريخ النشر.",
    "lastmod": "حدّثه عند تعديل مقال منشور. اتركه فارغًا للمقال الجديد.",
    "draft": "مفعّل = مسودة لا تظهر في الموقع الحي. غير مفعّل = منشور، ما دام مفتاح الأرشفة غير مفعّل.",
    "archived": "فعّله لإخفاء المقال مع إبقائه محفوظًا. الأرشفة هي بديل الحذف.",
    "categories": "اختر تصنيفًا واحدًا على الأقل. الأسماء ثابتة وتُعرض للزائر بلغته.",
    "featured_image": "ارفع صورة من جهازك. تُحفظ داخل مجلد المقال وتُضغط في المتصفح؛ الروابط الخارجية معطلة.",
    "featured_image_alt": "اكتب ما يظهر في الصورة بجملة قصيرة مفيدة، من دون «صورة لـ».",
}

MIME_BY_FORMAT = {
    "avif": "image/avif",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}


def load_json(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"يجب أن يكون {path} كائن JSON")
    return data


def bundle_locations(schema: dict[str, Any]) -> tuple[str, str]:
    """اشتق مساري مستودع المحتوى والرابط العام من العقد المركزي."""
    template = str(schema["bundle"]["path"]).strip("/")
    marker = "/<slug>"
    if not template.endswith(marker):
        raise ValueError("bundle.path يجب أن ينتهي بـ /<slug>/")

    repository_folder = template[: -len(marker)]
    default_locale = schema["languages"]["default"]
    public_folder = str(schema["languages"]["paths"][default_locale]).rstrip("/") or "/"
    return repository_folder, public_folder


def scalar(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def yaml_lines(value: Any, indent: int = 0) -> list[str]:
    """مُصدر YAML صغير وحتمي يكفي بنية إعداد Sveltia.

    تُقتبس النصوص دائمًا بقواعد JSON، وهي صيغة صحيحة داخل YAML؛ هذا يمنع أن
    تتحول قيم مثل ``true`` أو التواريخ إلى أنواع غير مقصودة.
    """
    pad = " " * indent
    if isinstance(value, dict):
        if not value:
            return [pad + "{}"]
        lines: list[str] = []
        for key, item in value.items():
            if isinstance(item, (dict, list)) and item:
                lines.append(f"{pad}{key}:")
                lines.extend(yaml_lines(item, indent + 2))
            elif isinstance(item, dict):
                lines.append(f"{pad}{key}: {{}}")
            elif isinstance(item, list):
                lines.append(f"{pad}{key}: []")
            else:
                lines.append(f"{pad}{key}: {scalar(item)}")
        return lines
    if isinstance(value, list):
        if not value:
            return [pad + "[]"]
        lines = []
        for item in value:
            if isinstance(item, (dict, list)):
                lines.append(pad + "-")
                lines.extend(yaml_lines(item, indent + 2))
            else:
                lines.append(f"{pad}- {scalar(item)}")
        return lines
    return [pad + scalar(value)]


def common_field(name: str, rule: dict[str, Any], *, i18n: Any) -> dict[str, Any]:
    field: dict[str, Any] = {
        "name": name,
        "label": LABELS[name],
        "required": bool(rule.get("required", False)),
        "i18n": i18n,
    }
    if name in HINTS:
        field["hint"] = HINTS[name]
    if "min_length" in rule:
        # الحزمة 0.179.0 ومخطط إعدادها الرسمي يستخدمان الصيغة الصغيرة،
        # رغم أن صفحة التوثيق تعرض minLength/maxLength بحرف L كبير.
        field["minlength"] = int(rule["min_length"])
    if "max_length" in rule:
        field["maxlength"] = int(rule["max_length"])
    if rule.get("pattern"):
        field["pattern"] = [rule["pattern"], rule.get("error_ar", "القيمة غير مقبولة.")]
    return field


def build_fields(schema: dict[str, Any]) -> list[dict[str, Any]]:
    rules = schema["fields"]
    fields: list[dict[str, Any]] = []

    for name in ("title", "meta_title", "focus_keyword", "description"):
        field = common_field(name, rules[name], i18n=True)
        field["widget"] = "string"
        fields.append(field)

    slug = common_field("slug", rules["slug"], i18n="duplicate")
    slug["widget"] = "string"
    fields.append(slug)

    date = common_field("date", rules["date"], i18n="duplicate")
    date.update(**{**{"widget": "datetime",
         # بلا صيغة صريحة تكتب اللوحة "2026-08-07T20:22" فيرفضها Hugo
         # ويسقط البناء كله برسالة إنجليزية لا يفهمها الكاتب.
         # حدث فعليًّا في 2026-08-07 وأوقف النشر.
         # ‏Z لا ZZ: في رموز day.js يعطي Z إزاحةً بنقطتين (+03:00) وZZ
         # بلا نقطتين (+0300). الثانية كتبت "-0700" في 2026-09-12 فرفضها
         # المدقّق وأوقفت نشر مقال جاهز.
         "format": "YYYY-MM-DDTHH:mm:ssZ",
         # وتوقيت الرياض صراحةً لا توقيت جهاز الكاتب: بـlocal صار تاريخ
         # النشر يتبع مكان الكاتب لا مكان القارئ.
         "input_timezone": "Asia/Riyadh",
         "date_format": "YYYY-MM-DD", "time_format": "HH:mm",
         "picker_utc": False}, "default": "{{now}}"})
    fields.append(date)

    lastmod = common_field("lastmod", rules["lastmod"], i18n="duplicate")
    lastmod.update(**{"widget": "datetime",
         # بلا صيغة صريحة تكتب اللوحة "2026-08-07T20:22" فيرفضها Hugo
         # ويسقط البناء كله برسالة إنجليزية لا يفهمها الكاتب.
         # حدث فعليًّا في 2026-08-07 وأوقف النشر.
         # ‏Z لا ZZ: في رموز day.js يعطي Z إزاحةً بنقطتين (+03:00) وZZ
         # بلا نقطتين (+0300). الثانية كتبت "-0700" في 2026-09-12 فرفضها
         # المدقّق وأوقفت نشر مقال جاهز.
         "format": "YYYY-MM-DDTHH:mm:ssZ",
         # وتوقيت الرياض صراحةً لا توقيت جهاز الكاتب: بـlocal صار تاريخ
         # النشر يتبع مكان الكاتب لا مكان القارئ.
         "input_timezone": "Asia/Riyadh",
         "date_format": "YYYY-MM-DD", "time_format": "HH:mm",
         "picker_utc": False})
    fields.append(lastmod)

    draft = common_field("draft", rules["draft"], i18n="duplicate")
    draft.update({
        "widget": "boolean",
        "default": bool(rules["draft"].get("default", True)),
        "before_input": "منشور",
        "after_input": "مسودة",
    })
    fields.append(draft)

    archived = common_field("archived", rules["archived"], i18n="duplicate")
    archived.update({
        "widget": "boolean",
        "default": bool(rules["archived"].get("default", False)),
        "before_input": "نشط",
        "after_input": "مؤرشف",
    })
    fields.append(archived)

    categories = common_field("categories", rules["categories"], i18n="duplicate")
    categories.update({
        "widget": "select",
        "multiple": True,
        "min": int(rules["categories"].get("min_items", 0)),
        "options": [
            {"label": f'{item["en"]} — {item["ar"]}', "value": item["slug"]}
            for item in schema["categories"]["items"]
        ],
    })
    fields.append(categories)

    image = common_field("featured_image", rules["featured_image"], i18n=True)
    accepted = [MIME_BY_FORMAT[ext] for ext in schema["bundle"]["image_formats"] if ext in MIME_BY_FORMAT]
    image.update({
        "widget": "image",
        "choose_url": False,
        "multiple": False,
        "accept": ",".join(dict.fromkeys(accepted)),
    })
    fields.append(image)

    alt = common_field("featured_image_alt", rules["featured_image_alt"], i18n=True)
    alt["widget"] = "string"
    fields.append(alt)

    # أزرار المحرّر — تُذكر صراحةً لا تُترك للافتراضي.
    #
    # ⚠️ heading-one غائب عمدًا. القالب يضع عنوان المقال h1 بنفسه، وبوابة
    # check_seo.py تفرض `len(h1) == 1`. فزرّ h1 في اللوحة يعني كاتبًا يضغطه
    # فيفشل البناء ولا يفهم لماذا — وقد حدث فعلًا في مقال
    # how-to-choose-web-development-company وأُصلح يدويًّا.
    #
    # وتبدأ من h2 لا h3: البوابة تفرض `current <= previous + 1`، فقفزة من
    # h1 (العنوان) إلى h3 تُسقط البناء أيضًا. الكاتب يبدأ بـh2 ثم ينزل.
    fields.append({
        "name": "body",
        "label": "نص المقال",
        "widget": "richtext",
        "required": True,
        "i18n": True,
        # أسماء Netlify القديمة لا أسماء Sveltia الأصلية: المحرّر يمرّر كل
            # اسم عبر خريطة تحويل ثم يُسقط ما ليس فيها بلا تحذير
            # (‏.map(e => MAP[e]).filter(Boolean) في الحزمة). فـ«blockquote»
            # كان يختفي صامتًا — مفتاح الخريطة اسمه «quote».
            # وأزرار الكتلة (العناوين والقوائم والاقتباس) تظهر داخل قائمة ¶
            # المنسدلة لا كأيقونات مستقلّة، وهذا سلوك المحرّر لا نقص فيه.
            "buttons": [
            "bold", "italic",
            "heading-two", "heading-three", "heading-four",
            "heading-five", "heading-six",
            "bulleted-list", "numbered-list",
            "quote", "code", "link",
        ],
        "modes": ["rich-text", "markdown"],
        "hint": (
            "العناوين تبدأ من «عنوان 2» — «عنوان 1» هو عنوان المقال ويضعه "
            "الموقع تلقائيًّا. للربط الداخلي: حدّد الكلمة ثم اضغط زرّ الرابط "
            "واكتب مسارًا يبدأ بـ / مثل /ar/services/seo-riyadh/"
        ),
    })
    return fields


LANG_LABELS = {
    "ar": ("المقالات العربية", "مقال عربي"),
    "en": ("المقالات الإنجليزية", "مقال إنجليزي"),
}


def post_collection(lang: str, collection_folder: str, schema: dict[str, Any]) -> dict[str, Any]:
    """مجموعة تحريرية للغة واحدة.

    مجموعة i18n واحدة لا تستطيع نشر مقال بلغة واحدة في الاتجاهين: Sveltia
    تُبقي default_locale مفعّلة ولا تتيح تعطيلها — رابط توثيقها نفسه
    ‏«disabling-non-default-locale-content» — فأيًّا كانت اللغة الافتراضية
    تبقى مفروضة على كل مقال. ومجموعتان مستقلّتان تحلّان الاتجاهين معًا.

    والتصفية تعمل لأن Sveltia تبني regex من `path` وتطابق به أسماء الملفات
    (scanningPathsRegEx في الحزمة)، فـ«{{slug}}/index.ar» لا يلتقط
    ‏index.en.md ولا العكس.

    والمجلد واحد للاثنتين عمدًا: حزمة صفحة Hugo واحدة لكل مقال، فالمقال
    ثنائي اللغة يُنشأ مرّتين بنفس الـslug فيلتقي ملفّاه في المجلد نفسه
    وتُزاوجهما Hugo تلقائيًّا.
    """
    label, singular = LANG_LABELS[lang]
    fields = [
        {key: value for key, value in field.items() if key != "i18n"}
        for field in build_fields(schema)
    ]
    return {
        "name": f"posts_{lang}",
        "label": label,
        "label_singular": singular,
        "icon": "article",
        "folder": collection_folder,
        "path": "{{slug}}/index." + lang,
        "slug": "{{fields.slug}}",
        "identifier_field": "title",
        "format": "yaml-frontmatter",
        "extension": "md",
        "media_folder": "",
        "public_folder": "",
        "create": True,
        "delete": False,
        "duplicate": False,
        "summary": "{{title}} · {{categories}}",
        "fields": fields,
    }


def build_config(schema: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    languages = schema["languages"]
    fields = schema["fields"]
    collection_folder, public_folder = bundle_locations(schema)
    return {
        "backend": {
            "name": "github",
            "repo": settings["backend_repo"],
            "branch": settings["backend_branch"],
            "base_url": settings["oauth_base_url"],
            "auth_methods": ["oauth"],
        },
        "app_title": "كتابة مدونة ZERO 2 ONE",
        "i18n": {
            "structure": "multiple_files",
            "locales": languages["available"],
            # لا مجموعة تشترك في i18n بعد الآن — لكل لغة مجموعتها. تبقى
            # هذه الكتلة تعريفًا للّغات المعروفة يفحصه check_cms، ولا تحكم
            # سلوك المحرّر.
            "default_locale": languages["default"],
        },
        "slug": {
            "encoding": "ascii",
            "sanitize_replacement": "-",
            "maxlength": int(fields["slug"]["max_length"]),
            "trim": True,
            "lowercase": True,
            "timezone": "local",
        },
        "output": {
            "omit_empty_optional_fields": True,
            "yaml": {"quote": "double", "indent_size": 2, "indent_sequences": True},
        },
        # Sveltia 0.179.0 يشترط media_folder جذريًا حتى مع إعداد مجموعة
        # entry-relative. تقصره هذه القيمة على محتوى المدونة، بينما تبقي
        # القيمتان الفارغتان داخل posts الصور بجانب index.<lang>.md.
        "media_folder": f"/{collection_folder}",
        "public_folder": public_folder,
        "media_libraries": {
            "all": {
                "max_file_size": int(schema["bundle"]["max_image_bytes"]),
                "slugify_filename": True,
                "transformations": {
                    "raster_image": {"format": "webp", "quality": 85, "width": 1600, "height": 1600}
                },
            }
        },
        "collections": [
            post_collection(lang, collection_folder, schema)
            for lang in languages["available"]
        ],
    }


def config_text(config: dict[str, Any]) -> str:
    header = [
        "# مولّد آليًا من controls/schema.json وpreview/admin/settings.json.",
        "# لا تعدّل هذا الملف يدويًا؛ شغّل: python3 tools/generate_cms.py",
        "",
    ]
    return "\n".join(header + yaml_lines(config)) + "\n"


def guide_text(schema: dict[str, Any]) -> str:
    categories = "\n".join(
        f'- **{item["ar"]}** — `{item["slug"]}`'
        for item in schema["categories"]["items"]
    )
    errors = []
    for name, rule in schema["fields"].items():
        if rule.get("error_ar"):
            errors.append(f'- **{LABELS[name]}:** {rule["error_ar"]}')
    errors.append(f'- **اسم الصورة:** {schema["filenames"]["error_ar"]}')
    errors.append(f'- **حجم الصورة:** {schema["bundle"]["max_image_error_ar"]}')
    error_text = "\n".join(errors)
    max_kib = int(schema["bundle"]["max_image_bytes"]) // 1024

    return f"""<!-- مولّد من controls/schema.json؛ لا تعدّل الحدود أو رسائل الأخطاء هنا يدويًا. -->
# دليل كاتب مدونة ZERO 2 ONE

هذا الدليل يكفي لكتابة مقال وحفظه ونشره. لا تحتاج إلى معرفة Git أو كتابة
أوامر. احتفظ برابط اللوحة الذي يرسله لك المالك ولا تشاركه مع أحد.

## 1. الدخول

1. افتح رابط لوحة الكاتب الذي أرسله لك المالك.
2. اكتب اسم المستخدم وكلمة مرور الحماية في نافذة المتصفح.
3. اضغط **Sign in with GitHub**، ثم أكمل التحقق بخطوتين.
4. إذا لم يظهر زر GitHub، أو عاد بك الدخول إلى الصفحة نفسها، لا تنشئ رمزًا
   ولا ترسله لأحد؛ تواصل مع المالك واذكر وقت المشكلة وصورة للشاشة فقط.

## 2. إنشاء مقال جديد

1. اختر **المقالات** ثم **مقال جديد**.
2. ابدأ بالإنجليزية، ثم بدّل اللغة من أعلى المحرر إلى العربية. اللغتان ملفان
   مرتبطان للمقال نفسه، ويجب إكمال الحقول المطلوبة في كلتيهما.
3. اكتب العنوان والوصف والرابط القصير. الرابط حروف إنجليزية صغيرة وأرقام
   وشرطات فقط، مثل `why-ad-campaigns-fail`.
4. لا تغيّر الرابط بعد أول نشر. إذا كان تغييره ضروريًا أرسل الرابط القديم
   والجديد إلى المالك قبل الحفظ، لأن الزوار يحتاجون تحويلًا دائمًا.
5. اختر تصنيفًا واحدًا على الأقل، وارفع صورة مشاركة، ثم اكتب وصف الصورة.
6. اكتب نص المقال بعناوين فرعية واضحة، وراجعه في اللغتين قبل النشر.

## 2.1 العناوين والروابط داخل النصّ

**العناوين تبدأ من «عنوان 2».** «عنوان 1» غير موجود في شريط الأدوات عمدًا:
عنوان المقال الذي كتبته في الأعلى يصير h1 على الصفحة تلقائيًّا، وصفحة
بعنوانين رئيسيين تُربك محركات البحث ويرفضها الفحص قبل النشر.

ولا تقفز درجة. بعد «عنوان 2» يأتي «عنوان 3» لا «عنوان 4». تسلسل العناوين
هو ما تبني منه محركات البحث وقارئات الشاشة خريطةَ مقالك.

**الربط الداخلي:** حدّد الكلمة، اضغط زرّ الرابط 🔗، واكتب مسارًا يبدأ بـ`/`:

| تربط إلى | اكتب |
|---|---|
| صفحة خدمة | `/ar/services/seo-riyadh/` |
| صفحة أعمال | `/ar/work/habba/` |
| مقال آخر | `/blog/ar/why-ad-campaigns-fail/` |
| تواصل معنا | `/ar/contact/` |

اربط الكلمة الوصفية لا كلمة «هنا»: «خدمات تحسين محركات البحث» تفيد القارئ
ومحرك البحث معًا، و«اضغط هنا» لا تفيد أحدًا.

وللنسخة الإنجليزية احذف `/ar` من المسار: `/services/seo-riyadh/`.

## 3. الحالات الثلاث

| الحالة المطلوبة | مفتاح «حالة النشر» | مفتاح «أرشفة المقال» | النتيجة |
|---|---|---|---|
| مسودة | مسودة | نشط | لا تظهر على الموقع الحي؛ تظهر في المعاينة بعد تفعيلها |
| منشور | منشور | نشط | تظهر على المدونة بعد نجاح البناء |
| مؤرشف | أي قيمة | مؤرشف | تختفي من المدونة وتبقى محفوظة |

ابدأ دائمًا بمسودة. الأرشفة هي بديل الحذف؛ لا يوجد زر حذف في اللوحة. إذا
أرشفت مقالًا بالخطأ، أعد المفتاح إلى «نشط» واحفظه.

## 4. الصور

- ارفع صورة من جهازك، ولا تستخدم خيار رابط خارجي؛ هو معطل.
- الصيغ المقبولة: {", ".join(schema["bundle"]["image_formats"])}.
- اللوحة تحوّل الصور النقطية إلى WebP، وتصغّرها إلى حد أقصى 1600×1600،
  ثم يمنع البناء أي صورة تتجاوز {max_kib} كيلوبايت.
- اسم الملف حروف إنجليزية صغيرة وأرقام وشرطات، بلا مسافات.
- وصف الصورة إلزامي في كل لغة. صف ما فيها فعلًا بجملة قصيرة؛ لا تكتب
  «صورة» أو تحشو كلمات بحث.
- لا ترفع صورة عميل أو شخص أو بيانات خاصة من دون موافقة موثقة.

## 5. التصنيفات المتاحة

القائمة ثابتة؛ لا تنشئ تصنيفًا جديدًا ولا تكتب اسمًا يدويًا:

{categories}

القيمة الإنجليزية القصيرة بين العلامتين داخلية فقط؛ الزائر يرى الاسم الكامل
بلغته.

## 6. الحفظ والمعاينة والنشر

1. أثناء الكتابة اترك الحالة **مسودة** والأرشفة **نشط**، ثم احفظ.
2. بعد أن يفعّل المالك موقع المعاينة، انتظر دقيقتين إلى خمس دقائق وافتح رابط
   المعاينة. راجع الهاتف والكمبيوتر واللغتين والصورة والروابط.
3. عندما تصبح النسختان جاهزتين، بدّل حالة النشر إلى **منشور** واترك الأرشفة
   **نشط** ثم احفظ.
4. انتظر رسالة نجاح البناء، ثم افتح
   [المدونة الحية](https://zero2one.sa/blog/) وتأكد أن المقال موجود.
5. إذا فشل البناء، يبقى الموقع السابق سليمًا. أصلح الرسالة التي تظهر لك ثم
   احفظ مرة أخرى. إذا قالت الرسالة إن العطل تقني، أرسلها كاملة إلى المالك.

## 7. رسائل الأخطاء ومعناها

الرسائل التالية تأتي من عقد المحتوى نفسه؛ أصلح الحقل المذكور ثم أعد الحفظ:

{error_text}

قد يظهر رقم بدل `{{actual}}` واسم ملف بدل `{{name}}`. إذا ظهرت رسالة أخرى،
صوّرها كاملة ولا تحذف المقال أو الصورة لمحاولة تجاوزها.

## 8. إذا فقدت الوصول

- لا تنشئ حسابًا جديدًا ولا رمز وصول، ولا ترسل كلمة مرور أو رمز تحقق لأحد.
- جرّب نافذة خاصة وتأكد أن حساب GitHub الصحيح مفتوح.
- استخدم رموز الاسترداد التي سلّمها لك المالك فقط إذا فقدت تطبيق التحقق.
- إذا لم ينجح ذلك، أرسل للمالك: وقت المشكلة، الجهاز والمتصفح، وصورة الخطأ
  من دون أي كلمات مرور أو رموز.
"""


def expected_outputs() -> dict[str, str]:
    schema = load_json(SCHEMA_PATH)
    settings = load_json(SETTINGS_PATH)
    required_settings = ("backend_repo", "backend_branch", "oauth_base_url")
    missing = [key for key in required_settings if not settings.get(key)]
    if missing:
        raise ValueError("إعدادات ناقصة: " + ", ".join(missing))
    config = build_config(schema, settings)
    return {CONFIG_PATH: config_text(config), GUIDE_PATH: guide_text(schema)}


def write_outputs(outputs: dict[str, str], check: bool) -> int:
    stale: list[str] = []
    for path, expected in outputs.items():
        current = None
        if os.path.exists(path):
            with open(path, encoding="utf-8") as handle:
                current = handle.read()
        if current == expected:
            continue
        if check:
            stale.append(os.path.relpath(path, ROOT))
            continue
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(expected)
        print(f"  وُلّد: {os.path.relpath(path, ROOT)}")

    if stale:
        print("  ❌ ملفات لوحة الكاتب قديمة أو مفقودة:")
        for path in stale:
            print(f"     - {path}")
        print("  شغّل: python3 tools/generate_cms.py")
        return 1
    if check:
        print(f"  ✅ ملفات لوحة الكاتب مطابقة للمخطط — {len(outputs)} ملف")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="تحقق بلا كتابة")
    args = parser.parse_args()
    try:
        return write_outputs(expected_outputs(), args.check)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"  ❌ تعذر توليد لوحة الكاتب: {error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
