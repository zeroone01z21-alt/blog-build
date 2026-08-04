#!/usr/bin/env python3
"""جهّز محتوى Hugo من مستودع التحرير واستبعد الحزم المؤرشفة بالكامل.

الاستخدام:
    python3 tools/prepare_content.py <content-source>

الوجهة ثابتة عمدًا: ``content/`` داخل مستودع البناء. هذا يمنع تمرير مسار
خاطئ إلى عملية تنظيف ويجعل الناتج مؤقتًا قابلًا لإعادة التوليد.
"""

from __future__ import annotations

import os
import shutil
import sys
import uuid
from pathlib import Path

from check_content import parse_front_matter


ROOT = Path(__file__).resolve().parent.parent
DESTINATION = ROOT / "content"
MARKER = ".generated-by-prepare-content"


class PrepareError(RuntimeError):
    pass


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
    except OSError as exc:
        raise PrepareError(f"تعذّرت قراءة {path}") from exc
    if data is None:
        raise PrepareError(f"ملف بلا front matter: {path}")
    return data


def bundle_is_archived(bundle: Path) -> bool:
    indexes = sorted(bundle.glob("index.*.md"))
    if not indexes:
        raise PrepareError(f"حزمة بلا index.<lang>.md: {bundle}")
    states = {bool(front_matter(path).get("archived", False)) for path in indexes}
    if len(states) != 1:
        raise PrepareError(f"حالة archived مختلفة بين ترجمات الحزمة: {bundle.name}")
    return states == {True}


def prepare(source: Path) -> tuple[int, int]:
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
                if bundle_is_archived(bundle):
                    archived += 1
                    continue
                shutil.copytree(bundle, staging / bundle.name)
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
