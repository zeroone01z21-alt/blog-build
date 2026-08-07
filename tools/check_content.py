#!/usr/bin/env python3
"""
مدقّق المحتوى — القسم 5.2 · العقد في controls/schema.json
=========================================================

يفحص كل مقال قبل البناء ويفشل قبل أن يُنشر شيء ناقص.

لماذا الرسائل بالعربية
----------------------
الكاتب غير تقني، وهو **من يقرأ هذه الرسائل** لا المطوّر. رسالة مثل
`ValidationError: title length 8 < 10` تجعله يتصل بالمالك؛ ورسالة «العنوان
يجب أن يكون بين 10 و70 محرفًا، وعنوانك 8» يصلحها بنفسه في دقيقة.

القسم 14.2: أي حالة يمكن للكاتب إصلاحها بنفسه ← رسالة بلغته وخطوة تالية
واضحة. أي حالة تقنية ← طمأنة وتصعيد للمالك.

لماذا لا يُكرَّر المخطط هنا
---------------------------
كل حد وكل قيد يُقرأ من `controls/schema.json`. تكرارها في السكربت يعني
انحرافًا صامتًا بين ما يتحقّق منه البناء وما تعرضه اللوحة للكاتب — وهو
بالضبط العيب الذي وُضع القسم 16 لمنعه.

الاستخدام:
    python3 tools/check_content.py <مجلد المحتوى>
    python3 tools/check_content.py content --json    # مخرجات للأتمتة
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA = os.path.join(ROOT, "controls", "schema.json")

IMAGE_EXT = None          # يُملأ من المخطط
FRONT = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


def load_schema():
    with open(SCHEMA, encoding="utf-8") as fh:
        return json.load(fh)


def parse_front_matter(text):
    """YAML مبسّط: يكفي لما يسمح به المخطط (نص، تاريخ، منطقي، لائحة)."""
    m = FRONT.match(text)
    if not m:
        return None, text
    data, block = {}, m.group(1)
    key = None
    for raw in block.split("\n"):
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.lstrip().startswith("-") and key:
            data.setdefault(key, [])
            if isinstance(data[key], list):
                data[key].append(line.lstrip()[1:].strip().strip('"\''))
            continue
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key, val = key.strip(), val.strip()
        if val.startswith("[") and val.endswith("]"):
            inner = val[1:-1].strip()
            data[key] = [x.strip().strip('"\'') for x in inner.split(",") if x.strip()] if inner else []
        elif val in ("true", "false"):
            data[key] = val == "true"
        elif val == "":
            data[key] = []
        else:
            data[key] = val.strip('"\'')
    return data, text[m.end():]


def visible_length(value):
    """طول العنوان كما يراه القارئ — لا نحسب مسافات الأطراف."""
    return len(str(value).strip())


def display(path):
    """مسار قصير مقروء. المحتوى قد يُمرَّر من خارج المستودع (سير العمل
    يستنسخه في مجلد مؤقت)، فلا نفترض أنه تحته."""
    full = os.path.abspath(path)
    return os.path.relpath(full, ROOT) if full.startswith(ROOT + os.sep) else full


def check_file(path, schema, problems):
    rel = display(path)
    text = open(path, encoding="utf-8").read()
    fm, body = parse_front_matter(text)

    def bad(msg):
        problems.append((rel, msg))

    if fm is None:
        bad("الملف لا يبدأ بكتلة إعدادات بين سطري ---. أعد حفظه من اللوحة.")
        return

    # `_index` صفحة قسم لا مقال — هي عنوان المدونة ووصفها، بلا تصنيف
    # ولا صورة مشاركة ولا جسم. مطالبتها بحقول المقال خطأ في المدقّق لا
    # في المحتوى، وكان سيمنع كل بناء.
    if os.path.basename(path).startswith("_index."):
        for name in ("title", "description"):
            rule = schema["fields"].get(name, {})
            val = fm.get(name)
            if not val:
                bad(f"صفحة القسم تحتاج «{name}».")
                continue
            n = visible_length(val)
            lo, hi = rule.get("min_length"), rule.get("max_length")
            if (lo and n < lo) or (hi and n > hi):
                bad((rule.get("error_ar") or "").replace("{actual}", str(n)))
        return

    fields = schema["fields"]
    # قيمة التصنيف في front matter هي slug ثابتة لا الاسم المعروض. هكذا
    # يرتبط المقال العربي والإنجليزي بصفحة أرشيف واحدة مترجمة، ولا يتغيّر
    # الرابط عند تحسين الصياغة المعروضة في schema.json.
    allowed_cats = {c["slug"] for c in schema["categories"]["items"]}

    for name, rule in fields.items():
        val = fm.get(name)
        missing = val is None or (isinstance(val, (str, list)) and len(val) == 0)

        if missing:
            if rule.get("required") and not rule.get("auto"):
                # الحقل غائب، فطوله صفر — وإلا ظهر {actual} حرفيًّا للكاتب
                bad((rule.get("error_ar") or f"الحقل «{name}» مطلوب وهو فارغ.")
                    .replace("{actual}", "0"))
            continue

        if rule["type"] == "string":
            n = visible_length(val)
            lo, hi = rule.get("min_length"), rule.get("max_length")
            if (lo and n < lo) or (hi and n > hi):
                bad((rule.get("error_ar") or f"«{name}» خارج الحدود المسموحة.")
                    .replace("{actual}", str(n)))
            pat = rule.get("pattern")
            if pat and not re.match(pat, str(val)):
                bad(rule.get("error_ar") or f"«{name}» لا يطابق الصيغة المطلوبة.")

        elif rule["type"] == "date":
            # Hugo يرفض تاريخًا بلا ثوانٍ أو منطقة زمنية ويُسقط البناء كله
            # برسالة إنجليزية لا يفهمها الكاتب. أُمسكها هنا برسالة بلغته.
            raw = str(val).strip().strip('"\'')
            try:
                import datetime as _dt
                _dt.datetime.fromisoformat(raw)
                if len(raw) < 19 or ("+" not in raw and "Z" not in raw[10:]):
                    raise ValueError
            except Exception:
                bad(f"التاريخ «{raw}» بصيغة لا يقبلها النظام. "
                    "الصيغة الصحيحة مثل 2026-08-07T20:22:00+03:00 — "
                    "أعد اختياره من التقويم في اللوحة.")

        elif rule["type"] == "list":
            if len(val) < rule.get("min_items", 0):
                bad(rule.get("error_ar") or f"«{name}» يحتاج عنصرًا واحدًا على الأقل.")
            if name == "categories":
                for c in val:
                    if c not in allowed_cats:
                        choices = "، ".join(sorted(allowed_cats))
                        bad(f"التصنيف «{c}» غير معروف. اختر من القائمة في اللوحة "
                            f"(القيم المسموحة: {choices}).")

        elif rule["type"] == "path" and rule.get("must_be_in_bundle"):
            if "/" in str(val) or str(val).startswith("http"):
                bad("صورة المشاركة يجب أن تكون داخل مجلد المقال نفسه، "
                    "لا رابطًا خارجيًّا ولا مسارًا في مجلد آخر.")
            elif not os.path.exists(os.path.join(os.path.dirname(path), str(val))):
                bad(f"لم أجد الصورة «{val}» في مجلد المقال. ارفعها من اللوحة.")

    # جسم فارغ يمرّ من كل الفحوص أعلاه ويُنتج صفحة بيضاء
    if len(body.strip()) < 200 and not fm.get("draft"):
        bad("المقال شبه فارغ. اكتب المحتوى أو أعده مسودة قبل النشر.")


def check_images(directory, schema, problems):
    cap = schema["bundle"]["max_image_bytes"]
    allowed = set(schema["bundle"]["image_formats"])
    name_re = re.compile(schema["filenames"]["pattern"])
    for base, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            # `_index.<lang>.md` أسماء محجوزة في Hugo، وقاعدة التسمية
            # موجّهة لما يرفعه الكاتب لا لما يولّده النظام
            if f.startswith(".") or f.startswith("_index."):
                continue
            ext = f.rsplit(".", 1)[-1].lower()
            full = os.path.join(base, f)
            rel = display(full)
            if not name_re.match(f):
                problems.append((rel, schema["filenames"]["error_ar"].replace("{name}", f)))
            if ext in allowed:
                size = os.path.getsize(os.path.join(base, f))
                if size > cap:
                    problems.append((rel, schema["bundle"]["max_image_error_ar"]
                                     .replace("{name}", f)
                                     .replace("{actual}", f"{size/1024:.0f} كيلوبايت")))


def check_bundle_consistency(directory, problems):
    """الـslug والتصنيفات والأرشفة عقد واحد بين ترجمات الحزمة."""
    blog = os.path.join(directory, "blog")
    if not os.path.isdir(blog):
        return
    for name in sorted(os.listdir(blog)):
        bundle = os.path.join(blog, name)
        if not os.path.isdir(bundle) or name.startswith("."):
            continue
        records = []
        for filename in sorted(os.listdir(bundle)):
            if not (filename.startswith("index.") and filename.endswith(".md")):
                continue
            path = os.path.join(bundle, filename)
            with open(path, encoding="utf-8") as handle:
                fm, _ = parse_front_matter(handle.read())
            if fm is not None:
                records.append((path, fm))
        if not records:
            continue
        first_path, first = records[0]
        expected = {
            "slug": first.get("slug"),
            "archived": bool(first.get("archived", False)),
            "categories": sorted(first.get("categories", [])),
        }
        if expected["slug"] != name:
            problems.append((display(first_path),
                             f"قيمة slug يجب أن تطابق اسم مجلد الحزمة «{name}»."))
        for path, fm in records[1:]:
            actual = {
                "slug": fm.get("slug"),
                "archived": bool(fm.get("archived", False)),
                "categories": sorted(fm.get("categories", [])),
            }
            for field in expected:
                if actual[field] != expected[field]:
                    problems.append((display(path),
                                     f"الحقل «{field}» يجب أن يتطابق بين كل ترجمات الحزمة."))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    directory = args[0] if args else os.path.join(ROOT, "content")
    as_json = "--json" in sys.argv

    if not os.path.isdir(directory):
        print(f"  لا يوجد مجلد محتوى: {directory}")
        return 1

    schema = load_schema()
    problems = []
    count = 0
    for base, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            if f.endswith(".md"):
                count += 1
                check_file(os.path.join(base, f), schema, problems)
    check_bundle_consistency(directory, problems)
    check_images(directory, schema, problems)

    if as_json:
        print(json.dumps([{"file": f, "message": m} for f, m in problems],
                         ensure_ascii=False, indent=2))
        return 1 if problems else 0

    if not problems:
        print(f"  ✅ {count} ملف — لا مشاكل")
        return 0

    print(f"  ❌ {len(problems)} مشكلة في {count} ملف\n")
    last = None
    for f, m in problems:
        if f != last:
            print(f"  ── {f}")
            last = f
        print(f"     • {m}")
    print("\n  البناء متوقّف حتى تُصلَح هذه النقاط.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
