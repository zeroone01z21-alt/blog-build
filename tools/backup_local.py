#!/usr/bin/env python3
"""أنشئ نسخة محلية شهرية قابلة للتحقق من مصادر ZERO 2 ONE.

لا يحذف هذا الأمر أي نسخة سابقة. يرفض الكتابة فوق مجلد موجود، ويستخدم
``git clone --mirror`` كي يحفظ كل الفروع والوسوم لا working tree فقط.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
from pathlib import Path


REPOSITORIES = {
    "zero2one-web": "https://github.com/01team9639-maker/zero2one-web.git",
    "blog-build": "https://github.com/zeroone01z21-alt/blog-build.git",
    "blog-content": "https://github.com/zeroone01z21-alt/blog-content.git",
}


class BackupError(RuntimeError):
    pass


def git(*args: str, cwd: Path | None = None) -> str:
    try:
        result = subprocess.run(
            ["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "git failed").strip()
        raise BackupError(detail) from exc
    return result.stdout.strip()


def backup(base: Path) -> Path:
    base = base.expanduser().resolve()
    if not base.is_dir():
        raise BackupError(f"مجلد الوجهة غير موجود: {base}")
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = base / f"zero2one-backup-{stamp}"
    if destination.exists():
        raise BackupError(f"مجلد النسخة موجود أصلًا: {destination}")
    destination.mkdir()

    records = []
    for name, url in REPOSITORIES.items():
        mirror = destination / f"{name}.git"
        print(f"  نسخ {name} …")
        git("clone", "--mirror", url, str(mirror))
        git("fsck", "--full", cwd=mirror)
        commit = git("rev-parse", "refs/heads/main", cwd=mirror)
        records.append({"name": name, "source": url, "main": commit})

    manifest = {
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "format": "git-mirror-v1",
        "repositories": records,
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    print(f"  ✅ النسخة مكتملة: {destination}")
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description="نسخة محلية شهرية لمشروع ZERO 2 ONE")
    parser.add_argument("destination", type=Path, help="مجلد موجود على قرص النسخ")
    args = parser.parse_args()
    try:
        backup(args.destination)
    except (BackupError, OSError) as exc:
        print(f"  ❌ فشل النسخ: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
