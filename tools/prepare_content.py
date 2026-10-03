#!/usr/bin/env python3
"""جهّز محتوى Hugo من مستودع التحرير واستبعد الحزم المؤرشفة بالكامل.

ويقرأ أرقام الساعة في date وlastmod بتوقيت الرياض (انظر «توقيت المدونة»).

الاستخدام:
    python3 tools/prepare_content.py <content-source>

الوجهة ثابتة عمدًا: ``content/`` داخل مستودع البناء. هذا يمنع تمرير مسار
خاطئ إلى عملية تنظيف ويجعل الناتج مؤقتًا قابلًا لإعادة التوليد.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import sys
import uuid
from pathlib import Path

from check_content import FRONT, parse_front_matter


ROOT = Path(__file__).resolve().parent.parent
DESTINATION = ROOT / "content"
MARKER = ".generated-by-prepare-content"

# ── توقيت المدونة ──────────────────────────────────────────────────────
#
# أرقام الساعة في حقلي التاريخ تُقرأ **دائمًا بتوقيت الرياض**، والإزاحة
# التي كتبها جهاز الكاتب تُهمَل. hugo.toml يضبط timeZone على Asia/Riyadh،
# والرياض بلا توقيت صيفي، فالإزاحة ثابتة.
#
# لماذا: ثلاث مقالات متتالية (12 و16 و23 سبتمبر 2026) خرجت من اللوحة بأرقام
# ساعة الرياض وإزاحة ‎-07:00، أي من جهاز منطقته الزمنية المحيط الهادئ
# وساعته مضبوطة يدويًّا على الرياض. فصار كل مقال من ذلك الجهاز «مجدولًا»
# بعد عشر ساعات، وتخطّاه Hugo بصمت: مقال 16 سبتمبر لم يُنشر قط.
# أرقام الساعة هي ما رآه الكاتب واختاره؛ الإزاحة هي ما يجهله.
#
# يُطبَّق على النسخة المجهّزة وحدها؛ ملف الكاتب في blog-content لا يتغيّر.
RIYADH_OFFSET = "+03:00"
DATE_FIELDS = ("date", "lastmod")
DATE_VALUE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?)?"
    r"\s*(Z|[+-]\d{2}(?::?\d{2})?)?$"
)
DATE_LINE = re.compile(
    r"(?m)^(" + "|".join(DATE_FIELDS) + r"):[ \t]*([\"']?)([^\"'\n]*?)\2[ \t]*$"
)


class PrepareError(RuntimeError):
    pass


class BundleProblem(PrepareError):
    """مشكلة في مقال واحد يصلحها الكاتب، لا في المحتوى كله.

    الرسالة موجّهة للكاتب. في الوضع الصارم (سطر الأوامر والمعاينة) تُرفع
    كما كانت؛ وبنّاء المدونة يسجّلها ويحجز المقال وحده.
    """


def riyadh_wall_clock(raw: str) -> tuple[str, str] | None:
    """('2026-09-16T10:07:00+03:00', '-07:00') — أو None لقيمة غير مفهومة.

    القيمة غير المفهومة تُترك كما هي ليرفضها check_content برسالته.
    """
    match = DATE_VALUE.match(raw.strip())
    if not match:
        return None
    year, month, day, hour, minute, second, offset = match.groups()
    try:
        value = datetime.datetime(
            int(year), int(month), int(day),
            int(hour or 0), int(minute or 0), int(second or 0),
        )
    except ValueError:
        return None
    return value.strftime("%Y-%m-%dT%H:%M:%S") + RIYADH_OFFSET, offset or ""


def normalise_dates(index: Path) -> list[dict[str, str]]:
    """يكتب date وlastmod بأرقامهما على توقيت الرياض. يعيد ما تغيّر."""
    text = index.read_text(encoding="utf-8")
    front = FRONT.match(text)
    if not front:
        return []
    changes: list[dict[str, str]] = []

    def rewrite(match: re.Match[str]) -> str:
        key, quote, raw = match.group(1), match.group(2), match.group(3)
        result = riyadh_wall_clock(raw)
        if result is None or result[0] == raw:
            return match.group(0)
        changes.append({"field": key, "before": raw, "after": result[0],
                        "offset": result[1]})
        return f"{key}: {quote}{result[0]}{quote}"

    block = DATE_LINE.sub(rewrite, front.group(1))
    if changes:
        index.write_text(text[:front.start(1)] + block + text[front.end(1):],
                         encoding="utf-8")
    return changes


def reject_symlinks(source: Path) -> None:
    """لا ننشر ملفًا يستطيع الخروج من checkout المحتوى عبر symlink."""
    if source.is_symlink():
        raise PrepareError(f"مجلد المحتوى لا يجوز أن يكون رابطًا رمزيًا: {source}")
    for base, directories, files in os.walk(source, followlinks=False):
        for name in [*directories, *files]:
            path = Path(base) / name
            if path.is_symlink():
                raise PrepareError(f"الرابط الرمزي غير مسموح في المحتوى: {path}")


def front_matter(path: Path) -> dict[str, object]:
    try:
        data, _ = parse_front_matter(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        raise BundleProblem(
            f"تعذّرت قراءة {path.name}. أعد حفظ المقال من اللوحة."
        ) from exc
    if data is None:
        raise BundleProblem(
            f"الملف {path.name} لا يبدأ بكتلة إعدادات بين سطري ---. أعد حفظه من اللوحة."
        )
    return data


def bundle_is_archived(bundle: Path) -> bool:
    indexes = sorted(bundle.glob("index.*.md"))
    if not indexes:
        raise BundleProblem(
            f"مجلد المقال «{bundle.name}» بلا نصّ (index.<lang>.md) — ربما رُفعت "
            "صورة ولم يُحفظ المقال. افتحه من اللوحة واحفظه، أو أبلغ المالك."
        )
    states = {bool(front_matter(path).get("archived", False)) for path in indexes}
    if len(states) != 1:
        raise BundleProblem(
            "مفتاح «أرشفة المقال» مختلف بين ترجمتي المقال. اجعله متطابقًا في "
            "اللغتين ثم احفظ."
        )
    return states == {True}


def localise_lone_language_resources(bundle: Path) -> int:
    """يمنح موارد الحزمة أحاديّة اللغة لاحقةَ تلك اللغة.

    ‏Hugo ينسب المورد الذي لا يحمل لاحقة لغة إلى اللغة الافتراضية. وحين
    لا تكون للحزمة صفحة بتلك اللغة — مقال عربي وحده مثلًا — يبقى المورد
    بلا صفحة تملكه، فلا تراه الصفحة العربية:

      • صورة داخل النصّ → يسقط البناء كلّه عند خطّاف render-image.
      • صورة المشاركة  → تسقط بصمت إلى صورة الموقع الافتراضية، فتخرج
        بطاقة المشاركة بصورة غير صورة المقال ولا يعرف أحد.

    أُثبت محليًّا على Hugo 0.164.0: بإعادة تسمية صورة واحدة إلى
    ‏«‎….ar.webp» اختفى خطؤها وحدها وبقيت أخطاء البقيّة.

    والحزمة ثنائية اللغة لا تُمسّ: صفحتها الإنجليزية تملك الموارد
    وتشاركها العربية، وإضافة لاحقة هناك تكسر المشاركة.

    يعمل على النسخة المجهَّزة لا على مستودع المحتوى، فلا يتغيّر اسم
    ملف عند الكاتب.
    """
    indexes = sorted(bundle.glob("index.*.md"))
    langs = {path.name.split(".")[1] for path in indexes}
    default_lang = json.loads(
        (ROOT / "controls" / "schema.json").read_text(encoding="utf-8")
    )["languages"]["default"]
    if default_lang in langs or len(langs) != 1:
        return 0

    lang = next(iter(langs))
    known = langs | {"en", "ar"}
    renamed: dict[str, str] = {}
    for item in sorted(bundle.iterdir()):
        if not item.is_file() or item.name.startswith("index."):
            continue
        stem, _, ext = item.name.rpartition(".")
        if not ext or stem.rpartition(".")[2] in known:
            continue
        new_name = f"{stem}.{lang}.{ext}"
        item.rename(bundle / new_name)
        renamed[item.name] = new_name

    if renamed:
        for index in indexes:
            text = index.read_text(encoding="utf-8")
            for old, new in renamed.items():
                text = text.replace(old, new)
            index.write_text(text, encoding="utf-8")
    return len(renamed)


def stage_bundle(bundle: Path, destination: Path) -> dict[str, object]:
    """ينسخ حزمة إلى مكانها المجهّز ويطبّق تحويلات التجهيز كلها.

    بنّاء المدونة يستدعيها أيضًا لنسخة سابقة من مقال منشور، فتمرّ النسخة
    السابقة بالتحويلات نفسها حرفيًّا.
    """
    shutil.copytree(bundle, destination)
    renamed = localise_lone_language_resources(destination)
    dates: list[dict[str, str]] = []
    for index in sorted(destination.glob("index.*.md")):
        for change in normalise_dates(index):
            change["file"] = index.name
            dates.append(change)
    return {"renamed": renamed, "dates": dates}


def prepare(
    source: Path,
    *,
    problems: dict[str, list[str]] | None = None,
    details: dict[str, dict[str, object]] | None = None,
) -> tuple[int, int]:
    """يجهّز content/ من المصدر.

    ``problems``: إن مُرّر، تُسجَّل فيه مشكلات المقال الواحد (BundleProblem)
    باسم مجلده ويُستبعد ذلك المقال وحده. بلا تمريره تُرفع كما كانت دائمًا.
    ``details``: يُملأ بما جرى لكل مقال (أرشفة، تواريخ سُوّيت، صور أُعيدت تسميتها).
    مشكلات المحتوى كله (رابط رمزي، صفحات القسم) تُرفع في الحالتين.
    """
    reject_symlinks(source)
    source = source.resolve()
    if not source.is_dir():
        raise PrepareError(f"مجلد المحتوى غير موجود: {source}")
    if source == DESTINATION.resolve():
        raise PrepareError("المصدر لا يمكن أن يكون مجلد content المولّد نفسه")

    staging = ROOT / f".content-prepared-{uuid.uuid4().hex}"
    staging.mkdir()
    previous: Path | None = None
    copied = 0
    archived = 0
    try:
        index_files = sorted(source.glob("_index.*.md"))
        required_indexes = {"_index.en.md", "_index.ar.md"}
        present_indexes = {path.name for path in index_files}
        missing_indexes = required_indexes - present_indexes
        if missing_indexes:
            raise PrepareError(
                "صفحات قسم المدونة مفقودة: " + ", ".join(sorted(missing_indexes))
            )
        for index_file in index_files:
            shutil.copy2(index_file, staging / index_file.name)

        bundles = source / "blog"
        if bundles.is_dir():
            for bundle in sorted(p for p in bundles.iterdir() if p.is_dir() and not p.name.startswith(".")):
                try:
                    is_archived = bundle_is_archived(bundle)
                except BundleProblem as exc:
                    if problems is None:
                        raise BundleProblem(f"{bundle.name}: {exc}") from exc
                    problems.setdefault(bundle.name, []).append(str(exc))
                    continue
                if is_archived:
                    archived += 1
                    if details is not None:
                        details[bundle.name] = {"archived": True}
                    continue
                info = stage_bundle(bundle, staging / bundle.name)
                if details is not None:
                    details[bundle.name] = {"archived": False, **info}
                copied += 1

        (staging / MARKER).write_text(
            "هذا مجلد مولّد. لا تحرره؛ شغّل tools/prepare_content.py.\n",
            encoding="utf-8",
        )

        # لا نحذف مجلدًا لم تنشئه هذه الأداة. هذا يحمي checkout أو مجلدًا
        # محليًا وُضع باسم content/ بالخطأ من تنظيف واسع وصامت.
        if DESTINATION.exists() or DESTINATION.is_symlink():
            destination_marker = DESTINATION / MARKER
            if (
                DESTINATION.is_symlink()
                or destination_marker.is_symlink()
                or not destination_marker.is_file()
            ):
                raise PrepareError(
                    "مجلد content موجود لكنه ليس ناتج prepare_content؛ لن يُحذف آليًا"
                )
            previous = ROOT / f".content-previous-{uuid.uuid4().hex}"
            os.replace(DESTINATION, previous)
        try:
            os.replace(staging, DESTINATION)
        except OSError:
            if previous is not None and previous.exists() and not DESTINATION.exists():
                os.replace(previous, DESTINATION)
                previous = None
            raise
        if previous is not None:
            shutil.rmtree(previous)
            previous = None
    except OSError as exc:
        raise PrepareError(f"تعذّر نسخ المحتوى أو تثبيت المجلد المولّد: {exc}") from exc
    finally:
        if staging.exists():
            try:
                shutil.rmtree(staging)
            except OSError:
                # فشل التنظيف لا يخفي الخطأ الأصلي؛ المجلد عشوائي ومخفي ولا
                # يُستخدم في البناء ما لم يكتمل os.replace أعلاه.
                pass
        if previous is not None and previous.exists() and not DESTINATION.exists():
            try:
                os.replace(previous, DESTINATION)
            except OSError:
                pass
    return copied, archived


def main() -> int:
    if len(sys.argv) != 2:
        print("  الاستخدام: prepare_content.py <content-source>")
        return 2
    try:
        copied, archived = prepare(Path(sys.argv[1]))
    except PrepareError as exc:
        print(f"  ❌ تجهيز المحتوى فشل: {exc}")
        return 1
    print(f"  ✅ جُهّزت {copied} حزمة · استُبعدت {archived} حزمة مؤرشفة")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
