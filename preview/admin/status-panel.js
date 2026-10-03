/*
 * بلاغات النشر — داخل لوحة الكاتب نفسها
 * ======================================
 *
 * لماذا: الكاتب يحفظ في اللوحة ويظن أن المقال نُشر. في سبتمبر 2026 بقي مقالان
 * خارج الموقع ثمانية أيام لأن سبب الرفض كان في سجل GitHub Actions وحده.
 *
 * ماذا: زرّ «بلاغات النشر» يعرض نتيجة آخر محاولة نشر: ما لم يُنشر ولماذا وما
 * المطلوب، وما هو مجدول ومتى، وما إذا تعطّل النشر لسبب عام.
 *
 * من أين: سجل آخر تشغيل لـbuild.yml عبر واجهة GitHub العامة — بلا دخول ولا
 * رمز ولا Issues. tools/blog_report.py يكتب الحالة في تعليق notice عنوانه
 * blog-status-v1 (JSON مضغوط بـzlib ثم base64).
 *
 * أمان: نصّ المقالات من الكاتب، فيُعرض بـtextContent وحده؛ لا حقن HTML ولا
 * روابط من البيانات إلا رابط سجل التشغيل بعد التحقق من بدايته. الواجهة كلها
 * في Shadow DOM فلا تتأثر بأنماط Sveltia ولا تؤثر فيها. check_cms.py يتحقق
 * من بصمة هذا الملف (SRI) ومن أنه لا يتصل إلا بمستودع blog-build.
 */
