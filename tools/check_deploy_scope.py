#!/usr/bin/env python3
"""
حارس نطاق النشر
================

يمنع خط بناء المدونة من لمس أي ملف في مستودع الموقع خارج `blog/`.

لماذا هذا موجود
---------------
مزامنة Git في Hostinger تنشر **محتوى مستودع الموقع** إلى `public_html`
وتحذف ما ليس فيه. اكتُشف ذلك في 2026-08-04 حين محا نشرٌ للموقع مجلد
`/blog/` بالكامل — والمدونة كانت تُرفع إليه بـFTP.

فصار لا مفرّ من أن تُسلّم المدونة مخرجاتها داخل مستودع الموقع. وهذا ينقض
العزل الذي بُني عليه القسم 5: خط بناء المدونة صار يملك رمزًا يكتب في
مستودع الموقع الحي.

**هذا الملف هو التعويض.** الرمز يستطيع تقنيًّا الكتابة في كل المستودع؛
هذا الفحص يجعل السكربت يرفض. الفرق أن الرفض مكتوب، ومسار `tools/`
محمي بـCODEOWNERS، وبصمة الضوابط تُفشل البناء إن عُدِّل بلا مراجعة.

الصراحة الواجبة: هذه طبقة **في السكربت** لا في المنصة. من يعدّل السكربت
يتجاوزها — لكنه يفعل ذلك في تغيير ظاهر يمرّ بمراجعة، لا صامتًا.

الاستخدام:
    python3 tools/check_deploy_scope.py <مسار مستودع الموقع> [--prefix blog/]
"""
import os
import subprocess
import sys

ALLOWED_PREFIX = "blog/"


def changed_paths(repo):
    """كل ما تغيّر في شجرة العمل مقارنةً بـHEAD، متتبَّعًا كان أو جديدًا."""
    out = subprocess.run(
        ["git", "-C", repo, "status", "--porcelain=v1", "--untracked-files=all"],
        capture_output=True, text=True, check=True).stdout
    paths = []
    for line in out.splitlines():
        if not line.strip():
            continue
        entry = line[3:]
        # إعادة التسمية تُكتب "قديم -> جديد" — الطرفان يهمّان
        if " -> " in entry:
            paths.extend(p.strip().strip('"') for p in entry.split(" -> "))
        else:
            paths.append(entry.strip().strip('"'))
    return paths


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print("  الاستخدام: check_deploy_scope.py <مسار مستودع الموقع>")
        return 1
    repo = args[0]
    prefix = ALLOWED_PREFIX
    for a in sys.argv[1:]:
        if a.startswith("--prefix="):
            prefix = a.split("=", 1)[1]

    if not os.path.isdir(os.path.join(repo, ".git")):
        print(f"  ليس مستودع Git: {repo}")
        return 1

    paths = changed_paths(repo)
    if not paths:
        print("  لا تغييرات — لا شيء لنشره")
        return 0

    outside = sorted({p for p in paths if not p.startswith(prefix)})
    inside = [p for p in paths if p.startswith(prefix)]

    print(f"  داخل {prefix}: {len(inside)} ملف")

    if outside:
        print(f"\n  ❌ البناء لمس {len(outside)} ملفًا خارج «{prefix}» — النشر متوقّف\n")
        for p in outside[:25]:
            print(f"     {p}")
        if len(outside) > 25:
            print(f"     … و{len(outside)-25} غيرها")
        print("\n  خط بناء المدونة لا يملك حق تعديل ملفات الموقع.")
        print("  إن كان التغيير مقصودًا فهو تعديل على الموقع، يُجرى في مستودعه")
        print("  بمراجعة، لا من هنا.")
        return 1

    print("  ✅ كل التغييرات داخل النطاق المسموح")
    return 0


if __name__ == "__main__":
    sys.exit(main())
