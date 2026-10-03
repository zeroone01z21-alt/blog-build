#!/usr/bin/env python3
"""
بنّاء المدونة — مقال معطوب يُحجز وحده، والبقية تُنشر
=====================================================

يشغّل بوابات البناء بالترتيب نفسه الذي كانت خطوات build.yml تشغّلها:
تجهيز المحتوى ← عقد المحتوى ← Hugo ← الخرائط ← الفهرسة ← SEO ← الميزانيات.
الفرق في **ما يحدث عند الفشل**.

لماذا
-----
كان أي خطأ في أي مقال يوقف نشر المدونة كلها. من 21 بناءً بين 12 و30
سبتمبر 2026 فشل 13: ستة في Hugo، وواحد في SEO، وستة في عقد المحتوى —
وكلها بسبب مقال واحد في كل مرة. واحتاج كل منها تدخّلًا تقنيًا.
وفي 23 سبتمبر لم يلاحظ أحد، فبقي مقالان خارج الموقع ثمانية أيام.

القاعدة الآن
------------
- مشكلة يمكن نسبتها إلى مقال بعينه ← يُحجز ذلك المقال وحده، وتُعاد البوابات
  كلها على ما بقي. لا يُنشر شيء لم يجتز كل البوابات؛ البوابة لم تُخفَّف.
- المقال المحجوز إن كان منشورًا أصلًا لا يختفي: تُستعمل آخر نسخة محفوظة منه
  في تاريخ blog-content تجتاز البوابات. فإن لم توجد، يتوقف النشر كله كما
  كان (وهذه حالة نادرة تحتاج المالك).
- مشكلة لا تُنسب إلى مقال (قالب، خط، إعداد، صفحة قسم) ← يتوقف النشر كله
  كما كان. ``Fatal`` هنا يعني: لا نشر.
- كل مقال يخرج بحالة صريحة في التقرير: منشور، مجدول بموعده، محجوز وسببه،
  مسودة، مؤرشف، أو مفقود. لا تخطٍّ صامت بعد اليوم.

الاستخدام (سير البناء):
    python3 tools/build_blog.py --source .content-src --site site \\
        --hugo hugo --report "$RUNNER_TEMP/blog-report.json"
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

import check_content  # noqa: E402
import prepare_content  # noqa: E402

ROOT = TOOLS.parent
CONTENT = prepare_content.DESTINATION
SOURCE_BUNDLES = "content/blog"          # مسار الحزم داخل مستودع المحتوى
RIYADH = dt.timezone(dt.timedelta(hours=3))
MAX_ROUNDS = 10
NOT_ARTICLES = {"categories", "page", "ar"}
HUGO_SUMMARY = re.compile(r"logged \d+ error")
HUGO_ERROR = re.compile(r"^(?:\S+\s+)?(?:ERROR\b|Error:)")
DEVICE_OFFSETS_OK = {"", "+03:00", "+0300", "+03"}


class Fatal(Exception):
    """عطل يخص المدونة كلها: لا نشر. ``stage`` اسم البوابة."""

    def __init__(self, stage: str, message: str, output: str = "") -> None:
        super().__init__(message)
        self.stage = stage
        self.message = message
        self.output = output


def now_riyadh() -> dt.datetime:
    return dt.datetime.now(RIYADH).replace(microsecond=0)


def parse_date(value: object) -> dt.datetime | None:
    try:
        parsed = dt.datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=RIYADH)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    ).stdout


def run(cmd: list[str]) -> tuple[int, str]:
    """يشغّل بوابة ويعرض مخرجها في السجل كما هو."""
    proc = subprocess.run(cmd, cwd=ROOT, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True)
    output = proc.stdout or ""
    if output:
        sys.stdout.write(output if output.endswith("\n") else output + "\n")
        sys.stdout.flush()
    return proc.returncode, output


def short_paths(text: str) -> str:
    """'"/home/runner/…/content/x/index.ar.md' ← 'content/x/index.ar.md' للقارئ."""
    return re.sub(r"(^|[\"'\s(])/[^\"'\s]*?/((?:content|layouts)/)", r"\1\2", text)


def tail(text: str, lines: int = 40) -> str:
    return "\n".join(text.strip().splitlines()[-lines:])


def language_prefixes(schema: dict) -> dict[str, str]:
    """{'en': '', 'ar': 'ar/'} من مسارات اللغات في العقد."""
    prefixes = {}
    for lang, path in schema["languages"]["paths"].items():
        parts = path.strip("/").split("/", 1)
        prefixes[lang] = parts[1] + "/" if len(parts) > 1 else ""
    return prefixes


def read_front(path: Path) -> dict:
    try:
        data, _ = check_content.parse_front_matter(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        return {}
    return data or {}


def article_dirs(root: Path) -> set[str]:
    """مسارات صفحات المقالات في مخرج بناء: '<slug>' و'ar/<slug>'."""
    found = set()
    for base, prefix in ((root, ""), (root / "ar", "ar/")):
        if not base.is_dir():
            continue
        for item in base.iterdir():
            if item.name in NOT_ARTICLES or not (item / "index.html").is_file():
                continue
            found.add(prefix + item.name)
    return found


class Article:
    def __init__(self, slug: str) -> None:
        self.slug = slug
        self.langs: list[str] = []
        self.titles: dict[str, str] = {}
        self.dates: dict[str, str] = {}
        self.drafts: dict[str, bool] = {}
        self.archived = False
        self.live_before: list[str] = []
        self.problems: list[dict[str, str]] = []
        self.notes: list[str] = []
        self.fallback: dict[str, str] | None = None
        self.fallback_dir: Path | None = None
        self.rejected: set[str] = set()
        self.rejections: list[dict[str, str]] = []
        self.status = ""
        self.published: list[str] = []

    @property
    def draft(self) -> bool:
        """مسودة = كل ترجماتها مسودة. ترجمة واحدة منشورة تكفي لتعدّه للنشر."""
        return bool(self.drafts) and all(self.drafts.values())

    def problem(self, stage: str, message: str, file: str = "") -> None:
        entry = {"stage": stage, "file": file, "message": message}
        if entry not in self.problems:
            self.problems.append(entry)

    def as_dict(self) -> dict:
        return {
            "slug": self.slug, "status": self.status, "langs": self.langs,
            "titles": self.titles, "dates": self.dates, "draft": self.draft,
            "draft_langs": sorted(lang for lang, flag in self.drafts.items() if flag),
            "archived": self.archived, "live_before": self.live_before,
            "published": self.published, "problems": self.problems,
            "fallback": self.fallback, "fallback_rejections": self.rejections,
            "notes": self.notes,
        }


class Builder:
    def __init__(self, source: Path, site: Path | None, public: Path, hugo: str,
                 now: dt.datetime | None = None) -> None:
        self.source = source.resolve()
        self.site_blog = (site / "blog").resolve() if site else None
        self.public = public.resolve()
        self.hugo = hugo
        # --now للاختبار وحده: Hugo نفسه يقرّر «المستقبل» بساعة الجهاز.
        self.fixed_now = now is not None
        self.now = now or now_riyadh()
        self.stage_failed = ""
        self.schema = check_content.load_schema()
        self.prefixes = language_prefixes(self.schema)
        self.articles: dict[str, Article] = {}
        self.rounds = 0
        self.fatal: Fatal | None = None
        self.removed_pages: list[str] = []
        self.scratch = Path(tempfile.mkdtemp(prefix="blog-fallback-"))

    # ── الجرد ─────────────────────────────────────────────────────────
    def page(self, slug: str, lang: str) -> str:
        return f"{self.prefixes.get(lang, lang + '/')}{slug}/index.html"

    def load_inventory(self, prepare_problems: dict, details: dict) -> None:
        source_bundles = self.source / SOURCE_BUNDLES
        names = sorted(
            p.name for p in source_bundles.iterdir()
            if p.is_dir() and not p.name.startswith(".")
        ) if source_bundles.is_dir() else []
        for name in names:
            art = Article(name)
            self.articles[name] = art
            staged = CONTENT / name
            origin = staged if staged.is_dir() else source_bundles / name
            for index in sorted(origin.glob("index.*.md")):
                lang = index.name.split(".")[1]
                front = read_front(index)
                art.langs.append(lang)
                art.titles[lang] = str(front.get("title") or "")
                if front.get("date"):
                    art.dates[lang] = str(front.get("date"))
                art.drafts[lang] = bool(front.get("draft", False))
            # الأرشفة قرار التجهيز وحده: حزمة اختلفت أرشفة ترجمتيها مشكلةٌ
            # تُحجز (وتبقى نسختها المنشورة)، لا أرشفة تُخفيها.
            info = details.get(name, {})
            art.archived = bool(info.get("archived")) and name not in prepare_problems
            for change in info.get("dates", []):
                if change.get("offset", "") not in DEVICE_OFFSETS_OK:
                    art.notes.append(
                        f"device-offset:{change['field']}:{change['before']}→{change['after']}")
            for message in prepare_problems.get(name, []):
                art.problem("prepare", message)
            if self.site_blog is not None:
                art.live_before = [
                    lang for lang in sorted(set(art.langs) | set(self.prefixes))
                    if (self.site_blog / self.page(name, lang)).is_file()
                ]

    # ── الحجز ─────────────────────────────────────────────────────────
    def check_staged(self) -> None:
        for name, art in self.articles.items():
            staged = CONTENT / name
            if not staged.is_dir():
                continue
            for file, message in check_content.check_bundle(str(staged), self.schema):
                art.problem("content", message, Path(file).name)

    def held(self) -> list[Article]:
        return [a for a in self.articles.values() if a.problems and not a.archived]

    def apply_holds(self) -> None:
        for art in self.held():
            destination = CONTENT / art.slug
            if destination.exists():
                shutil.rmtree(destination)
            # المسودة لن تُنشر أصلًا، والمقال الذي لم يُنشر قط يكفي حجزه.
            if art.draft or not art.live_before:
                continue
            if art.fallback is None:
                self.find_fallback(art)
            if art.fallback is None:
                raise Fatal(
                    "hold",
                    f"المقال المنشور «{art.slug}» فيه مشكلة، ولا توجد نسخة سابقة منه "
                    "تجتاز البوابات الحالية. أُوقف النشر كله كي لا يختفي من الموقع.",
                )
            shutil.copytree(art.fallback_dir, destination)

    def history(self, slug: str) -> list[tuple[str, str]]:
        out = git(self.source, "log", "--format=%H%x09%cI", "HEAD", "--",
                  f"{SOURCE_BUNDLES}/{slug}")
        rows = []
        for line in out.splitlines():
            if "\t" in line:
                commit, when = line.split("\t", 1)
                rows.append((commit, when))
        return rows

    def export(self, commit: str, slug: str, target: Path) -> bool:
        prefix = f"{SOURCE_BUNDLES}/{slug}/"
        proc = subprocess.run(
            ["git", "-C", str(self.source), "archive", "--format=tar", commit,
             "--", prefix.rstrip("/")],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        if proc.returncode != 0:
            return False
        with tarfile.open(fileobj=io.BytesIO(proc.stdout)) as archive:
            for member in archive.getmembers():
                if not member.name.startswith(prefix):
                    continue
                relative = member.name[len(prefix):]
                parts = Path(relative).parts
                if not relative or relative.startswith("/") or ".." in parts:
                    continue
                path = target.joinpath(*parts)
                if member.isdir():
                    path.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    handle = archive.extractfile(member)
                    path.write_bytes(handle.read() if handle else b"")
        return target.is_dir()

    def find_fallback(self, art: Article) -> None:
        """أحدث نسخة محفوظة **سابقة** تجتاز فحوص المحتوى وتصلح للنشر الآن.

        أحدث commit يمسّ الحزمة هو النسخة المحجوزة نفسها، فلا يُجرَّب: قد
        يجتاز فحوص المحتوى ويكون عطله في Hugo أو SEO أو الميزانيات.
        """
        for commit, when in self.history(art.slug)[1:]:
            if commit in art.rejected:
                continue
            work = self.scratch / art.slug / commit[:12]
            exported = work / "export" / art.slug
            staged = work / "staged" / art.slug
            if work.exists():
                shutil.rmtree(work)
            if not self.export(commit, art.slug, exported):
                continue
            try:
                if prepare_content.bundle_is_archived(exported):
                    continue
            except prepare_content.BundleProblem:
                continue
            prepare_content.stage_bundle(exported, staged)
            fronts = [read_front(p) for p in sorted(staged.glob("index.*.md"))]
            if not fronts or any(f.get("archived") for f in fronts):
                continue
            shown = [f for f in fronts if not f.get("draft")]
            dates = [parse_date(f.get("date")) for f in shown]
            # نسخة بديلة لمقال منشور يجب أن تظهر الآن، لا مسودة ولا مجدولة.
            if not shown or any(d is None or d > self.now for d in dates):
                continue
            if check_content.check_bundle(str(staged), self.schema):
                continue
            art.fallback = {"commit": commit, "committed_at": when}
            art.fallback_dir = staged
            return

    # ── نسبة الأعطال إلى المقالات ─────────────────────────────────────
    def built_slugs(self) -> set[str]:
        return {p.name for p in CONTENT.iterdir()
                if p.is_dir() and not p.name.startswith(".")} if CONTENT.is_dir() else set()

    def slug_of_page(self, page: str) -> str | None:
        parts = Path(page).parts
        if parts and parts[0] == "ar":
            parts = parts[1:]
        if len(parts) >= 2 and parts[0] in self.built_slugs():
            return parts[0]
        return None

    def attribute_hugo(self, output: str) -> tuple[dict[str, list[str]], list[str]]:
        slugs = sorted(self.built_slugs(), key=len, reverse=True)
        found: dict[str, list[str]] = {}
        orphans = []
        for line in output.splitlines():
            if not HUGO_ERROR.search(line) or HUGO_SUMMARY.search(line):
                continue
            hits = [s for s in slugs
                    if re.search(r"(?<![A-Za-z0-9-])" + re.escape(s)
                                 + r"(?=[/\\\"'»:)\s]|$)", line)]
            if not hits:
                orphans.append(line)
            for slug in hits:
                found.setdefault(slug, []).append(line.strip())
        return found, orphans

    def last_change(self, slug: str) -> int:
        """لحظة آخر حفظ يمسّ المقال (ثوانٍ)؛ 0 إن لم يُعرف."""
        try:
            out = git(self.source, "log", "-1", "--format=%ct", "HEAD", "--",
                      f"{SOURCE_BUNDLES}/{slug}").strip()
        except subprocess.CalledProcessError:
            return 0
        return int(out) if out.isdigit() else 0

    def attribute_pages(self, items: list[dict]) -> tuple[dict[str, list[str]], list[dict]]:
        found: dict[str, list[str]] = {}
        orphans = []
        for item in items:
            page = str(item.get("page", ""))
            message = str(item.get("message", ""))
            if message.startswith(page + ": "):
                message = message[len(page) + 2:]
            slug = self.slug_of_page(page)
            # «مكرر مع <صفحة>»: check_seo يسمّي الصفحة الأخيرة أبجديًا، وقد تكون
            # المقال القديم البريء. المحجوز هو صاحب آخر حفظ — الوافد الجديد.
            duplicate = re.search(r"مكرر مع (\S+)", message)
            if slug is not None and duplicate:
                other = self.slug_of_page(duplicate.group(1))
                if other is not None and self.last_change(other) > self.last_change(slug):
                    slug, message = other, f"{message.split(' مكرر')[0]} مكرر مع {page}"
            if slug is None:
                orphans.append(item)
            else:
                found.setdefault(slug, []).append(message)
        return found, orphans

    def blame(self, stage: str, found: dict[str, list[str]]) -> None:
        built = self.built_slugs()
        if len(built) >= 2 and built <= set(found):
            # عطل يصيب كل المقالات معًا عطل قالب أو إعداد، لا عطل مقال.
            raise Fatal(stage, "الخطأ أصاب كل المقالات في الجولة نفسها — عطل عام في "
                               "القالب أو الإعداد، لا في مقال.",
                        "\n".join(line for lines in found.values() for line in lines[:2]))
        for slug, lines in found.items():
            art = self.articles.get(slug)
            if art is None:
                raise Fatal(stage, f"عطل منسوب إلى «{slug}» وليس في المحتوى.", "\n".join(lines))
            if art.fallback is not None:
                # النسخة السابقة نفسها لم تجتز هذه البوابة: جرّب أقدم منها.
                art.rejected.add(art.fallback["commit"])
                art.rejections.append({"stage": stage, **art.fallback,
                                       "message": " | ".join(lines)[:500]})
                art.fallback = None
                art.fallback_dir = None
            else:
                for line in lines:
                    art.problem(stage, short_paths(line)[:500])

    # ── جولة بناء ─────────────────────────────────────────────────────
    def gate_json(self, stage: str, tool: str) -> list[dict] | None:
        out_file = self.scratch / f"{stage}-{self.rounds}.json"
        rc, output = run([sys.executable, str(TOOLS / tool), str(self.public),
                          "--json-out", str(out_file)])
        if rc == 0:
            return None
        try:
            items = json.loads(out_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise Fatal(stage, f"بوابة {stage} فشلت دون تقرير مفهوم.", tail(output))
        if not items:
            raise Fatal(stage, f"بوابة {stage} فشلت دون مشكلات مسمّاة.", tail(output))
        return items

    def build_round(self) -> dict[str, list[str]]:
        """يعيد الأعطال المنسوبة إلى مقالات؛ قاموس فارغ = اجتازت البوابات كلها."""
        print(f"\n━━ الجولة {self.rounds}: بوابة عقد المحتوى (الشجرة كلها)")
        rc, output = run([sys.executable, str(TOOLS / "check_content.py"), str(CONTENT)])
        if rc != 0:
            raise Fatal("content", "عقد المحتوى فشل على ما بقي بعد الحجز.", tail(output))

        print(f"\n━━ الجولة {self.rounds}: Hugo")
        if self.public.exists():
            shutil.rmtree(self.public)
        rc, output = run([self.hugo, "--gc", "--minify", "--destination", str(self.public)])
        if rc != 0:
            found, orphans = self.attribute_hugo(output)
            if orphans or not found:
                raise Fatal("hugo", "Hugo فشل بخطأ لا يخص مقالًا بعينه.", tail(output))
            self.stage_failed = "hugo"
            return found

        print(f"\n━━ الجولة {self.rounds}: الخرائط والفهرسة")
        rc, output = run([sys.executable, str(TOOLS / "normalize_sitemaps.py"), str(self.public)])
        index = self.public / "index.html"
        if rc != 0 or not index.is_file() or index.stat().st_size == 0:
            raise Fatal("sitemaps", "تعذّر تجهيز خرائط اللغات أو الصفحة الرئيسية.", tail(output))
        rc, output = run([sys.executable, str(TOOLS / "check_indexing.py"), str(self.public)])
        if rc != 0:
            raise Fatal("indexing", "فحص الخرائط وRSS وIndexNow فشل.", tail(output))

        for stage, tool in (("seo", "check_seo.py"), ("budgets", "check_budgets.py")):
            print(f"\n━━ الجولة {self.rounds}: {stage}")
            items = self.gate_json(stage, tool)
            if items is None:
                continue
            found, orphans = self.attribute_pages(items)
            if orphans:
                lines = "\n".join(f"{i.get('page')}: {i.get('message')}" for i in orphans)
                raise Fatal(stage, f"بوابة {stage} فشلت على صفحة لا تخص مقالًا بعينه.", lines)
            self.stage_failed = stage
            return found
        return {}

    def run(self, prepare_problems: dict | None = None) -> None:
        prepare_problems = {} if prepare_problems is None else prepare_problems
        details: dict = {}
        print("━━ تجهيز المحتوى")
        try:
            copied, archived = prepare_content.prepare(
                self.source / "content", problems=prepare_problems, details=details)
        except prepare_content.PrepareError as exc:
            raise Fatal("prepare", f"تجهيز المحتوى فشل: {exc}")
        print(f"  جُهّزت {copied} حزمة · استُبعدت {archived} مؤرشفة · "
              f"{len(prepare_problems)} بمشكلة في التجهيز")
        self.load_inventory(prepare_problems, details)
        self.check_staged()
        for art in self.held():
            print(f"  ⏸ «{art.slug}» محجوز: " + " | ".join(p["message"] for p in art.problems))

        while True:
            self.rounds += 1
            if self.rounds > MAX_ROUNDS:
                raise Fatal("rounds", f"تجاوز البناء {MAX_ROUNDS} جولات حجز دون استقرار.")
            self.apply_holds()
            self.stage_failed = ""
            found = self.build_round()
            if not found:
                break
            for slug, lines in found.items():
                print(f"  ⏸ «{slug}» حُجز بعد {self.stage_failed}: {lines[0][:200]}")
            self.blame(self.stage_failed, found)
        self.classify()

    # ── الحالة النهائية لكل مقال ───────────────────────────────────────
    def classify(self) -> None:
        finished = self.now if self.fixed_now else now_riyadh()
        built = article_dirs(self.public) if self.public.is_dir() else set()
        for art in self.articles.values():
            art.published = [lang for lang in art.langs
                             if self.page(art.slug, lang).rsplit("/index.html", 1)[0] in built]
            if art.archived:
                art.status = "archived"
            elif art.problems and art.fallback is not None:
                art.status = "held_live_kept"
            elif art.problems:
                art.status = "draft" if art.draft else "held"
            elif art.draft:
                art.status = "draft"
            else:
                waiting = [lang for lang in art.langs
                           if lang not in art.published and not art.drafts.get(lang)]
                future = [lang for lang in waiting
                          if (parse_date(art.dates.get(lang)) or finished) > finished]
                missing = [lang for lang in waiting if lang not in future]
                if missing:
                    # اجتاز كل البوابات وتاريخه حلّ، ولم يخرج من Hugo: هذا هو
                    # «التخطي الصامت» نفسه. لا يمرّ بلا بلاغ للمالك.
                    art.status = "missing"
                elif future and not art.published:
                    art.status = "scheduled"
                else:
                    art.status = "published"
                    for lang in future:
                        art.notes.append(f"lang-scheduled:{lang}:{art.dates.get(lang)}")
                    for lang in art.langs:
                        if art.drafts.get(lang):
                            art.notes.append(f"lang-draft:{lang}")
        if self.site_blog is not None and self.site_blog.is_dir():
            self.removed_pages = sorted(article_dirs(self.site_blog) - built)

    def report(self, content_sha: str, content_date: str) -> dict:
        arts = [a.as_dict() for a in self.articles.values()]
        counts: dict[str, int] = {}
        for art in arts:
            counts[art["status"] or "unknown"] = counts.get(art["status"] or "unknown", 0) + 1
        return {
            "version": 1,
            "outcome": "blocked" if self.fatal else "ready",
            "generated_at": now_riyadh().isoformat(),
            "now": self.now.isoformat(),
            "content_sha": content_sha,
            "content_committed_at": content_date,
            "rounds": self.rounds,
            "fatal": None if self.fatal is None else {
                "stage": self.fatal.stage, "message": self.fatal.message,
                "output": self.fatal.output[-4000:],
            },
            "articles": arts,
            "removed_pages": self.removed_pages,
            "counts": counts,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="بناء المدونة بعزل كل مقال")
    parser.add_argument("--source", required=True, type=Path,
                        help="checkout مستودع المحتوى (بتاريخه كاملًا)")
    parser.add_argument("--site", type=Path, help="استنساخ zero2one-web لمعرفة المنشور حاليًا")
    parser.add_argument("--public", type=Path, default=ROOT / "public")
    parser.add_argument("--hugo", default="hugo")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--now", help="لحظة بديلة للاختبار فقط (ISO 8601)")
    args = parser.parse_args(argv)

    now = parse_date(args.now) if args.now else None
    builder = Builder(args.source, args.site, args.public, args.hugo, now)
    try:
        content_sha = git(builder.source, "rev-parse", "HEAD").strip()
        content_date = git(builder.source, "log", "-1", "--format=%cI", "HEAD").strip()
    except (OSError, subprocess.CalledProcessError):
        content_sha, content_date = "", ""
    try:
        builder.run()
    except Fatal as exc:
        builder.fatal = exc
        builder.classify()
        # تشغيل متوقّف لم يغيّر الموقع: لا «منشور» ولا «مجدول» من مخرج ناقص.
        for art in builder.articles.values():
            if art.status in ("published", "scheduled", "missing"):
                art.status = "blocked"
        print(f"\n  ⛔ لا نشر — {exc.stage}: {exc.message}")
        if exc.output:
            print(exc.output)
    finally:
        shutil.rmtree(builder.scratch, ignore_errors=True)

    data = builder.report(content_sha, content_date)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print("\n━━ حالة المقالات")
    for art in data["articles"]:
        extra = ""
        if art["status"] in ("held", "held_live_kept"):
            extra = " — " + " | ".join(p["message"] for p in art["problems"])[:300]
        print(f"  {art['status']:<15} {art['slug']}{extra}")
    for page in data["removed_pages"]:
        print(f"  removed         {page}")
    return 1 if builder.fatal else 0


if __name__ == "__main__":
    sys.exit(main())
