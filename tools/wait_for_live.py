#!/usr/bin/env python3
"""انتظر حتى يطابق ملف حي النسخة المحلية بعد مزامنة Hostinger."""

from __future__ import annotations

import argparse
import hashlib
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse


MAX_BYTES = 2 * 1024 * 1024
ALLOWED_PATHS = {
    "/blog/indexnow-deploy.txt",
    "/blog/rollback-deploy.txt",
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(url: str) -> bytes | None:
    request = urllib.request.Request(
        url,
        headers={"Cache-Control": "no-cache", "User-Agent": "ZERO2ONE-Deploy-Verify/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body = response.read(MAX_BYTES + 1)
            # لا نقبل redirect صامتًا إلى صفحة أو مضيف آخر؛ العلامة يجب أن
            # تكون في المسار الدقيق الذي ستتحقق منه بقية الأدوات.
            if response.geturl() != url or response.status != 200 or len(body) > MAX_BYTES:
                return None
            return body
    except (OSError, urllib.error.URLError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="تحقق خارجي من وصول ملف منشور")
    parser.add_argument("expected", type=Path)
    parser.add_argument("url")
    parser.add_argument("--seconds", type=int, default=240)
    args = parser.parse_args()

    try:
        target = urlparse(args.url)
        valid_port = target.port in (None, 443)
    except ValueError:
        target = urlparse("")
        valid_port = False
    if (
        target.scheme != "https"
        or target.hostname != "zero2one.sa"
        or not valid_port
        or target.username
        or target.password
        or target.path not in ALLOWED_PATHS
        or target.params
        or target.query
        or target.fragment
    ):
        print("  ❌ رابط التحقق ليس أحد مساري النشر المعتمدين")
        return 2
    if not args.expected.is_file() or not 0 <= args.seconds <= 3600:
        print("  ❌ ملف التحقق مفقود أو المهلة غير صالحة")
        return 2

    expected = args.expected.read_bytes()
    if len(expected) > MAX_BYTES:
        print("  ❌ ملف التحقق أكبر من الحد")
        return 2
    expected_hash = digest(expected)
    deadline = time.monotonic() + args.seconds
    while True:
        body = fetch(args.url)
        if body is not None and digest(body) == expected_hash:
            print(f"  ✅ ظهر النشر الحي المطابق ({expected_hash[:12]})")
            return 0
        if time.monotonic() >= deadline:
            print("  ❌ انتهت مهلة مزامنة Hostinger دون تطابق")
            return 1
        remaining = deadline - time.monotonic()
        time.sleep(min(10, max(0.1, remaining)))


if __name__ == "__main__":
    raise SystemExit(main())
