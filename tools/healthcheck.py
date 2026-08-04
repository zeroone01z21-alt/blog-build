#!/usr/bin/env python3
"""أرسل إشارة اختيارية إلى Healthchecks.io بلا طباعة رابطها السري.

يُقرأ رابط ping من ``HEALTHCHECKS_URL`` فقط. غياب المتغير يعني أن المالك لم
يربط المراقب بعد، وهو وضع مسموح لا يفشل النشر. الأحداث المدعومة تطابق واجهة
Healthchecks.io: ``start`` و``success`` و``fail``.
"""

from __future__ import annotations

import os
import re
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit, urlunsplit


KEY_RE = re.compile(r"^[A-Za-z0-9-]{8,128}$")
EVENTS = {"start", "success", "fail"}
USER_AGENT = "ZERO2ONE-Healthcheck/1.0"


class HealthcheckError(RuntimeError):
    pass


def event_url(base_url: str, event: str) -> str:
    if event not in EVENTS:
        raise HealthcheckError(f"حدث غير معروف: {event}")
    parsed = urlsplit(base_url.strip())
    parts = [part for part in parsed.path.split("/") if part]
    if (
        parsed.scheme != "https"
        or parsed.hostname != "hc-ping.com"
        or parsed.port not in (None, 443)
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or len(parts) != 1
        or not KEY_RE.fullmatch(parts[0])
    ):
        raise HealthcheckError(
            "HEALTHCHECKS_URL يجب أن يكون https://hc-ping.com/<key> بلا إضافات"
        )
    suffix = "" if event == "success" else f"/{event}"
    return urlunsplit(("https", "hc-ping.com", f"/{parts[0]}{suffix}", "", ""))


def ping(url: str) -> None:
    last_error = "network"
    for attempt in range(2):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                # لا نحتاج جسم الرد، لكن نقرأ حدًا صغيرًا كي يُغلق الاتصال.
                response.read(4096)
                if response.status == 200:
                    return
                last_error = f"HTTP {response.status}"
        except urllib.error.HTTPError as exc:
            last_error = f"HTTP {exc.code}"
        except (OSError, urllib.error.URLError):
            last_error = "network"
        if attempt == 0:
            time.sleep(2)
    raise HealthcheckError(f"تعذّر إرسال الإشارة ({last_error})")


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in EVENTS:
        print("  الاستخدام: healthcheck.py <start|success|fail>")
        return 2
    base_url = os.environ.get("HEALTHCHECKS_URL", "").strip()
    if not base_url:
        print("  Healthchecks غير مربوط — الإشارة اختيارية")
        return 0
    try:
        ping(event_url(base_url, sys.argv[1]))
    except (HealthcheckError, ValueError) as exc:
        # ValueError يغطي منفذ URL غير صالح من دون كشف الرابط نفسه.
        print(f"  ❌ {exc}")
        return 1
    print(f"  ✅ أُرسلت إشارة Healthchecks: {sys.argv[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
