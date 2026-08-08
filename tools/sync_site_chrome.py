#!/usr/bin/env python3
"""
مزامنة هيكل الموقع إلى المدونة
==============================

يستخرج **حرفيًّا** من صفحة داخلية حقيقية في الموقع:

    البرغر · القائمة الجانبية · السوشيال · الفوتر · وسوم CSS و JS

ويكتبها في `layouts/partials/site/`.

لماذا استخراج لا إعادة كتابة
-----------------------------
قرار المالك (2026-08-06، مكرَّرًا ثلاثًا): «الناف بار والسايد والبرغر
والفوتر نفسها في كل صفحة بالموقع بدون أي تعديل أبدًا».

أي محاولة لإعادة كتابتها بأسلوبنا تنتج شيئًا **يشبه** الموقع ولا يطابقه،
وينحرف عنه مع كل تعديل يجري هناك. الاستخراج يجعل الموقع مصدر الحقيقة:
يتغيّر الهيدر في الموقع، نعيد تشغيل هذه الأداة، فتتبعه المدونة.

الكلفة، موثَّقة صراحةً
----------------------
هذا يجلب `bundle.min.css` و`vendor.min.js` و`index-new.min.js` — أي
GSAP و locomotive و barba كاملة. المسار الحرج يتجاوز 220 كيلوبايت،
وميزانية `controls/budgets.json` أُعيد ضبطها **بقرار المالك** لا بتجاوز
صامت من البناء.

المقابل: هوية واحدة عبر النطاق كله. زائر ينتقل من مقال إلى صفحة خدمة لا
يشعر أنه غيّر موقعًا — وهذا يساوي أكثر من كيلوبايتات في نظره.

ملاحظة على الأصول
-----------------
الروابط تُكتب مطلقة إلى `https://zero2one.sa` لا نسبية: المعاينة تعمل على
نطاق فرعي مختلف، ومسار نسبي هناك يعطي 404 صامتًا فتظهر الصفحة بلا تنسيق.
وبصمات `?v=` تُنسخ كما هي، فيصيب المتصفح ذاكرته المخزّنة من زيارته للموقع
ولا يُنزّل الحزمة مرتين.

الاستخدام:
    python3 tools/sync_site_chrome.py <مسار مستودع الموقع>
    python3 tools/sync_site_chrome.py <مسار> --check   # يفشل عند الانحراف
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "layouts", "partials", "site")
PARTIALS = os.path.join(ROOT, "layouts", "partials")
ORIGIN = "https://zero2one.sa"

# صفحة داخلية عادية — لا الرئيسية: هيدر الرئيسية بطل الصفحة لا تنقّل عام
SOURCES = [("en", "work/index.html"), ("ar", "ar/work/index.html")]


def clean(block):
    """يزيل ترويسة XML من الأيقونات المضمّنة.

    `<?xml version="1.0"?>` بلا معنى داخل HTML — المتصفح يتجاهلها كتعليق
    زائف. لكن مصغِّر Hugo يهرّبها إلى `&lt;?xml …` فتظهر **نصًّا مرئيًّا**
    فوق كل سهم في الفوتر. تُحذف عند الاستخراج لا بعده.
    """
    return re.sub(r"<\?xml[^>]*\?>\s*", "", block)


def extract(html):
    """كتلتا الهيكل حول محتوى الصفحة، ووسوم الأصول.

    بنية صفحة الموقع:

        <main class="main inner-page">
          … البرغر · القائمة الجانبية · السوشيال …
          <div class="main-wrap" data-scroll-container>   ← تفتح هنا
            … محتوى الصفحة …
            <div class="footer-rounded-div">…</div>
            <div class="footer-wrap … theme-dark">
              <footer class="section footer">…</footer>
              <div class="overlay overlay-gradient"></div>
            </div>
          </div>                                          ← وتُغلق هنا
        </main>

    لهذا لا يكفي أخذ `<footer>` وحده: قواعد الموقع مكتوبة على الأب —
    `.footer-wrap.theme-dark .footer` و`.footer-wrap.theme-dark
    .overlay-gradient`. فوتر بلا هذا الأب لا يصله أي تنسيق، ويظهر
    كتلةً بيضاء لا تشبه الموقع. والغلاف `data-scroll-container` هو ما
    يمسك locomotive؛ فتحُه بلا إغلاق يكسر التمرير في كل صفحة.

    فالكتلتان تُقتطعان لتُغلّفا المحتوى معًا: `nav` ترصيدها +1 div،
    و`footer` ترصيدها −1، فتتوازنان داخل `<main>` في baseof.html.
    """
    main = re.search(r"<main[^>]*>", html)
    wrap = re.search(r'<div class="main-wrap"[^>]*>', html)
    frd = html.find('<div class="footer-rounded-div"')
    close = html.find("</main>")
    if not (main and wrap and frd > 0 and close > frd):
        raise SystemExit("  ❌ بنية الصفحة تغيّرت — راجع الموقع قبل المزامنة")
    return {
        "nav": clean(html[main.end():wrap.end()]),
        "footer": clean(html[frd:close]),
        "css": re.findall(r'<link[^>]*href="(/assets/css/[^"]+)"', html),
        "js": re.findall(r'<script[^>]*src="(/assets/js/[^"]+)"', html),
    }


def render_assets(css, js):
    head = (
        "{{- /* مولَّد من tools/sync_site_chrome.py — لا يُحرَّر يدويًّا.\n"
        "     مطلق لا نسبي: المعاينة على نطاق فرعي، والمسار النسبي هناك\n"
        "     يعطي 404 صامتًا فتظهر الصفحة بلا تنسيق. */ -}}\n"
    )
    return (
        head + "\n".join(f'<link rel="stylesheet" href="{ORIGIN}{c}">' for c in css) + "\n",
        head + "\n".join(f'<script defer src="{ORIGIN}{j}"></script>' for j in js) + "\n",
    )


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    check = "--check" in sys.argv
    site = args[0] if args else os.path.join(os.path.expanduser("~"), "Desktop", "zero2one_aa1")
    if not os.path.isdir(site):
        print(f"  لا أجد مستودع الموقع: {site}")
        return 1

    os.makedirs(OUT, exist_ok=True)
    drift, wrote = [], 0
    css = js = None

    for lang, rel in SOURCES:
        path = os.path.join(site, rel)
        if not os.path.exists(path):
            print(f"  ❌ مفقود: {rel}")
            return 1
        got = extract(open(path, encoding="utf-8").read())
        css, js = got["css"], got["js"]

        # الكتلتان تغلّفان المحتوى: ما تفتحه الأولى تغلقه الثانية. اختلال
        # هنا يعني صفحةً كاملة بوسوم مفتوحة — عطبٌ صامت في كل مقال.
        def bal(s):
            return len(re.findall(r"<div\b", s)) - len(re.findall(r"</div>", s))
        if bal(got["nav"]) + bal(got["footer"]) != 0:
            print(f"  ❌ {lang}: الكتلتان غير متوازنتين "
                  f"(تنقّل {bal(got['nav']):+d} · فوتر {bal(got['footer']):+d})")
            return 1

        for kind in ("nav", "footer"):
            dest = os.path.join(OUT, f"{kind}-{lang}.html")
            new = got[kind] + "\n"
            old = open(dest, encoding="utf-8").read() if os.path.exists(dest) else None
            if old != new:
                if check:
                    drift.append(f"{kind}-{lang}.html")
                else:
                    open(dest, "w", encoding="utf-8").write(new)
                    wrote += 1
        print(f"  {lang}: تنقّل {len(got['nav']):,} · فوتر {len(got['footer']):,} حرف")

    css_html, js_html = render_assets(css, js)
    for name, body in (("site-css.html", css_html), ("site-scripts.html", js_html)):
        dest = os.path.join(PARTIALS, name)
        old = open(dest, encoding="utf-8").read() if os.path.exists(dest) else None
        if old != body:
            if check:
                drift.append(name)
            else:
                open(dest, "w", encoding="utf-8").write(body)
                wrote += 1

    if check:
        if drift:
            print(f"\n  ❌ هيكل المدونة انحرف عن الموقع — {len(drift)} ملف\n")
            for d in drift:
                print(f"     {d}")
            print("\n  شغّل الأداة بلا --check لمزامنته.")
            return 1
        print("\n  ✅ الهيكل مطابق للموقع")
        return 0

    print(f"\n  ✅ كُتب {wrote} ملف")
    print(f"     CSS: {', '.join(css)}")
    print(f"     JS : {', '.join(js)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
