#!/usr/bin/env python3
"""
الجدولة — ما حان موعده يُنشر دون أن يحفظ أحد شيئًا
==================================================

لماذا
-----
Hugo يتخطّى المقال المؤرَّخ في المستقبل، ولا يعيد أحد البناء بعد حلول
موعده. مقال 16 سبتمبر 2026 بقي خارج الموقع لهذا السبب وحده. والبناء لا
يبدأ إلا بإشارة من مستودع المحتوى عند الحفظ؛ إن ضاعت الإشارة (رمز منتهٍ،
عطل في GitHub) لم يُنشر شيء ولم يعلم أحد.

ماذا يفعل (يشغّله schedule.yml كل ساعة)
---------------------------------------
1. بناء قيد التشغيل أو في الطابور ← لا شيء.
2. آخر محتوى في main لم يُبنَ قط ← تشغيل البناء (إشارة الحفظ لم تصل).
3. آخر بناء لهذا المحتوى فشل ← إعادة محاولة بعد ساعة، بحدّ ثلاث محاولات
   للمحتوى نفسه بالقوالب نفسها. ما بعدها يحتاج المالك، والبلاغ مفتوح أصلًا.
4. آخر بناء نجح ← تشغيل إن حلّ موعد مقال **بعد** بدء ذلك البناء.

لا حالة محفوظة في أي مكان: القرار من تاريخ تشغيلات build.yml نفسها.
وهو لا يبني ولا ينشر بنفسه؛ يطلب build.yml بالبوابات كلها كأي حفظة.

الاستخدام:
    python3 tools/schedule_check.py --content .content-src [--dispatch]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

import check_content  # noqa: E402
from prepare_content import riyadh_wall_clock  # noqa: E402

API = "https://api.github.com"
WORKFLOW = "build.yml"
SCHEDULER = "schedule.yml"
SHA40 = re.compile(r"\b[0-9a-f]{40}\b")
RETRY_AFTER = dt.timedelta(hours=1)
MAX_FAILURES = 3


def api(method: str, path: str, token: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        API + path, data=data, method=method,
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28",
                 "User-Agent": "zero2one-blog-schedule"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read()
            return response.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        return exc.code, None


def when(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def due_dates(content: Path) -> list[tuple[str, dt.datetime]]:
    """(slug, موعد) لكل ترجمة منشورة غير مؤرشفة، بقاعدة توقيت المدونة نفسها."""
    found = []
    root = content / "content" / "blog"
    bundles = sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []
    for bundle in bundles:
        fronts = []
        for index in sorted(bundle.glob("index.*.md")):
            try:
                fm, _ = check_content.parse_front_matter(index.read_text(encoding="utf-8"))
            except (OSError, UnicodeError):
                fm = None
            fronts.append(fm or {})
        if not fronts or any(f.get("archived") for f in fronts):
            continue
        for fm in fronts:
            if fm.get("draft"):
                continue
            parsed = riyadh_wall_clock(str(fm.get("date") or ""))
            moment = when(parsed[0]) if parsed else None
            if moment is not None:
                found.append((bundle.name, moment))
    return found


def decide(runs: list[dict], content_sha: str, content_time: dt.datetime,
           template_sha: str, dates: list[tuple[str, dt.datetime]],
           now: dt.datetime) -> tuple[str, str]:
    """('dispatch', السبب) أو ('wait', السبب). دالة نقية تُختبر بلا شبكة."""
    if any(r.get("status") != "completed" for r in runs):
        return "wait", "بناء قيد التشغيل أو في الطابور"

    def covers(run: dict) -> bool:
        title = run.get("display_title") or ""
        if content_sha in title:
            return True
        created = when(run.get("created_at"))
        return not SHA40.search(title) and created is not None and created >= content_time

    mine = [r for r in runs if covers(r)]          # الأحدث أولًا كما يعيدها GitHub
    if not mine:
        return "dispatch", f"لم يُبنَ آخر محتوى ({content_sha[:7]}) — إشارة الحفظ لم تصل"
    last = mine[0]
    if last.get("conclusion") != "success":
        failures = 0
        for run in mine:
            if run.get("conclusion") == "success":
                break
            if (run.get("conclusion") not in ("success", "cancelled", "skipped")
                    and run.get("head_sha") == template_sha):
                failures += 1
        if failures >= MAX_FAILURES:
            return "wait", f"فشل {failures} مرات للمحتوى والقوالب نفسها — البلاغ مفتوح للمالك"
        finished = when(last.get("updated_at")) or now
        if now - finished < RETRY_AFTER:
            return "wait", "آخر محاولة فشلت قبل أقل من ساعة"
        return "dispatch", "إعادة محاولة بعد فشل"
    started = when(last.get("run_started_at")) or when(last.get("created_at")) or now
    ready = sorted({slug for slug, moment in dates if started < moment <= now})
    if ready:
        return "dispatch", "حان موعد: " + "، ".join(ready)
    return "wait", "لا جديد"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="نشر ما حان موعده")
    parser.add_argument("--content", type=Path, required=True)
    parser.add_argument("--dispatch", action="store_true",
                        help="نفّذ القرار (بدونه يُطبع فقط)")
    args = parser.parse_args(argv)

    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    template_sha = os.environ.get("GITHUB_SHA", "")
    if not token or not repo:
        print("::error::GITHUB_TOKEN وGITHUB_REPOSITORY مطلوبان.")
        return 1
    git = ["git", "-C", str(args.content)]
    content_sha = subprocess.run([*git, "rev-parse", "HEAD"], check=True,
                                 capture_output=True, text=True).stdout.strip()
    content_time = when(subprocess.run([*git, "log", "-1", "--format=%cI", "HEAD"],
                                       check=True, capture_output=True,
                                       text=True).stdout.strip())
    now = dt.datetime.now(dt.timezone.utc)

    status, data = api("GET", f"/repos/{repo}/actions/workflows/{WORKFLOW}/runs?per_page=100",
                       token)
    if status != 200 or not isinstance(data, dict):
        print(f"::error::تعذّرت قراءة تشغيلات {WORKFLOW} (HTTP {status}).")
        return 1
    action, reason = decide(data.get("workflow_runs", []), content_sha,
                            content_time or now, template_sha,
                            due_dates(args.content), now)
    print(f"  {action}: {reason}")

    # GitHub يعطّل الجدولة في المستودع العام بعد 60 يومًا بلا نشاط. إعادة
    # التفعيل اليومية محاولة احتياطية؛ الضمان الفعلي في مهمة الإبلاغ التي
    # تعيدها مع كل حفظة من الكاتب.
    if args.dispatch and now.hour == 3:
        code, _ = api("PUT", f"/repos/{repo}/actions/workflows/{SCHEDULER}/enable", token)
        print(f"  keepalive: HTTP {code}")

    if action != "dispatch" or not args.dispatch:
        return 0
    code, _ = api("POST", f"/repos/{repo}/actions/workflows/{WORKFLOW}/dispatches", token,
                  {"ref": "main",
                   "inputs": {"reason": f"تشغيل دوري — {reason}"[:200],
                              "content_sha": content_sha}})
    if code != 204:
        print(f"::error::تعذّر طلب البناء (HTTP {code}).")
        return 1
    print("  ✅ طُلب البناء")
    return 0


if __name__ == "__main__":
    sys.exit(main())
