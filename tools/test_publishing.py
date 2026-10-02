#!/usr/bin/env python3
"""
اختبارات موثوقية النشر — بلا شبكة وبلا Hugo
=============================================

تغطي ما أُضيف في 2026-10 كي لا يعود ما حدث في سبتمبر:
توقيت الرياض، صور النص، حجز المقال وحده ونسخته السابقة، نسبة أعطال
Hugo وSEO والميزانيات إلى مقالاتها، حالة كل مقال، البلاغ، والجدولة.

    python3 tools/test_publishing.py        # يعمل في controls.yml أيضًا
"""

from __future__ import annotations

import datetime as dt
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))

import blog_report  # noqa: E402
import build_blog  # noqa: E402
import check_content  # noqa: E402
import prepare_content  # noqa: E402
import schedule_check  # noqa: E402

RIYADH = dt.timezone(dt.timedelta(hours=3))
BODY = ("## مقدمة\n\n" + "هذا نصّ تجريبي يكفي طوله لاجتياز حدّ المحتوى الأدنى. " * 8 + "\n")


def article(slug: str, *, title: str = "عنوان تجريبي صالح للمقال", date: str =
            "2026-09-01T10:00:00+03:00", draft: bool = False, archived: bool = False,
            body: str = BODY, extra: str = "") -> str:
    return (
        "---\n"
        f'title: "{title}"\n'
        'description: "وصف تجريبي صالح يزيد طوله عن خمسين محرفًا كي يجتاز حدود العقد بلا مشكلة."\n'
        f'slug: "{slug}"\n'
        f'date: "{date}"\n'
        f"draft: {'true' if draft else 'false'}\n"
        f"archived: {'true' if archived else 'false'}\n"
        "categories:\n  - seo\n"
        'featured_image: "cover.webp"\n'
        'featured_image_alt: "وصف الصورة"\n'
        f"{extra}"
        "---\n"
        f"{body}"
    )


def write_bundle(root: Path, slug: str, text: str, lang: str = "ar",
                 files: tuple[str, ...] = ("cover.webp",)) -> Path:
    bundle = root / slug
    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / f"index.{lang}.md").write_text(text, encoding="utf-8")
    for name in files:
        (bundle / name).write_bytes(b"RIFF0000WEBP")
    return bundle


def git(repo: Path, *args: str, when: str = "") -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    if when:
        env.update(GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when)
    return subprocess.run(["git", "-C", str(repo), *args], check=True, env=env,
                          capture_output=True, text=True).stdout.strip()


