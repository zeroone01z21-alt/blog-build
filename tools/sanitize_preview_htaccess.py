#!/usr/bin/env python3
"""أزل Header من حماية المعاينة مع إثبات بقاء Basic Auth.

يستعمله سير المعاينة على نسخة مؤقتة سحبها عبر FTP. لا يطبع المحتوى لأن
``AuthUserFile`` قد يكشف مسار حساب الاستضافة في سجل Actions.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


MAX_BYTES = 64 * 1024


def sanitize(text: str) -> tuple[str, int]:
    kept: list[str] = []
    removed = 0
    for line in text.splitlines(keepends=True):
        if re.match(r"^\s*Header(?:\s|$)", line, flags=re.IGNORECASE):
            removed += 1
            continue
        kept.append(line)
    result = "".join(kept)

    active = [
        line.split("#", 1)[0].strip()
        for line in result.splitlines()
        if line.split("#", 1)[0].strip()
    ]
    requirements = {
        "AuthType Basic": lambda line: re.fullmatch(
            r"AuthType\s+Basic", line, flags=re.IGNORECASE
        ),
        "AuthUserFile": lambda line: re.match(
            r"AuthUserFile\s+\S+", line, flags=re.IGNORECASE
        ),
        "Require valid-user": lambda line: re.fullmatch(
            r"Require\s+valid-user", line, flags=re.IGNORECASE
        ),
    }
    missing = [name for name, matches in requirements.items() if not any(matches(line) for line in active)]
    if missing:
        raise ValueError("حماية Basic Auth ناقصة: " + "، ".join(missing))
    if any(re.match(r"^Header(?:\s|$)", line, flags=re.IGNORECASE) for line in active):
        raise ValueError("بقيت تعليمة Header فعالة")
    return result, removed


def main() -> int:
    if len(sys.argv) != 2:
        print("  الاستخدام: sanitize_preview_htaccess.py <temporary-htaccess>")
        return 2
    path = Path(sys.argv[1])
    try:
        if not path.is_file() or path.is_symlink():
            raise ValueError("ملف حماية المعاينة غير موجود أو غير آمن")
        raw = path.read_bytes()
        if not raw or len(raw) > MAX_BYTES:
            raise ValueError("حجم ملف حماية المعاينة غير صالح")
        text = raw.decode("utf-8")
        cleaned, removed = sanitize(text)
        path.write_text(cleaned, encoding="utf-8", newline="")
    except (OSError, UnicodeError, ValueError) as error:
        print(f"  ❌ لم يُعدّل ملف الحماية: {error}")
        return 1
    print(f"  ✅ Basic Auth محفوظ · أزيلت {removed} تعليمة Header")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
