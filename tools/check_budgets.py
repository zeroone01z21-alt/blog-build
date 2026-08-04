#!/usr/bin/env python3
"""
فحص ميزانيات الأداء — القسم 13.4
=================================

يقيس مخرجات البناء ويفشل قبل النشر عند التجاوز.

القياس حجم النقل لا الحجم الخام
--------------------------------
النصوص (HTML/CSS/JS) تُقاس مضغوطة بـbrotli، والصور والخطوط بحجمها الفعلي
لأنها مضغوطة أصلًا. المبرّر الكامل في ترويسة `controls/budgets.json`.

الدرس الذي فرض هذا: على الموقع الرئيسي قِيس CSS خامًا فأعطى 120 كيلوبايت
وقاد إلى توصية بتقسيمه. القياس المضغوط الحقيقي كان **17**، والتقسيم كان
سيضرّ. **قِس ما يعبر السلك.**

المسار الحرج = HTML الصفحة + كل CSS + خط واحد + صورة LCP.
خط واحد لا كل الخطوط: الصفحة العربية لا تحمّل NeueMontreal والعكس، لأن
`unicode-range` يمنع المتصفح من جلب ما لا يحتاجه.

الاستخدام:
    python3 tools/check_budgets.py public
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    import brotli
    def squeeze(data):
        return len(brotli.compress(data, quality=11))
    METHOD = "brotli"
except ImportError:                       # لا نفشل لغياب مكتبة اختيارية
    import gzip
    def squeeze(data):
        return len(gzip.compress(data, 9))
    METHOD = "gzip (تقدير أعلى قليلًا من brotli)"


def budgets():
    path = os.path.join(ROOT, "controls", "budgets.json")
    return {b["id"]: b for b in json.load(open(path, encoding="utf-8"))["budgets"]}


def transfer(path):
    """حجم ما يعبر السلك: النصوص مضغوطة، الباقي كما هو."""
    ext = path.rsplit(".", 1)[-1].lower()
    raw = open(path, "rb").read()
    if ext in {"html", "css", "js", "json", "xml", "svg", "txt"}:
        return squeeze(raw)
    return len(raw)


def find_pages(root):
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            if f == "index.html":
                yield os.path.join(base, f)


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "public"
    if not os.path.isdir(out):
        print(f"  لا يوجد مجلد بناء: {out}")
        return 1

    caps = budgets()
    problems, warnings = [], []
    print(f"  القياس: {METHOD}\n")

    css_dir = os.path.join(out, "css")
    fonts_dir = os.path.join(out, "fonts")
    css_total = sum(transfer(os.path.join(css_dir, f))
                    for f in os.listdir(css_dir)) if os.path.isdir(css_dir) else 0
    css_total += sum(transfer(os.path.join(fonts_dir, f))
                     for f in os.listdir(fonts_dir)
                     if f.endswith(".css")) if os.path.isdir(fonts_dir) else 0

    def font_bytes(prefix):
        if not os.path.isdir(fonts_dir):
            return 0
        return sum(os.path.getsize(os.path.join(fonts_dir, f))
                   for f in os.listdir(fonts_dir)
                   if f.startswith(prefix) and f.endswith(".woff2"))

    fonts_ar, fonts_en = font_bytes("cairo"), font_bytes("nm-")

    # 1) CSS
    cap = caps["css_total"]["max_bytes"]
    mark = "✅" if css_total <= cap else "❌"
    print(f"  CSS كامل        {css_total/1024:6.1f} / {cap/1024:5.0f} KB  {mark}")
    if css_total > cap:
        problems.append(caps["css_total"]["error_ar"].replace("{actual}", f"{css_total/1024:.1f} KB"))

    # 2) الخطوط لكل لغة
    cap = caps["fonts_total"]["max_bytes"]
    for label, val in (("خطوط عربية", fonts_ar), ("خطوط إنجليزية", fonts_en)):
        if not val:
            continue
        mark = "✅" if val <= cap else "❌"
        print(f"  {label:<14} {val/1024:6.1f} / {cap/1024:5.0f} KB  {mark}")
        if val > cap:
            problems.append(f"{label}: " + caps["fonts_total"]["error_ar"].replace("{actual}", f"{val/1024:.1f} KB"))

    # 3) كل صورة على حدة
    cap = caps["single_image"]["max_bytes"]
    biggest = (0, "")
    for base, dirs, files in os.walk(out):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            if f.rsplit(".", 1)[-1].lower() in {"jpg", "jpeg", "png", "webp", "avif", "gif"}:
                size = os.path.getsize(os.path.join(base, f))
                biggest = max(biggest, (size, f))
                if size > cap:
                    problems.append(caps["single_image"]["error_ar"]
                                    .replace("{name}", f).replace("{actual}", f"{size/1024:.0f} KB"))
    if biggest[0]:
        print(f"  أكبر صورة      {biggest[0]/1024:6.1f} / {cap/1024:5.0f} KB  "
              f"{'✅' if biggest[0] <= cap else '❌'}  ({biggest[1]})")

    # 4) المسار الحرج لكل صفحة
    cap = caps["critical_path"]["max_bytes"]
    worst = (0, "")
    for page in find_pages(out):
        rel = os.path.relpath(page, out)
        font = fonts_ar if rel.startswith("ar" + os.sep) else fonts_en
        # صورة الغلاف إن وُجدت بجوار الصفحة
        cover = 0
        d = os.path.dirname(page)
        for f in os.listdir(d):
            if f.rsplit(".", 1)[-1].lower() in {"jpg", "jpeg", "png", "webp", "avif"}:
                cover = max(cover, os.path.getsize(os.path.join(d, f)))
        total = transfer(page) + css_total + font + cover
        worst = max(worst, (total, rel))
        if total > cap:
            problems.append(f"{rel}: " + caps["critical_path"]["error_ar"]
                            .replace("{actual}", f"{total/1024:.1f} KB"))
    if worst[0]:
        print(f"  أثقل مسار حرج  {worst[0]/1024:6.1f} / {cap/1024:5.0f} KB  "
              f"{'✅' if worst[0] <= cap else '❌'}  ({worst[1]})")

    if warnings:
        print()
        for w in warnings:
            print(f"  ⚠️  {w}")

    if problems:
        print(f"\n  ❌ {len(problems)} تجاوز — النشر متوقّف\n")
        for p in problems:
            print(f"     • {p}")
        print("\n  ⛔ لا تُرفع الحدود لتمرير البناء. القسم 13.4: الأداء لا يتآكل")
        print("     تدريجيًّا — البناء هو ما يمنع التراجع.")
        return 1

    print("\n  ✅ كل الميزانيات ضمن الحدود")
    return 0


if __name__ == "__main__":
    sys.exit(main())