class Sandbox(unittest.TestCase):
    """مجلد مؤقت يحلّ محل ROOT/content كي لا تلمس الاختبارات المستودع."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="publishing-test-"))
        (self.tmp / "controls").mkdir()
        shutil.copy(ROOT / "controls" / "schema.json", self.tmp / "controls" / "schema.json")
        self.saved = (prepare_content.ROOT, prepare_content.DESTINATION, build_blog.CONTENT)
        prepare_content.ROOT = self.tmp
        prepare_content.DESTINATION = self.tmp / "content"
        build_blog.CONTENT = self.tmp / "content"
        self.schema = check_content.load_schema()

    def tearDown(self) -> None:
        prepare_content.ROOT, prepare_content.DESTINATION, build_blog.CONTENT = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def content_repo(self) -> Path:
        repo = self.tmp / "blog-content"
        (repo / "content" / "blog").mkdir(parents=True)
        for lang in ("ar", "en"):
            (repo / "content" / f"_index.{lang}.md").write_text(
                "---\ntitle: \"مدونة من الصفر إلى الواحد\"\n"
                "description: \"وصف قسم المدونة بطول يكفي لاجتياز حدّ الخمسين محرفًا المطلوب في العقد.\"\n"
                "---\n", encoding="utf-8")
        git(repo, "init", "-q", "-b", "main")
        return repo


# ── توقيت الرياض ─────────────────────────────────────────────────────────
class RiyadhTime(Sandbox):
    def test_wall_clock_digits_are_riyadh(self) -> None:
        cases = {
            "2026-09-16T10:07:00-07:00": ("2026-09-16T10:07:00+03:00", "-07:00"),
            "2026-09-12T09:30:00-0700": ("2026-09-12T09:30:00+03:00", "-0700"),
            "2026-08-07T20:22": ("2026-08-07T20:22:00+03:00", ""),
            "2026-10-05": ("2026-10-05T00:00:00+03:00", ""),
            "2026-10-05 10:00:00Z": ("2026-10-05T10:00:00+03:00", "Z"),
            "2026-07-07T04:37:31+03:00": ("2026-07-07T04:37:31+03:00", "+03:00"),
            "2026-09-16T10:07:00.123-07:00": ("2026-09-16T10:07:00+03:00", "-07:00"),
        }
        for raw, expected in cases.items():
            self.assertEqual(prepare_content.riyadh_wall_clock(raw), expected, raw)
        for raw in ("2026-02-30T10:00:00+03:00", "tomorrow", "", "2026-13-01"):
            self.assertIsNone(prepare_content.riyadh_wall_clock(raw), raw)

    def test_normalise_touches_front_matter_only(self) -> None:
        path = self.tmp / "index.ar.md"
        path.write_text('---\ntitle: "x"\ndate: "2026-09-16T10:07:00-07:00"\n'
                        "lastmod: 2026-09-17T08:00:00Z\n---\n"
                        "date: 2020-01-01T00:00:00Z\n", encoding="utf-8")
        changes = prepare_content.normalise_dates(path)
        text = path.read_text(encoding="utf-8")
        self.assertIn('date: "2026-09-16T10:07:00+03:00"', text)
        self.assertIn("lastmod: 2026-09-17T08:00:00+03:00", text)
        self.assertTrue(text.endswith("date: 2020-01-01T00:00:00Z\n"), "النص لا يُمسّ")
        self.assertEqual([c["offset"] for c in changes], ["-07:00", "Z"])
        self.assertEqual(prepare_content.normalise_dates(path), [], "التسوية ثابتة")

    def test_unparseable_date_is_left_for_the_checker(self) -> None:
        path = self.tmp / "index.ar.md"
        path.write_text('---\ndate: "غدًا"\n---\nنص\n', encoding="utf-8")
        self.assertEqual(prepare_content.normalise_dates(path), [])
        self.assertIn('date: "غدًا"', path.read_text(encoding="utf-8"))

    def test_hugo_time_zone_matches_the_offset(self) -> None:
        self.assertIn("timeZone = 'Asia/Riyadh'", (ROOT / "hugo.toml").read_text(encoding="utf-8"))
        self.assertEqual(prepare_content.RIYADH_OFFSET, "+03:00")


# ── صور النص والاتساق ───────────────────────────────────────────────────
class ContentChecks(Sandbox):
    def test_markdown_image_targets_skip_code(self) -> None:
        body = ("![a](one.webp)\n![b](<two.webp> \"t\")\n`![c](inline.webp)`\n"
                "```\n![d](fenced.webp)\n```\n![e](three.webp 'x')\n")
        self.assertEqual(check_content.markdown_image_targets(body),
                         ["one.webp", "two.webp", "three.webp"])

    def test_inline_images_must_live_in_the_bundle(self) -> None:
        body = BODY + "\n![ok](cover.webp)\n![gone](missing.webp)\n" \
                      "![ext](https://example.com/x.webp)\n![up](../other/x.webp)\n"
        bundle = write_bundle(self.tmp / "content", "post-one", article("post-one", body=body))
        messages = [m for _, m in check_content.check_bundle(str(bundle), self.schema)]
        self.assertEqual(len(messages), 3, messages)
        self.assertTrue(any("missing.webp" in m and "غير موجودة" in m for m in messages))
        self.assertTrue(any("رابط خارجي" in m for m in messages))
        self.assertTrue(any("غير صالح" in m for m in messages))

    def test_consistency_runs_on_the_staged_layout(self) -> None:
        staged = self.tmp / "content"
        write_bundle(staged, "right-name", article("other-name"))
        problems: list = []
        check_content.check_bundle_consistency(str(staged), problems)
        self.assertTrue(any("slug" in m for _, m in problems), problems)


# ── التجهيز المتسامح ─────────────────────────────────────────────────────
class LenientPrepare(Sandbox):
    def test_one_bad_bundle_does_not_stop_the_rest(self) -> None:
        repo = self.content_repo()
        blog = repo / "content" / "blog"
        write_bundle(blog, "good-post", article("good-post"))
        write_bundle(blog, "mixed-archive", article("mixed-archive"), lang="ar")
        (blog / "mixed-archive" / "index.en.md").write_text(
            article("mixed-archive", archived=True), encoding="utf-8")
        problems: dict = {}
        details: dict = {}
        copied, archived = prepare_content.prepare(repo / "content",
                                                   problems=problems, details=details)
        self.assertEqual((copied, archived), (1, 0))
        self.assertIn("mixed-archive", problems)
        self.assertTrue((self.tmp / "content" / "good-post").is_dir())
        with self.assertRaises(prepare_content.BundleProblem) as raised:
            prepare_content.prepare(repo / "content")
        self.assertIn("mixed-archive:", str(raised.exception))

    def test_staged_copy_gets_riyadh_dates_and_source_stays(self) -> None:
        repo = self.content_repo()
        source = write_bundle(repo / "content" / "blog", "tz-post",
                              article("tz-post", date="2026-09-16T10:07:00-07:00"))
        details: dict = {}
        prepare_content.prepare(repo / "content", details=details)
        staged = (self.tmp / "content" / "tz-post" / "index.ar.md").read_text(encoding="utf-8")
        self.assertIn('date: "2026-09-16T10:07:00+03:00"', staged)
        self.assertIn("-07:00", (source / "index.ar.md").read_text(encoding="utf-8"))
        self.assertEqual(details["tz-post"]["dates"][0]["offset"], "-07:00")


# ── الحجز والنسخة السابقة ───────────────────────────────────────────────
class Holds(Sandbox):
    def make(self, now: str = "2026-10-01T12:00:00+03:00"):
        repo = self.content_repo()
        blog = repo / "content" / "blog"
        write_bundle(blog, "live-post", article("live-post"))
        write_bundle(blog, "new-post", article("new-post"))
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "v1")
        good = git(repo, "rev-parse", "HEAD")
        broken = BODY + "\n### \n"
        (blog / "live-post" / "index.ar.md").write_text(article("live-post", body=broken),
                                                         encoding="utf-8")
        (blog / "new-post" / "index.ar.md").write_text(article("new-post", body=broken),
                                                        encoding="utf-8")
        git(repo, "commit", "-q", "-am", "v2 broken")
        site = self.tmp / "site"
        page = site / "blog" / "ar" / "live-post"
        page.mkdir(parents=True)
        (page / "index.html").write_text("<html>live</html>", encoding="utf-8")
        builder = build_blog.Builder(repo, site, self.tmp / "public", "hugo",
                                     build_blog.parse_date(now))
        self.addCleanup(shutil.rmtree, builder.scratch, True)
        return repo, site, good, builder

    def prepare(self, builder) -> None:
        problems: dict = {}
        details: dict = {}
        prepare_content.prepare(builder.source / "content", problems=problems, details=details)
        builder.load_inventory(problems, details)
        builder.check_staged()

    def test_live_article_keeps_last_good_version(self) -> None:
        _, _, good, builder = self.make()
        self.prepare(builder)
        builder.apply_holds()
        live = builder.articles["live-post"]
        self.assertEqual(live.fallback["commit"], good)
        staged = (self.tmp / "content" / "live-post" / "index.ar.md").read_text(encoding="utf-8")
        self.assertNotIn("### \n", staged, "النسخة المبنية هي السليمة")
        self.assertFalse((self.tmp / "content" / "new-post").exists(),
                         "مقال لم يُنشر قط يُحجز ولا يُبنى")
        self.assertTrue(any("عنوان فارغ" in p["message"] for p in live.problems))

    def test_no_good_version_stops_everything(self) -> None:
        _, _, good, builder = self.make()
        self.prepare(builder)
        builder.articles["live-post"].rejected.add(good)
        with self.assertRaises(build_blog.Fatal) as raised:
            builder.apply_holds()
        self.assertEqual(raised.exception.stage, "hold")

    def test_fallback_must_be_visible_now(self) -> None:
        _, _, _, builder = self.make(now="2026-08-01T00:00:00+03:00")
        self.prepare(builder)
        with self.assertRaises(build_blog.Fatal):
            builder.apply_holds()      # v1 مؤرَّخ بعد «الآن» المفترض: لا يصلح بديلًا

    def test_blame_rejects_a_failing_fallback(self) -> None:
        _, _, good, builder = self.make()
        self.prepare(builder)
        builder.apply_holds()
        builder.blame("hugo", {"live-post": ["ERROR … live-post/index.ar.md …"]})
        live = builder.articles["live-post"]
        self.assertIsNone(live.fallback)
        self.assertIn(good, live.rejected)
        self.assertEqual(live.rejections[0]["stage"], "hugo")


# ── نسبة الأعطال ────────────────────────────────────────────────────────
class Attribution(Sandbox):
    def builder(self) -> build_blog.Builder:
        for slug in ("social-media-campaign-management", "seo", "seo-tips"):
            (self.tmp / "content" / slug).mkdir(parents=True)
        builder = build_blog.Builder(self.tmp, None, self.tmp / "public", "hugo")
        self.addCleanup(shutil.rmtree, builder.scratch, True)
        return builder

    def test_hugo_lines(self) -> None:
        b = self.builder()
        output = "\n".join([
            "Start building sites …",
            "ERROR صورة Markdown «x.webp» في social-media-campaign-management/index.ar.md "
            "ليست داخل حزمة المقال أو غير موجودة",
            'Error: error building site: process: readAndProcessContent: '
            '"/home/runner/work/blog-build/blog-build/content/seo-tips/index.ar.md:3:1": '
            "failed to unmarshal YAML",
            "ERROR error building site: logged 2 error(s)",
            "WARN  something harmless",
        ])
        found, orphans = b.attribute_hugo(output)
        self.assertEqual(sorted(found), ["seo-tips", "social-media-campaign-management"])
        self.assertEqual(orphans, [])
        _, orphans = b.attribute_hugo('ERROR template: _default/single.html:12:5: executing "main"')
        self.assertEqual(len(orphans), 1, "عطل قالب لا يُنسب إلى مقال")
        found, _ = b.attribute_hugo('ERROR render of "/ar/seo-tips" failed: execute of template')
        self.assertEqual(list(found), ["seo-tips"], "مسار الصفحة يكفي للنسبة")

    def test_duplicate_title_blames_the_newcomer(self) -> None:
        repo = self.content_repo()
        blog = repo / "content" / "blog"
        write_bundle(blog, "old-post", article("old-post"))
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "old", when="2026-09-01T10:00:00+03:00")
        write_bundle(blog, "new-post", article("new-post"))
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "new", when="2026-09-20T10:00:00+03:00")
        for slug in ("old-post", "new-post"):
            (self.tmp / "content" / slug).mkdir(parents=True)
        b = build_blog.Builder(repo, None, self.tmp / "public", "hugo")
        self.addCleanup(shutil.rmtree, b.scratch, True)
        # check_seo يسمّي الأخيرة أبجديًا (old-post)، والمحجوز يجب أن يكون الوافد.
        found, orphans = b.attribute_pages([{
            "page": "ar/old-post/index.html",
            "message": "title مكرر مع ar/new-post/index.html"}])
        self.assertEqual(orphans, [])
        self.assertEqual(list(found), ["new-post"])
        self.assertIn("ar/old-post/index.html", found["new-post"][0])

    def test_messages_lose_absolute_paths(self) -> None:
        line = ('ERROR error building site: "/home/runner/work/b/b/content/x/index.ar.md:3:6": '
                '"/home/runner/work/b/b/layouts/_default/_markup/render-image.html:3:6": failed')
        self.assertEqual(build_blog.short_paths(line),
                         'ERROR error building site: "content/x/index.ar.md:3:6": '
                         '"layouts/_default/_markup/render-image.html:3:6": failed')
        b = self.builder()
        found, _ = b.attribute_pages([{"page": "ar/seo/index.html",
                                       "message": "ar/seo/index.html: المسار الحرج تجاوز"}])
        self.assertEqual(found["seo"], ["المسار الحرج تجاوز"], "الصفحة لا تتكرر في الرسالة")

    def test_failure_in_every_article_is_a_template_fault(self) -> None:
        b = self.builder()
        for slug in b.built_slugs():
            b.articles[slug] = build_blog.Article(slug)
        with self.assertRaises(build_blog.Fatal):
            b.blame("hugo", {slug: ["ERROR x"] for slug in b.built_slugs()})
        b.blame("hugo", {"seo": ["ERROR y"]})
        self.assertEqual(b.articles["seo"].problems[0]["stage"], "hugo")

    def test_pages(self) -> None:
        b = self.builder()
        self.assertEqual(b.slug_of_page("ar/seo-tips/index.html"), "seo-tips")
        self.assertEqual(b.slug_of_page("seo-tips/photo.webp"), "seo-tips")
        for page in ("categories/seo/index.html", "404.html", ".htaccess",
                     "ar/.htaccess", "ar/index.html", "index.html"):
            self.assertIsNone(b.slug_of_page(page), page)
        found, orphans = b.attribute_pages([
            {"page": "ar/seo/index.html", "message": "h3 فارغ"},
            {"page": "ar/categories/seo/index.html", "message": "title مكرر"},
        ])
        self.assertEqual(list(found), ["seo"])
        self.assertEqual(len(orphans), 1)


# ── الحالة النهائية ──────────────────────────────────────────────────────
class Classification(Sandbox):
    def test_statuses(self) -> None:
        now = build_blog.parse_date("2026-10-01T12:00:00+03:00")
        public, site = self.tmp / "public", self.tmp / "site" / "blog"
        for root, pages in ((public, ["ar/pub", "ar/kept"]), (site, ["ar/pub", "ar/kept", "ar/gone"])):
            for page in pages:
                (root / page).mkdir(parents=True)
                (root / page / "index.html").write_text("x", encoding="utf-8")
        b = build_blog.Builder(self.tmp, self.tmp / "site", public, "hugo", now)
        self.addCleanup(shutil.rmtree, b.scratch, True)

        def art(slug, date="2026-09-01T10:00:00+03:00", **kw):
            a = build_blog.Article(slug)
            a.langs, a.dates, a.drafts = ["ar"], {"ar": date}, {"ar": kw.get("draft", False)}
            a.archived = kw.get("archived", False)
            a.problems = kw.get("problems", [])
            a.fallback = kw.get("fallback")
            b.articles[slug] = a
        art("pub")
        art("later", date="2026-10-03T09:00:00+03:00")
        art("lost")
        art("bad", problems=[{"stage": "content", "message": "x"}])
        art("kept", problems=[{"stage": "content", "message": "x"}], fallback={"commit": "c"})
        art("wip", draft=True)
        art("old", archived=True)
        b.classify()
        got = {slug: a.status for slug, a in b.articles.items()}
        self.assertEqual(got, {"pub": "published", "later": "scheduled", "lost": "missing",
                               "bad": "held", "kept": "held_live_kept", "wip": "draft",
                               "old": "archived"})
        self.assertEqual(b.removed_pages, ["ar/gone"])


# ── البلاغ ───────────────────────────────────────────────────────────────
def report_with(*articles: dict, fatal: dict | None = None) -> dict:
    return {"report": {"outcome": "blocked" if fatal else "ready", "fatal": fatal,
                       "articles": list(articles), "removed_pages": [], "counts": {},
                       "rounds": 1, "content_sha": "a" * 40},
            "outcomes": {"run_url": "https://example.invalid/run"}}


HELD = {"slug": "held-post", "status": "held", "titles": {"ar": "مقال [محجوز](https://x) |@someone"},
        "problems": [{"stage": "content", "message": "الكلمة المفتاحية غائبة"}]}


class FakeAPI:
    def __init__(self, issues=None, list_status=200, scheduler_state="active"):
        self.calls: list[tuple[str, str, dict | None]] = []
        self.issues = issues or []
        self.list_status = list_status
        self.scheduler_state = scheduler_state

    def __call__(self, method, path, token, body=None):
        self.calls.append((method, path, body))
        if path.endswith("/actions/workflows/schedule.yml") and method == "GET":
            return 200, {"state": self.scheduler_state}, {}
        if path.endswith("/enable"):
            return 204, None, {}
        if method == "GET" and "/issues?" in path:
            return self.list_status, (self.issues if self.list_status == 200 else None), {}
        if method == "POST" and path.endswith("/issues"):
            return 201, {"number": 7}, {}
        if method == "POST" and path.endswith("/comments"):
            return 201, {}, {}
        return 200, {}, {}

    def methods(self) -> list[str]:
        return [f"{m} {p.split('/repos/r/')[-1]}" for m, p, _ in self.calls]


class Report(unittest.TestCase):
    def setUp(self) -> None:
        self.saved_api = blog_report.api

    def tearDown(self) -> None:
        blog_report.api = self.saved_api

    def test_clean_neutralises_markup(self) -> None:
        text = blog_report.clean("a|b <x> [l](u) `c` @user")
        for bad in ("|", "<", "[l]", "`c`", "@user"):
            self.assertNotIn(bad, text)

    def test_attention_and_fingerprint(self) -> None:
        items = blog_report.attention(report_with(HELD))
        self.assertEqual(len(items), 1)
        again = blog_report.attention(report_with(HELD))
        self.assertEqual(blog_report.fingerprint(items), blog_report.fingerprint(again))
        changed = dict(HELD, problems=[{"stage": "content", "message": "مشكلة أخرى"}])
        self.assertNotEqual(blog_report.fingerprint(items),
                            blog_report.fingerprint(blog_report.attention(report_with(changed))))
        fatal = blog_report.attention(report_with(fatal={"stage": "hugo", "message": "x"}))
        self.assertTrue(fatal[0]["key"].startswith("fatal:"))
        self.assertTrue(blog_report.attention({"report": None})[0]["key"] == "no-report")

    def test_token_expiry(self) -> None:
        parse = blog_report.parse_expiry
        self.assertEqual(parse("2026-10-20 12:00:00 UTC").utcoffset(), dt.timedelta(0))
        self.assertEqual(parse("2026-10-20 12:00:00 -0700").utcoffset(), dt.timedelta(hours=-7))
        self.assertIsNone(parse("soon"))
        bundle = {"report": report_with()["report"],
                  "token": {"status": "expiring", "expires_at": "2026-10-20", "days_left": 18}}
        self.assertTrue(any(i["key"].startswith("token:") for i in blog_report.attention(bundle)))

    def test_pack_roundtrip(self) -> None:
        bundle = report_with(HELD)
        self.assertEqual(blog_report.unpack(blog_report.pack(bundle)), bundle)
        self.assertIsNone(blog_report.unpack("not base64!"))

    def test_issues_disabled_is_a_warning(self) -> None:
        fake = FakeAPI(list_status=410)
        blog_report.api = fake
        self.assertEqual(blog_report.notify(report_with(HELD), "r", "t", ["owner"]), 0)
        self.assertFalse(any(m == "POST" for m, _, _ in fake.calls))

    def test_open_update_quiet_close(self) -> None:
        fake = FakeAPI()
        blog_report.api = fake
        blog_report.notify(report_with(HELD), "r", "t", ["owner"])
        created = [b for m, p, b in fake.calls if m == "POST" and p.endswith("/issues")]
        self.assertEqual(len(created), 1)
        self.assertIn("@owner", created[0]["body"])
        self.assertNotIn("@someone", created[0]["body"], "لا إشارة من نصّ المقال")

        issue = {"number": 7, "body": created[0]["body"]}
        fake = FakeAPI(issues=[issue])
        blog_report.api = fake
        blog_report.notify(report_with(HELD), "r", "t", ["owner"])
        self.assertFalse(any(p.endswith("/comments") for _, p, _ in fake.calls),
                         "لا تعليق ما دام لا شيء تغيّر")

        fake = FakeAPI(issues=[issue])
        blog_report.api = fake
        resolved = dict(HELD, status="published", problems=[])
        blog_report.notify(report_with(resolved), "r", "t", ["owner"])
        closing = [b for m, p, b in fake.calls if m == "PATCH"]
        self.assertEqual(closing[-1], {"state": "closed", "state_reason": "completed"})

    def test_scheduler_is_reenabled_after_inactivity(self) -> None:
        fake = FakeAPI(scheduler_state="disabled_inactivity")
        blog_report.api = fake
        self.assertEqual(blog_report.ensure_scheduler("r", "t"), [])
        self.assertTrue(any(p.endswith("/schedule.yml/enable") for _, p, _ in fake.calls))
        fake = FakeAPI(scheduler_state="disabled_manually")
        blog_report.api = fake
        items = blog_report.ensure_scheduler("r", "t")
        self.assertEqual(items[0]["who"], "owner")
        self.assertFalse(any(p.endswith("/enable") for _, p, _ in fake.calls),
                         "التعطيل اليدوي قرار مالك لا يُلغى آليًّا")

    def test_failure_after_the_builder_means_nothing_published(self) -> None:
        bundle = report_with(dict(HELD, slug="ok-post", status="published", problems=[]))
        bundle["outcomes"]["job"] = "failure"
        bundle["outcomes"]["push"] = "failure"
        text = blog_report.summary_markdown(bundle)
        self.assertIn("لم يُنشر شيء", text)
        self.assertNotIn("✅ منشور: ", text, "لا عدّاد «منشور» لما لم يصل إلى الموقع")
        keys = [i["key"] for i in blog_report.attention(bundle)]
        self.assertIn("post-build-failure", keys)

    def test_summary_for_blocked_run(self) -> None:
        text = blog_report.summary_markdown(report_with(fatal={"stage": "hugo", "message": "x"}))
        self.assertIn("لم يُنشر شيء", text)


# ── لوحة البلاغات داخل لوحة الكاتب ──────────────────────────────────────────
class Panel(unittest.TestCase):
    def decode(self, text: str) -> dict:
        import base64
        import json
        import zlib
        return json.loads(zlib.decompress(base64.b64decode(text)))

    def test_status_record_lists_what_needs_the_writer(self) -> None:
        scheduled = {"slug": "later", "status": "scheduled", "titles": {"ar": "لاحق"},
                     "dates": {"ar": "2026-10-05T10:00:00+03:00"}}
        clean_draft = {"slug": "wip", "status": "draft", "titles": {"ar": "مسودة"}, "problems": []}
        data = self.decode(blog_report.status_payload(
            report_with(HELD, scheduled, clean_draft, dict(HELD, slug="ok", status="published"))))
        self.assertEqual(data["o"], "ready")
        self.assertEqual([a["s"] for a in data["a"]], ["held-post", "later"],
                         "المنشور والمسودة السليمة لا يظهران")
        self.assertEqual(data["a"][1]["w"], "2026-10-05T10:00:00+03:00")

    def test_status_record_marks_blocked_runs_and_stays_small(self) -> None:
        data = self.decode(blog_report.status_payload(report_with(fatal={"stage": "hugo", "message": "x"})))
        self.assertEqual(data["o"], "blocked")
        # نصوص فريدة (عشوائية) كي لا يبتلع الضغط الحجم فيبقى الحد بلا اختبار
        many = [dict(HELD, slug=f"post-{i}", titles={"ar": f"عنوان {os.urandom(24).hex()}"},
                     problems=[{"stage": "content", "message": os.urandom(90).hex()}
                               for _ in range(3)])
                for i in range(40)]
        text = blog_report.status_payload(report_with(*many))
        self.assertLessEqual(len(text), blog_report.STATUS_LIMIT)
        self.assertGreater(self.decode(text).get("more", 0), 0, "الزائد يُعدّ ولا يُسقَط صامتًا")

    def test_summary_emits_the_record_for_the_panel(self) -> None:
        import contextlib
        import io
        import json
        tmp = Path(tempfile.mkdtemp(prefix="panel-test-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "r.json").write_text(json.dumps(report_with(HELD)["report"]), encoding="utf-8")
        out = io.StringIO()
        saved = os.environ.pop("GITHUB_STEP_SUMMARY", None)
        try:
            with contextlib.redirect_stdout(out):
                blog_report.main(["summary", "--report", str(tmp / "r.json")])
        finally:
            if saved is not None:
                os.environ["GITHUB_STEP_SUMMARY"] = saved
        lines = [l for l in out.getvalue().splitlines() if l.startswith("::notice title=blog-status-v1::")]
        self.assertEqual(len(lines), 1)

    def test_dashboard_guard(self) -> None:
        import check_cms
        index = (ROOT / "preview" / "admin" / "index.html").read_text(encoding="utf-8")
        self.assertEqual(check_cms.panel_problems(index), [], "اللوحة الحالية سليمة")
        source = (ROOT / "preview" / "admin" / "status-panel.js").read_text(encoding="utf-8")
        self.assertIn("textContent", source)
        saved = check_cms.PANEL
        tmp = Path(tempfile.mkdtemp(prefix="panel-guard-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        try:
            bad = tmp / "status-panel.js"
            bad.write_text(source + '\nfetch("https://evil.example/x"); el.innerHTML = t;\n', encoding="utf-8")
            check_cms.PANEL = str(bad)
            found = " | ".join(check_cms.panel_problems(index))
            self.assertIn("SRI", found)
            self.assertIn("evil.example", found)
            self.assertIn("innerHTML", found)
        finally:
            check_cms.PANEL = saved
        preview = (ROOT / ".github" / "workflows" / "preview.yml").read_text(encoding="utf-8")
        self.assertIn("preview/admin/status-panel.js", preview, "المعاينة تنشر ملف اللوحة")


# ── الجدولة ──────────────────────────────────────────────────────────────
def run(sha: str = "", *, status="completed", conclusion="success", started="2026-10-01T08:00:00Z",
        updated="2026-10-01T08:05:00Z", created=None, head="tpl") -> dict:
    return {"display_title": f"نشر المدونة · {sha}" if sha else "نشر المدونة · يدوي",
            "status": status, "conclusion": conclusion, "run_started_at": started,
            "created_at": created or started, "updated_at": updated, "head_sha": head}


class Scheduling(unittest.TestCase):
    sha = "b" * 40
    commit = dt.datetime(2026, 10, 1, 7, 0, tzinfo=dt.timezone.utc)
    now = dt.datetime(2026, 10, 1, 12, 0, tzinfo=dt.timezone.utc)

    def decide(self, runs, dates=()):
        return schedule_check.decide(runs, self.sha, self.commit, "tpl", list(dates), self.now)

    def test_branches(self) -> None:
        due = dt.datetime(2026, 10, 1, 13, 0, tzinfo=RIYADH)          # 10:00Z
        earlier = dt.datetime(2026, 10, 1, 10, 0, tzinfo=RIYADH)      # 07:00Z
        self.assertEqual(self.decide([run(self.sha, status="queued")])[0], "wait")
        self.assertEqual(self.decide([run("c" * 40)])[0], "dispatch", "إشارة ضائعة")
        self.assertEqual(self.decide([run(self.sha)], [("p", due)]),
                         ("dispatch", "حان موعد: p"))
        self.assertEqual(self.decide([run(self.sha)], [("p", earlier)])[0], "wait")
        self.assertEqual(self.decide([run(created="2026-10-01T07:30:00Z")])[0], "wait",
                         "تشغيل يدوي بعد آخر حفظة يغطيها")
        recent = run(self.sha, conclusion="failure", updated="2026-10-01T11:30:00Z")
        self.assertEqual(self.decide([recent])[0], "wait")
        old = run(self.sha, conclusion="failure", updated="2026-10-01T09:00:00Z")
        self.assertEqual(self.decide([old])[0], "dispatch")
        self.assertEqual(self.decide([old, old, old])[0], "wait", "ثلاث محاولات بحدّ أقصى")
        other_tpl = run(self.sha, conclusion="failure", updated="2026-10-01T09:00:00Z", head="new")
        self.assertEqual(self.decide([old, other_tpl, other_tpl])[0], "dispatch",
                         "إصلاح القوالب يعيد المحاولات")

    def test_due_dates_use_the_riyadh_rule(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="schedule-test-"))
        try:
            blog = tmp / "content" / "blog"
            write_bundle(blog, "tz", article("tz", date="2026-09-16T10:07:00-07:00"))
            write_bundle(blog, "wip", article("wip", draft=True))
            write_bundle(blog, "old", article("old", archived=True))
            dates = schedule_check.due_dates(tmp)
            self.assertEqual(dates, [("tz", dt.datetime(2026, 9, 16, 10, 7, tzinfo=RIYADH))])
        finally:
            shutil.rmtree(tmp)


# ── عقود الملفات ─────────────────────────────────────────────────────────
class Contracts(unittest.TestCase):
    def read(self, name: str) -> str:
        return (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")

    def test_runner_pinned_everywhere(self) -> None:
        for path in (ROOT / ".github" / "workflows").glob("*.yml"):
            runners = re.findall(r"(?m)^\s*runs-on:\s*(\S+)", path.read_text(encoding="utf-8"))
            self.assertTrue(runners, path.name)
            self.assertEqual(set(runners), {"ubuntu-24.04"}, path.name)

    def test_build_workflow_shape(self) -> None:
        build = self.read("build.yml")
        self.assertIn("fetch-depth: 0", build)
        self.assertIn("tools/build_blog.py", build)
        self.assertNotIn("schedule:", build.split("jobs:")[0],
                         "لا جدول في build.yml: تعطيله لخمول المستودع يوقف النشر كله")
        build_job = build.split("  notify:")[0].split("jobs:")[1]
        self.assertNotIn("write", build_job.split("steps:")[0],
                         "مهمة البناء تقرأ فقط")
        notify_job = build.split("  notify:")[1]
        self.assertIn("issues: write", notify_job)
        self.assertIn("needs.build.outputs.report", notify_job)

    def test_scheduler_is_separate(self) -> None:
        schedule = self.read("schedule.yml")
        self.assertIn("cron:", schedule)
        self.assertIn("tools/schedule_check.py", schedule)

    def test_new_tools_are_guarded(self) -> None:
        import check_controls
        for tool in ("tools/build_blog.py", "tools/blog_report.py",
                     "tools/schedule_check.py", "tools/test_publishing.py"):
            self.assertIn(tool, check_controls.GUARDED_FILES, tool)


if __name__ == "__main__":
    unittest.main(verbosity=2)
