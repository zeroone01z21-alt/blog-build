#!/usr/bin/env python3
"""
بصمة مزانة الضوابط — القسم 12.6
================================

يُفشل البناء إذا تغيّر أي ملف ضوابط دون تحديث بصمته صراحةً.

لماذا هذا موجود
---------------
ضوابط النسخ السابقة كانت **تعليمات** تعتمد على التزام من يقرؤها. أي وكيل — أو
أي إنسان مستعجل — يستطيع رفع حدّ ميزانية ليمرّر بناءً فاشلاً، ولن يلاحظ أحد.

هذا الملف يجعل ذلك **مرئياً**: كل ملف ضوابط له بصمة مسجّلة. تغييرٌ بلا تحديث
البصمة يوقف البناء. وتحديث البصمة يظهر في الـdiff كسطر صريح لا يمكن تفويته.

الصراحة الواجبة: هذا **تلاعب مكشوف لا تلاعب ممنوع**. من يملك صلاحية الكتابة
يستطيع تعديل الملف وبصمته معاً. الفرق أن ذلك يصير فعلاً متعمّداً ظاهراً في
سجل المراجعة، لا تغييراً صامتاً. حماية الفروع على GitHub هي الطبقة التي تحوّله
إلى ممنوع — وهي مفعّلة على هذا المستودع لأنه عام.

الملف يبصم **نفسه** أيضاً. تعطيل الفحص بتعديله يُسقط بصمته فيفشل الفحص.

الاستخدام
---------
    python3 tools/check_controls.py            # يفشل بخروج 1 عند أي اختلاف
    python3 tools/check_controls.py --update   # يعيد توليد البصمات (فعل متعمّد)
"""
import hashlib
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "controls", "fingerprints.txt")

# كل ما يقع تحت هذه المسارات يُبصَم. إضافة ملف جديد فيها دون تسجيله = فشل،
# وهذا مقصود: لا يتسلل سير عمل جديد بلا مراجعة.
GUARDED_DIRS = [".github/workflows", "controls"]
# البوابات نفسها مبصومة: من يعطّل بوابةً يفعلها في تغيير ظاهر لا صامت.
GUARDED_FILES = [
    "CLAUDE.md",
    "ARCHITECTURE.md",
    "tools/check_controls.py",
    "tools/check_deploy_scope.py",   # يمنع لمس ملفات الموقع خارج blog/
    "tools/check_budgets.py",        # يمنع تآكل الأداء
    "tools/check_content.py",        # يمنع النشر الناقص
    "tools/check_indexing.py",       # يثبت عقد الخرائط وRSS وIndexNow
    "tools/indexnow.py",             # يحصر الإخطار في روابط المدونة المنشورة
]
EXCLUDE = {"controls/fingerprints.txt"}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def guarded_paths():
    """كل ملفات الضوابط الموجودة فعلياً، بمسارات نسبية مرتّبة."""
    found = set()
    for d in GUARDED_DIRS:
        base = os.path.join(ROOT, d)
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [x for x in dirnames if not x.startswith(".")]
            for name in filenames:
                if name.startswith("."):
                    continue
                rel = os.path.relpath(os.path.join(dirpath, name), ROOT)
                if rel not in EXCLUDE:
                    found.add(rel)
    for f in GUARDED_FILES:
        if os.path.exists(os.path.join(ROOT, f)):
            found.add(f)
    return sorted(found)


def read_manifest():
    if not os.path.exists(MANIFEST):
        return None
    recorded = {}
    with open(MANIFEST, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            digest, _, path = line.partition("  ")
            if digest and path:
                recorded[path] = digest
    return recorded


def write_manifest(paths):
    lines = [
        "# بصمات ملفات الضوابط — القسم 12.6",
        "# لا يُحرَّر يدوياً. وَلِّده بـ: python3 tools/check_controls.py --update",
        "# تحديثه فعل متعمّد يظهر في المراجعة — وهذا هو الغرض منه.",
        "",
    ]
    for rel in paths:
        lines.append(f"{sha256(os.path.join(ROOT, rel))}  {rel}")
    with open(MANIFEST, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"  حُدِّثت البصمات: {len(paths)} ملف")


def main():
    paths = guarded_paths()

    if "--update" in sys.argv:
        write_manifest(paths)
        return 0

    recorded = read_manifest()
    if recorded is None:
        print("  ❌ لا يوجد controls/fingerprints.txt — وَلِّده بـ --update")
        return 1

    problems = []

    for rel in paths:
        actual = sha256(os.path.join(ROOT, rel))
        if rel not in recorded:
            problems.append(("ملف ضوابط غير مسجَّل", rel,
                             "أُضيف دون تسجيل بصمته — سير عمل أو إعداد يتسلل بلا مراجعة"))
        elif recorded[rel] != actual:
            problems.append(("بصمة مختلفة", rel,
                             "تغيّر محتواه دون تحديث البصمة"))

    for rel in recorded:
        if rel not in paths:
            problems.append(("ملف مسجَّل مفقود", rel,
                             "حُذف أو نُقل دون تحديث البصمة"))

    if not problems:
        print(f"  ✅ الضوابط سليمة — {len(paths)} ملف مطابق")
        return 0

    print(f"  ❌ فحص الضوابط فشل — {len(problems)} مشكلة\n")
    for kind, rel, why in problems:
        print(f"    {kind}: {rel}")
        print(f"      {why}\n")
    print("  إن كان التغيير مشروعاً، شغّل:")
    print("      python3 tools/check_controls.py --update")
    print("  وضمّ الناتج في نفس العملية ليراه المراجِع.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