(function () {
  "use strict";

  // عناوين كاملة حرفيًّا: check_cms.py يقارنها بقائمة المسموح.
  var API = "https://api.github.com/repos/zeroone01z21-alt/blog-build";
  var RUN_PREFIX = "https://github.com/zeroone01z21-alt/blog-build/actions/runs/";
  var STATUS_TITLE = "blog-status-v1";
  var JOB_NAME = "بناء ونشر";
  var CACHE_KEY = "z2o-blog-status-v1";
  var CACHE_MS = 2 * 60 * 1000;

  var STAGES = {
    prepare: "تجهيز المقال",
    content: "فحص المحتوى",
    hugo: "توليد الصفحة",
    seo: "فحص الصفحة الناتجة",
    budgets: "حجم الصفحة"
  };
  var HINTS = {
    hugo: "غالبًا صورة داخل النص غير موجودة أو مكتوبة يدويًا: احذفها وأعد إدراجها من زرّ الصورة.",
    seo: "راجع عناوين المقال (عنوان فارغ أو قفزة في الدرجات، أو عنوان مكرر مع مقال آخر).",
    budgets: "صفحة المقال ثقيلة على الجوال: صغّر الصور الكبيرة أو قلّل عددها."
  };

  // ── أدوات ─────────────────────────────────────────────────────────────
  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (key) {
      if (key === "text") node.textContent = attrs[key];
      else node.setAttribute(key, attrs[key]);
    });
    (children || []).forEach(function (child) {
      if (child) node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
    });
    return node;
  }

  function when(value) {
    if (!value) return "؟";
    var moment = new Date(value);
    if (isNaN(moment.getTime())) return String(value);
    try {
      return new Intl.DateTimeFormat("ar-SA-u-nu-latn-ca-gregory", {
        timeZone: "Asia/Riyadh", year: "numeric", month: "long", day: "numeric",
        hour: "2-digit", minute: "2-digit", hour12: false
      }).format(moment);
    } catch (error) {
      return moment.toISOString().slice(0, 16).replace("T", " ") + " UTC";
    }
  }

  function readCache() {
    try {
      var saved = JSON.parse(window.sessionStorage.getItem(CACHE_KEY) || "null");
      if (saved && Date.now() - saved.at < CACHE_MS) return saved;
    } catch (error) { /* التخزين قد يكون ممنوعًا؛ نجلب من جديد */ }
    return null;
  }

  function writeCache(state) {
    try {
      window.sessionStorage.setItem(CACHE_KEY, JSON.stringify(state));
    } catch (error) { /* اختياري */ }
  }

  function getJSON(url) {
    return fetch(url, { headers: { Accept: "application/vnd.github+json" }, cache: "no-store" })
      .then(function (response) {
        if (!response.ok) {
          var failure = new Error("HTTP " + response.status);
          failure.status = response.status;
          throw failure;
        }
        return response.json();
      });
  }

  function decode(text) {
    if (typeof DecompressionStream === "undefined") return Promise.resolve(null);
    var bytes = Uint8Array.from(window.atob(text), function (c) { return c.charCodeAt(0); });
    var stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("deflate"));
    return new Response(stream).text().then(JSON.parse);
  }

  // ── الجلب: آخر تشغيل مكتمل، ثم مهمته، ثم تعليقاتها ─────────────────────
  function load() {
    return getJSON(API + "/actions/workflows/build.yml/runs?per_page=10").then(function (data) {
      var runs = (data && data.workflow_runs) || [];
      var running = runs.some(function (run) { return run.status !== "completed"; });
      var latest = runs.filter(function (run) {
        return run.status === "completed" && run.conclusion !== "cancelled" && run.conclusion !== "skipped";
      })[0];
      var state = { at: Date.now(), running: running, run: null, status: null, decodeFailed: false };
      if (!latest) return state;
      state.run = {
        conclusion: latest.conclusion,
        at: latest.run_started_at || latest.created_at,
        url: String(latest.html_url || "").indexOf(RUN_PREFIX) === 0 ? latest.html_url : ""
      };
      return getJSON(API + "/actions/runs/" + latest.id + "/jobs?per_page=20").then(function (jobs) {
        var list = (jobs && jobs.jobs) || [];
        var job = list.filter(function (item) { return item.name === JOB_NAME; })[0] || list[0];
        if (!job) return state;
        return getJSON(API + "/check-runs/" + job.id + "/annotations?per_page=50").then(function (notes) {
          var note = (notes || []).filter(function (item) { return item.title === STATUS_TITLE; })[0];
          if (!note) return state;
          return decode(String(note.message || "").trim()).then(function (status) {
            state.status = status;
            state.decodeFailed = !status;
            return state;
          }, function () {
            state.decodeFailed = true;
            return state;
          });
        });
      });
    });
  }

  // ── العرض ─────────────────────────────────────────────────────────────
  var CSS = [
    ":host{all:initial}",
    "*{box-sizing:border-box;font-family:system-ui,-apple-system,'Segoe UI',Tahoma,sans-serif}",
    ".wrap{position:fixed;left:16px;bottom:16px;z-index:2147483000;direction:rtl}",
    ".toggle{display:flex;align-items:center;gap:8px;border:1px solid #c9ced6;background:#fff;color:#1c2330;",
    "border-radius:999px;padding:8px 14px;font-size:14px;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.15)}",
    ".toggle:focus-visible,.panel button:focus-visible,.panel a:focus-visible{outline:3px solid #2f6feb;outline-offset:2px}",
    ".badge{min-width:22px;height:22px;border-radius:11px;padding:0 6px;display:inline-flex;align-items:center;",
    "justify-content:center;font-size:13px;font-weight:700;color:#fff;background:#8a93a3}",
    ".badge.bad{background:#c62828}.badge.good{background:#2e7d32}",
    ".panel{position:absolute;left:0;bottom:52px;width:min(420px,calc(100vw - 32px));max-height:min(70vh,560px);",
    "overflow:auto;background:#fff;color:#1c2330;border:1px solid #c9ced6;border-radius:12px;",
    "box-shadow:0 8px 28px rgba(0,0,0,.22);padding:16px;font-size:14px;line-height:1.7}",
    ".panel[hidden]{display:none}",
    "h2{font-size:16px;margin:0 0 8px}h3{font-size:14px;margin:14px 0 6px}",
    ".line{margin:4px 0}.muted{color:#5b6472;font-size:13px}",
    ".item{border:1px solid #e3e6eb;border-radius:8px;padding:8px 10px;margin:6px 0}",
    ".item strong{display:block}.slug{direction:ltr;unicode-bidi:isolate;font-family:ui-monospace,Menlo,monospace;font-size:12px;color:#5b6472}",
    "ul{margin:4px 0;padding-inline-start:18px}",
    ".alert{background:#fdecea;border:1px solid #f5c2bd;border-radius:8px;padding:8px 10px}",
    ".ok{background:#e8f5e9;border:1px solid #b9dfbb;border-radius:8px;padding:8px 10px}",
    ".foot{display:flex;gap:12px;align-items:center;justify-content:space-between;margin-top:12px;flex-wrap:wrap}",
    ".foot button{border:1px solid #c9ced6;background:#f6f7f9;border-radius:6px;padding:4px 10px;cursor:pointer;font-size:13px}",
    "a{color:#1f5fbf}"
  ].join("");

  var host, root, toggle, badge, panel;

  function itemBlock(entry, extra) {
    var lines = [];
    (entry.p || []).forEach(function (problem) {
      lines.push(el("li", { text: (STAGES[problem[0]] || problem[0]) + ": " + problem[1] }));
    });
    var hints = [];
    (entry.p || []).forEach(function (problem) {
      if (HINTS[problem[0]] && hints.indexOf(HINTS[problem[0]]) < 0) hints.push(HINTS[problem[0]]);
    });
    var lang = (entry.l || []).indexOf("ar") >= 0 ? "ar" : "en";
    return el("div", { "class": "item" }, [
      el("strong", { text: entry.n || entry.s }),
      el("span", { "class": "slug", text: entry.s }),
      extra ? el("div", { "class": "line", text: extra }) : null,
      lines.length ? el("ul", {}, lines) : null,
      hints.length ? el("div", { "class": "line muted", text: hints.join(" ") }) : null,
      entry.st === "scheduled" ? null : el("a", {
        href: "#/collections/posts_" + lang,
        text: lang === "ar" ? "افتح المقالات العربية لإصلاحه ←" : "افتح المقالات الإنجليزية لإصلاحه ←"
      })
    ]);
  }

  function section(title, entries, extraFor) {
    if (!entries.length) return null;
    return el("div", {}, [el("h3", { text: title })].concat(entries.map(function (entry) {
      return itemBlock(entry, extraFor ? extraFor(entry) : "");
    })));
  }

  function render(state, error) {
    var body = [el("h2", { id: "z2o-status-title", text: "بلاغات النشر" })];
    var needs = 0;
    if (error) {
      body.push(el("div", { "class": "alert", text: error.status === 403 || error.status === 429
        ? "تعذّر جلب الحالة الآن (حدّ الطلبات في GitHub). جرّب بعد دقائق."
        : "تعذّر جلب حالة النشر الآن. تحقّق من الاتصال ثم اضغط «تحديث»." }));
    } else if (!state.run) {
      body.push(el("div", { "class": "line", text: "لا توجد محاولة نشر سابقة بعد." }));
    } else {
      var status = state.status;
      var blocked = state.run.conclusion !== "success" || (status && status.o === "blocked");
      body.push(el("div", { "class": "line muted", text: "آخر محاولة نشر: " + when(state.run.at) + " (بتوقيت الرياض)" }));
      if (state.running) {
        body.push(el("div", { "class": "line", text: "⏳ يجري الآن نشر جديد. اضغط «تحديث» بعد دقائق." }));
      }
      if (blocked) {
        needs += 1;
        body.push(el("div", { "class": "alert", text: "⛔ لم تكتمل آخر محاولة نشر بسبب عطل عام. محتواك محفوظ، " +
          "والمالك مُبلَّغ. لا تكرّر الحفظ؛ تُعاد المحاولة تلقائيًا." }));
      }
      if (!status) {
        if (state.decodeFailed) {
          body.push(el("div", { "class": "line muted", text: "تعذّر عرض التفاصيل في هذا المتصفح. حدّثه أو افتح التفاصيل التقنية." }));
        }
      } else {
        var by = function (name) { return (status.a || []).filter(function (entry) { return entry.st === name; }); };
        var held = by("held").concat(by("missing"));
        var kept = by("held_live_kept");
        needs += held.length + kept.length;
        [
          section("لم يُنشر — يحتاج إصلاحًا", held),
          section("تعديل محجوز — النسخة السابقة ما زالت ظاهرة على الموقع", kept, function (entry) {
            return entry.k ? "الموقع يعرض نسختك المحفوظة في " + when(entry.k) + "." : "";
          }),
          section("مجدول — يظهر تلقائيًا", by("scheduled"), function (entry) {
            return "يظهر بعد " + when(entry.w) + " بتوقيت الرياض (خلال ساعة تقريبًا من الموعد).";
          }),
          section("مسودات تحتاج إصلاحًا قبل نشرها", by("draft"))
        ].forEach(function (block) { if (block) body.push(block); });
        if (!blocked && !held.length && !kept.length) {
          body.push(el("div", { "class": "ok", text: "✅ كل المقالات الجاهزة منشورة." }));
        }
        if (status.more) {
          body.push(el("div", { "class": "line muted", text: "وبنود أخرى (" + status.more + ") في التفاصيل التقنية." }));
        }
      }
    }
    var refresh = el("button", { type: "button", text: "تحديث" });
    refresh.addEventListener("click", function () { update(true); });
    body.push(el("div", { "class": "foot" }, [
      state && state.run && state.run.url ? el("a", { href: state.run.url, target: "_blank", rel: "noopener noreferrer",
        text: "التفاصيل التقنية" }) : el("span", {}),
      el("span", { "class": "muted", text: state ? "آخر تحقق: " + when(state.at) : "" }),
      refresh
    ]));
    while (panel.firstChild) panel.removeChild(panel.firstChild);
    body.forEach(function (node) { panel.appendChild(node); });

    badge.textContent = error ? "؟" : String(needs);
    badge.className = "badge " + (error ? "" : needs ? "bad" : "good");
    toggle.setAttribute("aria-label", error ? "بلاغات النشر — تعذّر الجلب"
      : needs ? "بلاغات النشر — " + needs + " يحتاج انتباهًا" : "بلاغات النشر — لا شيء يحتاج انتباهًا");
  }

  var pending = null;
  function update(force) {
    var cached = force ? null : readCache();
    if (cached) { render(cached); return Promise.resolve(); }
    if (pending) return pending;
    pending = load().then(function (state) {
      writeCache(state);
      render(state);
    }, function (error) {
      render(null, error);
    }).then(function () { pending = null; });
    return pending;
  }

  function open(show) {
    panel.hidden = !show;
    toggle.setAttribute("aria-expanded", show ? "true" : "false");
    if (show) {
      update(false);
      var heading = panel.querySelector("h2");
      if (heading) { heading.setAttribute("tabindex", "-1"); heading.focus(); }
    } else {
      toggle.focus();
    }
  }

  function mount() {
    if (document.getElementById("z2o-blog-status")) return;
    host = el("div", { id: "z2o-blog-status" });
    root = host.attachShadow({ mode: "open" });
    root.appendChild(el("style", { text: CSS }));
    badge = el("span", { "class": "badge", text: "…" });
    toggle = el("button", { type: "button", "class": "toggle", "aria-expanded": "false",
      "aria-controls": "z2o-status-panel" }, [el("span", { text: "بلاغات النشر" }), badge]);
    panel = el("div", { id: "z2o-status-panel", "class": "panel", role: "dialog",
      "aria-labelledby": "z2o-status-title", hidden: "" });
    toggle.addEventListener("click", function () { open(panel.hidden); });
    root.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && !panel.hidden) open(false);
    });
    root.appendChild(el("div", { "class": "wrap" }, [panel, toggle]));
    document.body.appendChild(host);
    update(false);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
  else mount();
})();
