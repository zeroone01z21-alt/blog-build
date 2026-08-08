#!/usr/bin/env python3
"""
خطوط المدونة — بند 13
=====================

يجلب الخطوط ويستضيفها ذاتيًّا ويولّد @font-face، ويفشل إن تجاوزت الميزانية.

القرارات ومبرّراتها
-------------------
**استضافة ذاتية، لا Google Fonts.** الموقع الحالي يحمّل Cairo من
`fonts.googleapis.com` — أي أن كل زائر يُعلِم جوجل بزيارته، ويدفع رحلة DNS
وTLS إضافية قبل أن يظهر النص. التنزيل هنا يحدث **وقت البناء فقط**؛ المخرجات
ملفات محلية لا يصل معها الزائر أي طرف ثالث.

**وزنان ثابتان، لا خط متغيّر.** Cairo متاح متغيّرًا (محور wght 200–1000)،
وبدا الخيار الأذكى: ملف واحد لكل نطاق يغطي كل الأوزان. القياس قال العكس:

    متغيّر   عربي 30.0 + لاتيني 32.9 = 62.8 كيلوبايت
    ثابتان   عربي 26.7 + لاتيني 29.7 = 56.4 كيلوبايت

الثابتان أصغر بـ6.4 كيلوبايت **ويعطيان الوزنين المطلوبين بالضبط** (القسم 9:
«وزنان فقط، عادي وعريض»). المتغيّر يحمل ثمن مرونة لا نستعملها.

تنبيه لمن يعدّل: Google يقرّر الصيغة من شكل الطلب. `wght@400` يعطي ملفًّا
ثابتًا، و`wght@400;700` يعطي المتغيّر. فالطلبان منفصلان هنا عمدًا.

**لا نعيد تجزئة ملفات Google.** جُرّب في 2026-08-02: تجزئة النطاق اللاتيني إلى
الأرقام والترقيم والحروف المستخدمة فقط **كبّرت الملف** من 32.9 إلى 36.8
كيلوبايت. تجزئة Google مضبوطة ومضغوطة أصلًا، وإعادة معالجتها خسارة صافية.
**لا تُقترح ثانية.**

**النطاق اللاتيني من Cairo يُحمَّل مع العربية.** السجل اقترح خط النظام للأحرف
اللاتينية توفيرًا. لكن الأرقام في المدونة إنجليزية بقرار نهائي (القسم 9)،
وعرضها بخط النظام بجوار نص Cairo يُنتج تنافرًا بصريًّا ظاهرًا في كل تاريخ
وكل رقم. الكلفة 32.9 كيلوبايت والميزانية تتّسع لها بفارق مريح.

الميزانية: 110 كيلوبايت لكل صفحة (controls/budgets.json → fonts_total).

الاستخدام:
    python3 tools/build_fonts.py            # يجلب ويقيس ويولّد CSS
    python3 tools/build_fonts.py --check    # يقيس فقط، يفشل عند التجاوز
"""
import json
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "static", "fonts")
CSS_OUT = os.path.join(ROOT, "assets", "fonts", "fonts.css")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# طلبان منفصلان عمدًا: وزن واحد لكل طلب يجعل Google يعطي ملفًّا ثابتًا.
# طلبهما معًا (wght@400;700) يعطي المتغيّر، وهو أكبر بـ6.4 كيلوبايت.
CAIRO_CSS = "https://fonts.googleapis.com/css2?family=Cairo:wght@{w}&display=swap"
CAIRO_WEIGHTS = (400, 700)

# NeueMontreal من الموقع الحالي — **استخراج للقراءة فقط، لا تعديل**.
# الخط مرخَّص ضمن القالب المشترى، فلا يُنزَّل من طرف ثالث ولا يُعاد توزيعه
# خارج نطاقنا. المسار يُمرَّر بمتغيّر بيئة لأن مستودع الموقع خارج هذا المستودع
# ولا نفترض موضعه.
NM_SRC = os.environ.get(
    "Z2O_SITE_FONTS",
    os.path.join(os.path.expanduser("~"), "Desktop", "zero2one_aa1", "assets", "fonts"),
)
NM_FACES = [("NeueMontreal-Regular.otf", "nm-400.woff2", 400),
            ("NeueMontreal-Bold.otf", "nm-700.woff2", 700)]


