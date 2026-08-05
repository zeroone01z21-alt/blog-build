#!/usr/bin/env python3
"""اجمع جرد المدونة والروابط المحذوفة وأرسلها إلى IndexNow بعد النشر.

مفتاح IndexNow **عام بطبيعته**: البروتوكول يشترط نشره كملف نصي على
الموقع. نقرأه من static/ ولا نطبعه في السجلات أو payloadات التشخيص.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "controls" / "indexnow.json"
KEY_RE = re.compile(r"^[A-Za-z0-9-]{8,128}$")
MARKER_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
USER_AGENT = "ZERO2ONE-IndexNow/1.0 (+https://zero2one.sa/blog/)"


class IndexNowError(RuntimeError):
    pass


def load_config() -> dict[str, str]:
    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IndexNowError(f"تعذّر قراءة إعداد IndexNow: {exc}") from exc
    required = {
        "endpoint", "host", "key_file", "key_location",
        "deployment_marker", "url_prefix",
    }
    if (not isinstance(config, dict) or not required <= config.keys() or
            not all(isinstance(config[k], str) and config[k] for k in required)):
        raise IndexNowError("إعداد IndexNow ناقص أو غير صالح")
    if config["endpoint"] != "https://api.indexnow.org/indexnow":
        raise IndexNowError("نقطة IndexNow غير معتمدة")
    if config["host"] != "zero2one.sa":
        raise IndexNowError("مضيف IndexNow غير معتمد")
    if config["url_prefix"] != "https://zero2one.sa/blog/":
        raise IndexNowError("بادئة IndexNow يجب أن تبقى محصورة في /blog/")
    if not config["key_location"].startswith(config["url_prefix"]):
        raise IndexNowError("ملف مفتاح IndexNow يجب أن يبقى داخل /blog/")
    if config["key_location"] != f'{config["url_prefix"]}{Path(config["key_file"]).name}':
        raise IndexNowError("موقع مفتاح IndexNow غير معتمد")
    if config["deployment_marker"] != "https://zero2one.sa/blog/indexnow-deploy.txt":
        raise IndexNowError("موقع علامة النشر غير معتمد")
    return config


def read_key(config: dict[str, str]) -> str:
    key_path = ROOT / config["key_file"]
    try:
        key = key_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise IndexNowError(f"ملف مفتاح IndexNow مفقود: {key_path}") from exc
    if not KEY_RE.fullmatch(key):
        raise IndexNowError("صيغة مفتاح IndexNow غير صالحة")
    return key


def git_paths(repo: Path, args: list[str]) -> set[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), *args, "--", "blog/"],
        check=True,
        capture_output=True,
        text=True,
    )
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def changed_paths(repo: Path) -> set[str]:
    if not (repo / ".git").is_dir():
        raise IndexNowError(f"ليس مستودع Git: {repo}")
    try:
        paths = git_paths(repo, ["diff", "--name-only"])
        paths |= git_paths(repo, ["diff", "--cached", "--name-only"])
        paths |= git_paths(repo, ["ls-files", "--others", "--exclude-standard"])
        return paths
    except subprocess.CalledProcessError as exc:
        raise IndexNowError("تعذّر قراءة تغييرات مستودع الموقع") from exc


def html_path_to_url(path: str, prefix: str) -> str | None:
    item = PurePosixPath(path)
    if not item.parts or item.parts[0] != "blog":
        return None
    if item.name == "404.html" or item.suffix != ".html":
        return None
    if item.parts == ("blog", "en", "index.html"):
        # حُذف تحويل قديم كان على هذا الرابط. إخطار الرابط المحذوف يجعل محرك
        # البحث يعيد زيارته ويرى 404 بدل إبقائه في الفهرس.
        return f"{prefix}en/"
    if item.name != "index.html":
        return None
    relative = PurePosixPath(*item.parts[1:-1]).as_posix()
    return prefix if relative == "." else f"{prefix}{relative}/"


def urls_from_sitemaps(repo: Path, config: dict[str, str]) -> set[str]:
    urls: set[str] = set()
    for rel in ("blog/sitemap-en.xml", "blog/sitemap-ar.xml"):
        path = repo / rel
        try:
            root = ET.parse(path).getroot()
        except (OSError, ET.ParseError) as exc:
            raise IndexNowError(f"تعذّر قراءة {rel} عند تدوير المفتاح: {exc}") from exc
        for node in root.findall(f"{{{SITEMAP_NS}}}url"):
            loc = node.find(f"{{{SITEMAP_NS}}}loc")
            if loc is not None and loc.text:
                url = loc.text.strip()
                if url.startswith(config["url_prefix"]):
                    urls.add(url)
    return urls


def preserve_previous_marker(repo: Path, config: dict[str, str]) -> str:
    """أعِد علامة HEAD بعد استبدال blog/ كي لا نصنع commit حذف وهميًا."""
    marker_name = Path(urlparse(config["deployment_marker"]).path).name
    marker_path = repo / "blog" / marker_name
    if marker_path.exists():
        try:
            previous = marker_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise IndexNowError("تعذّر قراءة علامة النشر السابقة") from exc
    else:
        result = subprocess.run(
            ["git", "-C", str(repo), "show", f"HEAD:blog/{marker_name}"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return ""
        previous = result.stdout.strip()
    if not MARKER_RE.fullmatch(previous):
        raise IndexNowError("علامة النشر السابقة غير صالحة")
    if not marker_path.exists():
        marker_path.write_text(previous + "\n", encoding="utf-8")
    return previous


def collect(repo: Path, output: Path, deployment_id: str) -> int:
    config = load_config()
    if not MARKER_RE.fullmatch(deployment_id):
        raise IndexNowError("معرّف النشر غير صالح")
    previous_marker = preserve_previous_marker(repo, config)
    paths = changed_paths(repo)
    changed_urls = {
        url for path in paths
        if (url := html_path_to_url(path, config["url_prefix"])) is not None
    }
    inventory = urls_from_sitemaps(repo, config)
    if paths:
        # نرسل الجرد الحالي مع المحذوفات. هذا يعوّض إخطارًا سابقًا تعطل بعد
        # push، ويضمن أن URL المحذوف يبقى حاضرًا في طلب إعادة الزحف.
        urls = inventory | changed_urls
        marker = deployment_id
        marker_name = Path(urlparse(config["deployment_marker"]).path).name
        marker_path = repo / "blog" / marker_name
        marker_path.write_text(marker + "\n", encoding="utf-8")
    else:
        # تشغيل بلا diff قد يكون التعويض الذي يلي تشغيلًا أُلغي بعد الدفع.
        # أعد إرسال الجرد مربوطًا بآخر علامة، من دون صناعة commit جديد.
        urls = inventory if previous_marker else set()
        marker = previous_marker
    ordered = sorted(urls)
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {"deployment_marker": marker, "urls": ordered}
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(f"  روابط IndexNow المرشحة: {len(ordered)}")
    for url in ordered:
        print(f"    {url}")
    return 0


def load_manifest(path: Path, config: dict[str, str]) -> tuple[list[str], str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IndexNowError(f"تعذّر قراءة قائمة IndexNow: {exc}") from exc
    if not isinstance(data, dict):
        raise IndexNowError("بيان IndexNow يجب أن يكون كائن JSON")
    urls_value = data.get("urls")
    marker = data.get("deployment_marker")
    if (not isinstance(urls_value, list) or
            not all(isinstance(url, str) for url in urls_value)):
        raise IndexNowError("قائمة IndexNow ليست مصفوفة روابط")
    if not isinstance(marker, str) or (marker and not MARKER_RE.fullmatch(marker)):
        raise IndexNowError("علامة نشر IndexNow غير صالحة")
    urls = sorted(set(urls_value))
    if len(urls) > 10_000:
        raise IndexNowError("IndexNow يقبل 10,000 رابط كحد أقصى")
    if any(not url.startswith(config["url_prefix"]) for url in urls):
        raise IndexNowError("القائمة تحوي رابطًا خارج /blog/")
    if urls and not marker:
        raise IndexNowError("قائمة IndexNow غير الفارغة تحتاج علامة نشر")
    return urls, marker


def remote_text_matches(location: str, expected: str) -> bool:
    request = urllib.request.Request(location, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body = response.read(1025)
            return (response.status == 200 and len(body) <= 1024 and
                    body.decode("utf-8").strip() == expected)
    except (OSError, UnicodeDecodeError, urllib.error.URLError):
        return False


def wait_for_deployment(config: dict[str, str], marker: str, seconds: int) -> None:
    deadline = time.monotonic() + seconds
    while True:
        if remote_text_matches(config["deployment_marker"], marker):
            print("  ✅ ظهر نشر الموقع المطابق لطلب IndexNow")
            return
        if time.monotonic() >= deadline:
            raise IndexNowError("نشر الموقع لم يظهر ضمن مهلة IndexNow")
        time.sleep(min(10, max(1, int(deadline - time.monotonic()))))


def post_urls(config: dict[str, str], key: str, urls: list[str]) -> int:
    payload = json.dumps({
        "host": config["host"],
        "key": key,
        "keyLocation": config["key_location"],
        "urlList": urls,
    }).encode("utf-8")
    delays = (0, 5, 15, 30)
    last_status: int | None = None
    for delay in delays:
        if delay:
            time.sleep(delay)
        request = urllib.request.Request(
            config["endpoint"],
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                status = response.status
        except urllib.error.HTTPError as exc:
            status = exc.code
        except (OSError, urllib.error.URLError):
            status = 0
        last_status = status
        if status in {200, 202}:
            print(f"  ✅ IndexNow استلم {len(urls)} رابط (HTTP {status})")
            return 0
        if status not in {0, 429} and status < 500:
            break
    raise IndexNowError(f"رفض IndexNow الإرسال (HTTP {last_status or 'network'})")


def submit(path: Path, wait_seconds: int, dry_run: bool) -> int:
    config = load_config()
    key = read_key(config)
    urls, marker = load_manifest(path, config)
    if not urls:
        print("  لا روابط متغيّرة — لا إخطار IndexNow")
        return 0
    if dry_run:
        print(f"  ✅ طلب IndexNow صالح — {len(urls)} رابط (لم يُرسل)")
        return 0
    wait_for_deployment(config, marker, wait_seconds)
    if not remote_text_matches(config["key_location"], key):
        raise IndexNowError("مفتاح IndexNow المنشور مفقود أو لا يطابق المصدر")
    return post_urls(config, key, urls)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="IndexNow للمدونة")
    commands = root.add_subparsers(dest="command", required=True)
    collect_cmd = commands.add_parser("collect", help="جمع الجرد الحالي والروابط المحذوفة")
    collect_cmd.add_argument("repo", type=Path, help="مستودع الموقع بعد استبدال blog/")
    collect_cmd.add_argument("--output", type=Path, required=True)
    collect_cmd.add_argument("--deployment-id", required=True,
                             help="معرّف فريد يُستخدم للتحقق من وصول النشر")
    submit_cmd = commands.add_parser("submit", help="إرسال القائمة بعد ظهور النشر")
    submit_cmd.add_argument("urls", type=Path, help="ملف JSON الناتج من collect")
    submit_cmd.add_argument("--wait-seconds", type=int, default=180)
    submit_cmd.add_argument("--dry-run", action="store_true")
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "collect":
            return collect(args.repo.resolve(), args.output.resolve(), args.deployment_id)
        if args.wait_seconds < 0:
            raise IndexNowError("مهلة الانتظار لا يمكن أن تكون سالبة")
        return submit(args.urls.resolve(), args.wait_seconds, args.dry_run)
    except IndexNowError as exc:
        print(f"  ❌ {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
