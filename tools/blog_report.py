#!/usr/bin/env python3
"""
بلاغ حالة النشر — للكاتب والمالك، لا لسجل لا يقرؤه أحد
=======================================================

لماذا
-----
في 23 سبتمبر 2026 فشل النشر خمس مرات، ولم يعرف أحد ثمانية أيام: الرسالة
كانت في سجل GitHub Actions وحده، والمراقب الخارجي (HEALTHCHECKS_URL) لم
يُربط قط. والكاتب يحفظ في اللوحة ويظن أن المقال نُشر.

هذا الملف يحوّل تقرير ``build_blog.py`` إلى:

- ``summary``: ملخص التشغيل في صفحة Actions (عربي للكاتب، إنجليزي للمالك).
- ``export``: التقرير مضغوطًا إلى مخرجات المهمة، لتقرأه مهمة الإبلاغ.
- ``notify``: بلاغ واحد مفتوح في Issues باسم «حالة نشر المدونة» يُذكَر فيه
  الكاتب والمالك؛ يُحدَّث بتعليق عند **كل تغيّر** فقط، ويُغلق حين لا يبقى
  شيء يحتاج انتباهًا. ويعيد تفعيل الجدولة إن عطّلها GitHub لخمول المستودع.
- ``token-check``: كم بقي على انتهاء SITE_REPO_TOKEN، دون طباعته.

الإبلاغ لا يُفشل النشر: تعطّله يظهر تحذيرًا، والنشر الناجح يبقى ناجحًا.

الاستخدام: انظر ``main()``.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
import zlib
from pathlib import Path

RIYADH = dt.timezone(dt.timedelta(hours=3))
API = "https://api.github.com"
SITE_REPO = "01team9639-maker/zero2one-web"
BLOG_URL = "https://zero2one.sa/blog/"
MARKER = "blog-publish-status:v1"
ISSUE_TITLE = "حالة نشر المدونة"
TOKEN_WARN_DAYS = 21
SCHEDULER = "schedule.yml"
DEVICE_OFFSETS_OK = {"", "+03:00", "+0300", "+03"}

STATUS_AR = {
    "published": "✅ منشور",
    "scheduled": "🕒 مجدول",
    "held": "⏸ محجوز — لم يُنشر",
    "held_live_kept": "⏸ تعديلك الأخير محجوز",
    "draft": "📝 مسودة",
    "archived": "🗄 مؤرشف",
    "missing": "⚠️ لم يظهر",
    "blocked": "⛔ لم يتغيّر — عطل عام",
}
STAGE_AR = {
    "prepare": "تجهيز المقال",
    "content": "فحص المحتوى",
    "hugo": "توليد الصفحة",
    "seo": "فحص الصفحة الناتجة",
    "budgets": "حجم الصفحة",
}
STAGE_HINT_AR = {
    "hugo": "غالبًا صورة داخل النص غير موجودة أو مكتوبة يدويًا: احذفها وأعد "
            "إدراجها من زرّ الصورة. إن تكرّر بعد ذلك فلا تعد الحفظ وانتظر المالك.",
    "seo": "راجع عناوين المقال (عنوان فارغ أو قفزة في الدرجات) ثم احفظ.",
    "budgets": "صفحة المقال ثقيلة على الجوال: صغّر الصور الكبيرة أو قلّل عددها ثم احفظ.",
}


# ── أدوات صغيرة ──────────────────────────────────────────────────────────
def riyadh(value: str | None) -> str:
    """'2026-10-05T10:00:00+03:00' ← '2026-10-05 10:00' بتوقيت الرياض."""
    if not value:
        return "؟"
    try:
        moment = dt.datetime.fromisoformat(value)
    except ValueError:
        return value
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=RIYADH)
    return moment.astimezone(RIYADH).strftime("%Y-%m-%d %H:%M")


def title_of(article: dict) -> str:
    titles = article.get("titles") or {}
    for lang in ("ar", "en"):
        if titles.get(lang):
            return titles[lang]
    return article.get("slug", "")


def clean(text: str, limit: int = 300) -> str:
    """نصّ من محتوى الكاتب داخل Markdown: سطر واحد بلا أوامر جداول أو HTML."""
    text = re.sub(r"\s+", " ", str(text)).strip()
    text = text.replace("|", "¦").replace("<", "‹").replace(">", "›")
    text = re.sub(r"([\[\]`])", r"\\\1", text)        # لا روابط ولا شيفرة من نصّ المقال
    text = re.sub(r"@(?=\w)", "@​", text)       # لا إشارات عرضية لحسابات
    return text[:limit] + ("…" if len(text) > limit else "")


def device_offset(article: dict) -> str:
    for note in article.get("notes", []):
        if note.startswith("device-offset:"):
            before = note.split(":", 2)[2].split("→", 1)[0]
            match = re.search(r"(Z|[+-]\d{2}:?\d{2})$", before)
            if match and match.group(1) not in DEVICE_OFFSETS_OK:
                return match.group(1)
    return ""


# ── ما يحتاج انتباهًا ─────────────────────────────────────────────────────
def attention(bundle: dict) -> list[dict]:
    """البنود التي تُبقي البلاغ مفتوحًا. لكل بند مفتاح ثابت يُقارن بين التشغيلات."""
    report = bundle.get("report")
    items: list[dict] = []
    if not report:
        items.append({"key": "no-report", "who": "owner",
                      "ar": "تعذّر البناء قبل أن يكتمل تقرير المقالات. الموقع الحي "
                            "لم يتغيّر على الأرجح؛ افتح سجل التشغيل.",
                      "en": "The build stopped before the article report was written."})
    else:
        fatal = report.get("fatal")
        if fatal:
            items.append({"key": f"fatal:{fatal.get('stage')}", "who": "owner",
                          "ar": f"⛔ لم يُنشر شيء: عطل عام في «{fatal.get('stage')}». "
                                "الموقع الحي بقي كما كان. للكاتب: لا تكرّر الحفظ؛ محتواك محفوظ.",
                          "en": f"Blocked at {fatal.get('stage')}: {clean(fatal.get('message', ''))}"})
        for art in report.get("articles", []):
            slug, status = art.get("slug"), art.get("status")
            if status in ("held", "held_live_kept"):
                problems = art.get("problems") or []
                stages = {p.get("stage") for p in problems}
                key = f"held:{slug}:" + hashlib.sha256(json.dumps(
                    [p.get("message") for p in problems], ensure_ascii=False
                ).encode()).hexdigest()[:10]
                kept = ""
                if status == "held_live_kept" and art.get("fallback"):
                    kept = (" الموقع يعرض الآن نسختك المحفوظة في "
                            f"{riyadh(art['fallback'].get('committed_at'))}.")
                lines = [f"{STAGE_AR.get(p.get('stage'), p.get('stage'))}: {clean(p.get('message'))}"
                         for p in problems[:6]]
                hints = [STAGE_HINT_AR[s] for s in sorted(stages) if s in STAGE_HINT_AR]
                items.append({"key": key, "who": "writer", "slug": slug,
                              "ar": f"«{clean(title_of(art), 90)}» (`{slug}`) {STATUS_AR[status]}."
                                    f"{kept} " + " — ".join(lines) + (" " + " ".join(hints) if hints else ""),
                              "en": f"{slug}: {status}"})
            elif status == "missing":
                items.append({"key": f"missing:{slug}", "who": "owner", "slug": slug,
                              "ar": f"«{clean(title_of(art), 90)}» اجتاز الفحوص ولم يخرج من Hugo. "
                                    "هذا عطل تقني لا يصلحه الكاتب.",
                              "en": f"{slug} passed every gate but Hugo did not render it."})
            elif status == "scheduled":
                when = min((art.get("dates") or {}).values() or [""])
                items.append({"key": f"scheduled:{slug}:{when}", "who": "writer", "slug": slug,
                              "level": "info",
                              "ar": f"«{clean(title_of(art), 90)}» مجدول: يظهر تلقائيًا بعد "
                                    f"{riyadh(when)} بتوقيت الرياض (خلال ساعة تقريبًا من الموعد). "
                                    "إن لم تقصد الجدولة فعدّل «تاريخ النشر» واحفظ.",
                              "en": f"{slug} scheduled for {when}"})
        known = {a.get("slug") for a in report.get("articles", [])}
        for page in report.get("removed_pages", []):
            slug = page.split("/")[-1]
            if slug not in known:
                items.append({"key": f"removed:{page}", "who": "owner",
                              "ar": f"الصفحة /blog/{page}/ خرجت من الموقع ولم يعد مقالها في "
                                    "المحتوى. الحذف ليس مسارًا تحريريًّا (الأرشفة هي البديل) — تحقّق.",
                              "en": f"/blog/{page}/ removed: its bundle is no longer in blog-content."})
    outcomes = bundle.get("outcomes") or {}
    if report and not report.get("fatal") and outcomes.get("job") == "failure":
        items.append({"key": "post-build-failure", "who": "owner",
                      "ar": "اجتاز البناء بوابات المحتوى، ثم فشلت خطوة بعده (الاستبدال أو حارس "
                            "النطاق أو الدفع). لم يصل شيء إلى الموقع في هذا التشغيل؛ الجدولة "
                            "تعيد المحاولة خلال ساعة.",
                      "en": "A step after build_blog failed (replace/scope/push): nothing was published."})
    if outcomes.get("push") == "success" and outcomes.get("live") == "failure":
        items.append({"key": "live-unverified", "who": "owner",
                      "ar": "دُفع النشر لكن الاستضافة لم تُظهره خلال 10 دقائق. سيظهر عند "
                            "اكتمال المزامنة؛ تحقّق من الموقع.",
                      "en": "Pushed, but the live marker did not appear within 600 s."})
    token = bundle.get("token") or {}
    if token.get("status") == "expiring":
        items.append({"key": f"token:{token.get('expires_at')}", "who": "owner",
                      "ar": f"رمز النشر SITE_REPO_TOKEN ينتهي في {token.get('expires_at')} "
                            f"(بعد {token.get('days_left')} يومًا). جدّده قبلها وإلا توقّف النشر كله.",
                      "en": f"SITE_REPO_TOKEN expires {token.get('expires_at')}."})
    elif token.get("status") == "invalid":
        items.append({"key": "token:invalid", "who": "owner",
                      "ar": "رمز النشر SITE_REPO_TOKEN مرفوض (انتهى أو أُلغي). النشر متوقّف حتى يُجدَّد.",
                      "en": "SITE_REPO_TOKEN was rejected (HTTP 401)."})
    for extra in bundle.get("extra", []):
        items.append(extra)
    return items


def fingerprint(items: list[dict]) -> str:
    keys = sorted(item["key"] for item in items)
    return hashlib.sha256("\n".join(keys).encode()).hexdigest()[:16]


# ── العرض ────────────────────────────────────────────────────────────────
def article_rows(report: dict) -> list[str]:
    rows = ["| المقال | الحالة | التفاصيل |", "|---|---|---|"]
    order = {"held": 0, "held_live_kept": 1, "missing": 2, "blocked": 3, "scheduled": 4,
             "published": 5, "draft": 6, "archived": 7}
    for art in sorted(report.get("articles", []),
                      key=lambda a: (order.get(a.get("status"), 9), a.get("slug", ""))):
        status = art.get("status", "")
        detail = ""
        if status in ("held", "held_live_kept", "draft") and art.get("problems"):
            detail = " — ".join(clean(p.get("message"), 160) for p in art["problems"][:3])
            if status == "draft":
                detail = "يحتاج إصلاحًا قبل النشر: " + detail
            if status == "held_live_kept" and art.get("fallback"):
                detail = (f"الموقع يعرض نسختك المحفوظة في {riyadh(art['fallback'].get('committed_at'))}. "
                          + detail)
        elif status == "scheduled":
            when = min((art.get("dates") or {}).values() or [""])
            detail = f"يظهر تلقائيًا بعد {riyadh(when)} بتوقيت الرياض"
        elif status == "published":
            langs = art.get("published") or []
            new = [lang for lang in langs if lang not in (art.get("live_before") or [])]
            detail = "جديد على الموقع" if new else ""
        elif status == "missing":
            detail = "أُبلغ المالك"
        rows.append(f"| {clean(title_of(art), 80)}<br>`{art.get('slug')}` | "
                    f"{STATUS_AR.get(status, status)} | {detail} |")
    return rows


def summary_markdown(bundle: dict) -> str:
    report = bundle.get("report")
    outcomes = bundle.get("outcomes") or {}
    items = attention(bundle)
    out = ["## حالة نشر المدونة | Blog publishing status", ""]
    after_build_failed = bool(report) and not report.get("fatal") and outcomes.get("job") == "failure"
    if not report or report.get("fatal") or after_build_failed:
        out.append("**⛔ لم يُنشر شيء في هذا التشغيل.** الموقع الحي بقي كما كان.")
        out.append("**للكاتب:** لا تكرّر الحفظ؛ محتواك محفوظ، والعطل عام يحتاج المالك.")
        if after_build_failed:
            out += ["", "حالة المقالات في هذا البناء (لم يصل منها شيء إلى الموقع):", ""]
            out.extend(article_rows(report))
    else:
        counts = report.get("counts", {})
        bits = [f"✅ منشور: {counts.get('published', 0)}"]
        for status, label in (("held", "⏸ محجوز"), ("held_live_kept", "⏸ محجوز ونسخته السابقة باقية"),
                              ("scheduled", "🕒 مجدول"), ("missing", "⚠️ لم يظهر")):
            if counts.get(status):
                bits.append(f"{label}: {counts[status]}")
        out.append(" · ".join(bits))
        if outcomes.get("push") == "success" and outcomes.get("live") == "success":
            out.append("")
            out.append(f"تحقّق النظام من ظهور النشر على [المدونة]({BLOG_URL}).")
        elif outcomes.get("push") == "success" and outcomes.get("live") == "failure":
            out.append("")
            out.append("⚠️ النشر دُفع، لكن الاستضافة لم تُظهره خلال 10 دقائق؛ سيظهر عند اكتمال المزامنة.")
        out.append("")
        out.extend(article_rows(report))
    writer = [i for i in items if i.get("who") == "writer" and i.get("level") != "info"]
    if writer:
        out += ["", "### للكاتب — ما المطلوب", ""]
        out += [f"- {i['ar']}" for i in writer]
    offsets = sorted({device_offset(a) for a in (report or {}).get("articles", [])} - {""})
    if offsets:
        out += ["", f"> 📌 جهاز الكاتب يرسل التاريخ بمنطقة زمنية غير الرياض ({', '.join(offsets)}). "
                    "النظام يقرأ الوقت كما كُتب بتوقيت الرياض، فلا أثر على النشر. يُستحسن ضبط "
                    "منطقة الجهاز على الرياض والوقت تلقائيًا."]
    owner = [i for i in items if i.get("who") == "owner"]
    out += ["", "### Owner", ""]
    if report:
        out.append(f"- outcome `{report.get('outcome')}` · rounds {report.get('rounds')} · "
                   f"content `{str(report.get('content_sha', ''))[:12]}`")
        for art in report.get("articles", []):
            for rejection in art.get("fallback_rejections") or []:
                out.append(f"- `{art.get('slug')}`: earlier version `{rejection.get('commit', '')[:7]}` "
                           f"also failed {rejection.get('stage')}")
        if report.get("fatal"):
            out += ["", "```text", clean(report["fatal"].get("message", ""), 600), "```"]
    for key in ("push", "live", "indexnow"):
        if outcomes.get(key):
            out.append(f"- {key}: {outcomes[key]}")
    out += [f"- ⚠️ {i['en']} — {i['ar']}" for i in owner]
    if outcomes.get("run_url"):
        out += ["", f"[Full run log]({outcomes['run_url']})"]
    return "\n".join(out) + "\n"


def issue_body(bundle: dict, items: list[dict], mentions: list[str]) -> str:
    report = bundle.get("report") or {}
    out = [f"<!-- {MARKER} fp={fingerprint(items)} keys={encode_keys(items)} -->",
           "هذا البلاغ يكتبه نظام النشر تلقائيًا ويحدّثه عند كل تغيّر، ويغلقه حين يُحلّ كل شيء.",
           ""]
    if mentions:
        out += [" ".join("@" + m for m in mentions), ""]
    writer = [i for i in items if i.get("who") == "writer"]
    owner = [i for i in items if i.get("who") == "owner"]
    offsets = sorted({device_offset(a) for a in report.get("articles", [])} - {""})
    if writer:
        out += ["### للكاتب", ""] + [f"- {i['ar']}" for i in writer] + [""]
    if offsets:
        out += [f"> 📌 جهازك يرسل التاريخ بمنطقة زمنية غير الرياض ({', '.join(offsets)}). "
                "النظام يقرأ الوقت كما كتبته بتوقيت الرياض، فلا أثر على النشر. يُستحسن ضبط "
                "منطقة الجهاز على الرياض والوقت تلقائيًا.", ""]
    if owner:
        out += ["### للمالك", ""] + [f"- {i['ar']}" for i in owner] + [""]
    if report.get("articles"):
        out += ["### كل المقالات", ""] + article_rows(report) + [""]
    if bundle.get("outcomes", {}).get("run_url"):
        out.append(f"[سجل آخر تشغيل]({bundle['outcomes']['run_url']})")
    return "\n".join(out) + "\n"


def encode_keys(items: list[dict]) -> str:
    raw = json.dumps(sorted(i["key"] for i in items), ensure_ascii=False).encode()
    return base64.urlsafe_b64encode(raw).decode()


def decode_keys(body: str) -> list[str]:
    match = re.search(r"keys=([A-Za-z0-9_=-]+)", body or "")
    if not match:
        return []
    try:
        return json.loads(base64.urlsafe_b64decode(match.group(1)))
    except (ValueError, json.JSONDecodeError):
        return []


def change_comment(old_keys: list[str], items: list[dict], mentions: list[str],
                   run_url: str) -> str:
    new = [i for i in items if i["key"] not in old_keys]
    resolved = [k for k in old_keys if k not in {i["key"] for i in items}]
    out = [" ".join("@" + m for m in mentions)] if mentions else []
    if new:
        out += ["", "**جديد:**"] + [f"- {i['ar']}" for i in new]
    if resolved:
        out += ["", f"**حُلّ منذ آخر تحديث:** {len(resolved)} بند."]
    if not items:
        out += ["", "✅ لا شيء يحتاج انتباهًا: كل ما يجب نشره منشور. أُغلق البلاغ."]
    if run_url:
        out += ["", f"[سجل التشغيل]({run_url})"]
    return "\n".join(out).strip() + "\n"


# ── GitHub API ──────────────────────────────────────────────────────────
def api(method: str, path: str, token: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        API + path, data=data, method=method,
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28",
                 "User-Agent": "zero2one-blog-status"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read()
            return response.status, (json.loads(raw) if raw else None), dict(response.headers)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            payload = json.loads(raw) if raw else None
        except ValueError:
            payload = None
        return exc.code, payload, dict(exc.headers or {})


def ensure_scheduler(repo: str, token: str) -> list[dict]:
    """GitHub يعطّل الجدولة في المستودع العام بعد 60 يومًا بلا نشاط. كل حفظة
    من الكاتب تمرّ من هنا، فتعيدها إن عُطّلت لهذا السبب وحده."""
    status, data, _ = api("GET", f"/repos/{repo}/actions/workflows/{SCHEDULER}", token)
    if status != 200 or not isinstance(data, dict):
        return [{"key": "scheduler:unknown", "who": "owner", "level": "info",
                 "ar": f"تعذّر قراءة حالة الجدولة (HTTP {status}).",
                 "en": f"Could not read {SCHEDULER} state (HTTP {status})."}]
    state = data.get("state")
    if state == "disabled_inactivity":
        code, _, _ = api("PUT", f"/repos/{repo}/actions/workflows/{SCHEDULER}/enable", token)
        if code == 204:
            print(f"  ✅ أُعيد تفعيل {SCHEDULER} بعد تعطيله لخمول المستودع")
            return []
        return [{"key": "scheduler:disabled_inactivity", "who": "owner",
                 "ar": "الجدولة معطّلة لخمول المستودع وتعذّرت إعادتها آليًّا؛ فعّلها من تبويب Actions.",
                 "en": f"{SCHEDULER} disabled for inactivity; re-enable failed (HTTP {code})."}]
    if state != "active":
        return [{"key": f"scheduler:{state}", "who": "owner",
                 "ar": f"الجدولة ليست مفعّلة ({state}): المقالات المجدولة لن تظهر في موعدها.",
                 "en": f"{SCHEDULER} state is {state}."}]
    return []


def notify(bundle: dict, repo: str, token: str, mentions: list[str]) -> int:
    bundle.setdefault("extra", []).extend(ensure_scheduler(repo, token))
    items = attention(bundle)
    run_url = (bundle.get("outcomes") or {}).get("run_url", "")
    status, issues, _ = api("GET", f"/repos/{repo}/issues?state=open&per_page=100", token)
    if status in (404, 410):
        print("::warning::Issues معطّلة في هذا المستودع؛ البلاغ لم يُرسَل. فعّلها من "
              "Settings ← General ← Features ليصل للكاتب والمالك.")
        return 0
    if status != 200 or not isinstance(issues, list):
        print(f"::warning::تعذّرت قراءة البلاغات (HTTP {status}).")
        return 1
    current = next((i for i in issues if "pull_request" not in i
                    and MARKER in (i.get("body") or "")), None)
    if current is None:
        if not items:
            print("  لا شيء يحتاج انتباهًا، ولا بلاغ مفتوح.")
            return 0
        code, created, _ = api("POST", f"/repos/{repo}/issues", token,
                               {"title": ISSUE_TITLE, "body": issue_body(bundle, items, mentions)})
        if code != 201:
            print(f"::warning::تعذّر فتح البلاغ (HTTP {code}).")
            return 1
        print(f"  📣 فُتح البلاغ #{created.get('number')}")
        return 0
    number = current["number"]
    old_keys = decode_keys(current.get("body", ""))
    if fingerprint(items) in (current.get("body") or "") and items:
        print(f"  البلاغ #{number} محدَّث أصلًا — لا تعليق جديد.")
        return 0
    if items:
        api("PATCH", f"/repos/{repo}/issues/{number}", token,
            {"body": issue_body(bundle, items, mentions)})
    code, _, _ = api("POST", f"/repos/{repo}/issues/{number}/comments", token,
                     {"body": change_comment(old_keys, items, mentions, run_url)})
    if not items:
        api("PATCH", f"/repos/{repo}/issues/{number}", token,
            {"state": "closed", "state_reason": "completed"})
        print(f"  ✅ أُغلق البلاغ #{number}")
    else:
        print(f"  📣 حُدّث البلاغ #{number}")
    return 0 if code == 201 else 1


# ── انتهاء الرمز ─────────────────────────────────────────────────────────
def parse_expiry(header: str) -> dt.datetime | None:
    match = re.match(r"^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})\s*(UTC|[+-]\d{4})?", header.strip())
    if not match:
        return None
    zone = match.group(3) or "UTC"
    offset = dt.timedelta(0) if zone == "UTC" else dt.timedelta(
        hours=int(zone[1:3]), minutes=int(zone[3:5])) * (1 if zone[0] == "+" else -1)
    return dt.datetime.fromisoformat(f"{match.group(1)}T{match.group(2)}").replace(
        tzinfo=dt.timezone(offset))


def token_check(token: str, now: dt.datetime | None = None) -> dict:
    if not token:
        return {"status": "unknown", "reason": "no-token"}
    status, _, headers = api("GET", f"/repos/{SITE_REPO}", token)
    if status == 401:
        return {"status": "invalid"}
    lowered = {k.lower(): v for k, v in headers.items()}
    raw = lowered.get("github-authentication-token-expiration", "")
    if not raw:
        return {"status": "ok", "expires_at": None}
    expires = parse_expiry(raw)
    if expires is None:
        return {"status": "unknown", "reason": "unparsed-header"}
    now = now or dt.datetime.now(dt.timezone.utc)
    days = (expires - now).days
    return {"status": "expiring" if days <= TOKEN_WARN_DAYS else "ok",
            "expires_at": expires.astimezone(RIYADH).strftime("%Y-%m-%d"),
            "days_left": days}


# ── سجل الحالة للوحة الكاتب ────────────────────────────────────────────────
#
# لوحة الكاتب (preview/admin/status-panel.js) تعرض «بلاغات النشر» من سجل
# آخر تشغيل، عبر واجهة GitHub العامة بلا دخول ولا رمز ولا Issues: تعليق
# notice واحد بعنوان ثابت يحمل JSON مضغوطًا بـbase64. الحقول قصيرة عمدًا،
# والحجم محدود كي لا يقصّه GitHub؛ الزائد يُعدّ في ``more``.
STATUS_TITLE = "blog-status-v1"
STATUS_LIMIT = 3500
PANEL_STATUSES = ("held", "held_live_kept", "missing", "scheduled", "draft")


def status_payload(bundle: dict) -> str:
    report = bundle.get("report") or {}
    outcomes = bundle.get("outcomes") or {}
    blocked = (not report) or bool(report.get("fatal")) or outcomes.get("job") == "failure"
    data: dict = {
        "v": 1,
        "t": report.get("generated_at", ""),
        "o": "blocked" if blocked else "ready",
        "c": str(report.get("content_sha", ""))[:12],
        "n": report.get("counts", {}),
        "a": [],
    }
    order = {status: rank for rank, status in enumerate(PANEL_STATUSES)}
    articles = sorted(
        (a for a in report.get("articles", []) if a.get("status") in order
         and not (a.get("status") == "draft" and not a.get("problems"))),
        key=lambda a: (order[a["status"]], a.get("slug", "")))
    for art in articles:
        entry = {"s": art.get("slug", ""), "n": title_of(art)[:90], "st": art["status"],
                 "l": art.get("langs", [])[:2]}
        problems = [[p.get("stage", ""), str(p.get("message", ""))[:220]]
                    for p in (art.get("problems") or [])[:3]]
        if problems:
            entry["p"] = problems
        if art["status"] == "held_live_kept" and art.get("fallback"):
            entry["k"] = art["fallback"].get("committed_at", "")
        if art["status"] == "scheduled":
            entry["w"] = min((art.get("dates") or {}).values() or [""])
        data["a"].append(entry)

    def encode(value: dict) -> str:
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
        return base64.b64encode(zlib.compress(raw, 9)).decode()

    text = encode(data)
    while len(text) > STATUS_LIMIT and data["a"]:
        data["a"].pop()
        data["more"] = data.get("more", 0) + 1
        text = encode(data)
    return text


# ── الحزمة بين المهمتين ───────────────────────────────────────────────────
def load_json(path: str | None) -> dict | None:
    if not path:
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def outcomes_from_env() -> dict:
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    return {
        "job": os.environ.get("JOB_STATUS", ""),
        "push": os.environ.get("PUSH_OUTCOME", ""),
        "live": os.environ.get("LIVE_OUTCOME", ""),
        "indexnow": os.environ.get("INDEXNOW_OUTCOME", ""),
        "pushed": os.environ.get("PUSHED_SHA", ""),
        "run_url": f"{server}/{repo}/actions/runs/{run_id}" if repo and run_id else "",
    }


def make_bundle(report_path: str | None, token_path: str | None) -> dict:
    return {"report": load_json(report_path), "token": load_json(token_path),
            "outcomes": outcomes_from_env()}


def pack(bundle: dict) -> str:
    return base64.b64encode(zlib.compress(
        json.dumps(bundle, ensure_ascii=False).encode(), 9)).decode()


def unpack(text: str) -> dict | None:
    try:
        return json.loads(zlib.decompress(base64.b64decode(text)))
    except (ValueError, zlib.error):
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="بلاغ حالة نشر المدونة")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("summary", "export"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--report")
        cmd.add_argument("--token")
    cmd = sub.add_parser("token-check")
    cmd.add_argument("--output", required=True)
    cmd = sub.add_parser("notify")
    cmd.add_argument("--dry-run", action="store_true",
                     help="اطبع البلاغ بدل إرساله (للاختبار)")
    args = parser.parse_args(argv)

    if args.command == "token-check":
        result = token_check(os.environ.get("TOKEN", ""))
        Path(args.output).write_text(json.dumps(result), encoding="utf-8")
        print(f"  SITE_REPO_TOKEN: {result.get('status')}"
              + (f" · ينتهي {result['expires_at']} (بعد {result.get('days_left')} يومًا)"
                 if result.get("expires_at") else ""))
        return 0

    if args.command == "summary":
        text = summary_markdown(make_bundle(args.report, args.token))
        target = os.environ.get("GITHUB_STEP_SUMMARY")
        if target:
            with open(target, "a", encoding="utf-8") as handle:
                handle.write(text)
        else:
            sys.stdout.write(text)
        for item in attention(make_bundle(args.report, args.token)):
            if item.get("level") != "info":
                print(f"::warning title=حالة النشر::{clean(item['ar'], 400)}")
        print(f"::notice title={STATUS_TITLE}::{status_payload(make_bundle(args.report, args.token))}")
        return 0

    if args.command == "export":
        print(f"report={pack(make_bundle(args.report, args.token))}")
        return 0

    bundle = unpack(os.environ.get("REPORT_BUNDLE", "")) or {"report": None, "outcomes": {}}
    if os.environ.get("BUILD_RESULT") == "cancelled":
        print("  التشغيل أُلغي — لا بلاغ.")
        return 0
    bundle.setdefault("outcomes", {}).setdefault("run_url", outcomes_from_env()["run_url"])
    mentions = [m for m in re.split(r"[\s,]+", os.environ.get("NOTIFY_MENTIONS", "")) if m]
    if args.dry_run:
        items = attention(bundle)
        print(issue_body(bundle, items, mentions))
        print(f"fingerprint={fingerprint(items)} items={len(items)}")
        return 0
    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not token or not repo:
        print("::warning::GITHUB_TOKEN أو GITHUB_REPOSITORY غير متاح؛ لا بلاغ.")
        return 1
    return notify(bundle, repo, token, mentions)


if __name__ == "__main__":
    sys.exit(main())