def budget_bytes():
    path = os.path.join(ROOT, "controls", "budgets.json")
    for b in json.load(open(path, encoding="utf-8"))["budgets"]:
        if b["id"] == "fonts_total":
            return b["max_bytes"]
    raise SystemExit("لم أجد ميزانية الخطوط في controls/budgets.json")


def label(rng):
    if "U+0600" in rng:
        return "arabic"
    if "U+0100" in rng:
        return "latin-ext"
    if "U+0000-00FF" in rng:
        return "latin"
    return "other"


def get(url, binary=False):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    return data if binary else data.decode("utf-8")


def fetch_cairo(check_only):
    faces = []
    for weight in CAIRO_WEIGHTS:
        css = get(CAIRO_CSS.format(w=weight))
        for block in re.findall(r"@font-face\s*{[^}]*}", css):
            url = re.search(r"url\((https://[^)]+\.woff2)\)", block).group(1)
            rng = re.search(r"unicode-range:\s*([^;]+)", block).group(1).strip()
            kind = label(rng)
            if kind == "latin-ext":
                continue      # لا نستخدم اللاتيني الموسّع في المدونة
            name = f"cairo-{kind}-{weight}.woff2"
            dest = os.path.join(OUT, name)
            if not check_only and not os.path.exists(dest):
                os.makedirs(OUT, exist_ok=True)
                open(dest, "wb").write(get(url, binary=True))
            faces.append((weight, name, rng, dest))
    return faces


def convert_neue(check_only):
    faces = []
    try:
        from fontTools.ttLib import TTFont
    except ImportError:
        print("  fonttools غير مثبّت — pip install fonttools brotli")
        return faces
    for src, name, weight in NM_FACES:
        s = os.path.join(NM_SRC, src)
        dest = os.path.join(OUT, name)
        if not os.path.exists(s):
            print(f"  ⚠️  لم أجد {src} — تخطّيت")
            continue
        if not check_only and not os.path.exists(dest):
            os.makedirs(OUT, exist_ok=True)
            f = TTFont(s)
            f.flavor = "woff2"
            f.save(dest)
        faces.append((f"NeueMontreal:{weight}", name, "U+0000-00FF", dest))
    return faces


def write_css(cairo, neue):
    lines = [
        "/* مولَّد من tools/build_fonts.py — لا يُحرَّر يدويًّا */",
        "/* Cairo: وزنان ثابتان لكل نطاق. راجع ترويسة الأداة لسبب رفض المتغيّر. */",
        "",
    ]
    for weight, name, rng, _ in cairo:
        lines += [
            "@font-face {",
            "  font-family: 'Cairo';",
            "  font-style: normal;",
            f"  font-weight: {weight};",
            "  font-display: swap;",
            f"  src: url('{name}') format('woff2');",
            f"  unicode-range: {rng};",
            "}",
            "",
        ]
    for tag, name, rng, _ in neue:
        weight = tag.split(":")[1]
        lines += [
            "@font-face {",
            "  font-family: 'Dennis Sans';",
            "  font-style: normal;",
            f"  font-weight: {weight};",
            "  font-display: swap;",
            f"  src: url('{name}') format('woff2');",
            "}",
            "",
        ]
    os.makedirs(OUT, exist_ok=True)
    open(CSS_OUT, "w", encoding="utf-8").write("\n".join(lines))


def main():
    check_only = "--check" in sys.argv
    cairo = fetch_cairo(check_only)
    neue = convert_neue(check_only)
    if not check_only:
        write_css(cairo, neue)

    def size(path):
        return os.path.getsize(path) if os.path.exists(path) else 0

    ar = sum(size(p) for _, n, _, p in cairo)
    en = sum(size(p) for _, _, _, p in neue)
    cap = budget_bytes()

    print("  الملفات:")
    for _, name, _, path in cairo + neue:
        print(f"    {name:<22} {size(path)/1024:6.1f} KB")
    print()
    print(f"  صفحة عربية   (Cairo)        {ar/1024:6.1f} KB  / {cap/1024:.0f} KB")
    print(f"  صفحة إنجليزية (NeueMontreal) {en/1024:6.1f} KB  / {cap/1024:.0f} KB")

    over = [n for n, v in (("العربية", ar), ("الإنجليزية", en)) if v > cap]
    if over:
        print(f"\n  ❌ تجاوز الميزانية: {', '.join(over)}")
        return 1
    print("\n  ✅ ضمن الميزانية")
    return 0


if __name__ == "__main__":
    sys.exit(main())
