#!/usr/bin/env python3
"""Static-site generator for the hourly Hong Kong cross-platform issue tracker digest.

Usage:
    python3 build.py [--data data/reports] [--out public] [--config config.json] [--strict]

Reads one JSON file per hourly report (data/reports/YYYY-MM-DD-HH.json, see data/SCHEMA.md)
and regenerates the whole site into ./public (index, reports/, days/, sitemap.xml, favicon.svg,
404.html). Pure Python 3 standard library. Idempotent: output is built into a temporary
directory and swapped in, and contains no build-time timestamps, so identical input gives
byte-identical output.

All report content is treated as untrusted: every string is HTML-escaped, links are only
emitted for absolute http(s) URLs, and JSON-LD is escaped against </script> breakout.

Exit codes: 0 = ok; 1 = fatal error; 2 = site built but some report files were skipped
as invalid (with --strict, invalid files abort the build with exit code 1 instead).
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent

try:
    from zoneinfo import ZoneInfo
    HKT = ZoneInfo("Asia/Hong_Kong")
except Exception:  # tzdata missing: HK has had no DST since 1979, fixed +08:00 is exact
    HKT = timezone(timedelta(hours=8), "HKT")

DISCLAIMER = "本報反映指定範圍內可取得的公開討論，不代表香港整體民意；未收集到不等於沒有相關討論。"
MAX_ISSUES = 5
MAX_LEADS = 2
MAX_HEADS = 4
REPORT_ID_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-(\d{2})$")
LIST_CAP = 5  # ADHD-friendly layout: at most 5 visible items per list; the rest go behind <details>
MAX_KEY = 3   # 重點 block: 1-3 most important issues
ADHD_CSS = """
/* ADHD-friendly layout: 重點 block, edition diff, collapsed list overflow */
.keypts{ margin:0; padding:0; list-style:none; border:1px solid var(--line); border-left:3px solid var(--fg); border-radius:var(--radius); }
.keypts li{ padding:10px 16px; line-height:1.7; color:var(--fg-2); }
.keypts li + li{ border-top:1px solid var(--line); }
.keypts a{ font-weight:600; color:var(--fg); }
.keypts .tag{ margin-right:6px; }
.hl-top{ border-bottom:1px solid var(--line); padding:24px 0; }
.hl-top .label{ display:block; margin-bottom:10px; }
.hl-top .go{ display:inline-block; margin-top:10px; font:500 13px/1.5 var(--mono); }
.fields.diff > div{ padding:8px 24px; }
@media (max-width:720px){ .fields.diff > div{ grid-template-columns:120px 1fr; gap:0 12px; padding:8px 16px; } }
details.more{ margin-top:8px; }
details.more > summary{ cursor:pointer; font:500 12px/1.8 var(--mono); color:var(--muted); }
details.more > summary:hover{ color:var(--fg); }
details.more[open] > summary{ margin-bottom:8px; }
"""

WD_EN = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
WD_ZH = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]

STATUS = {  # key -> (label, css class)
    "new": ("新發現", "s-new"),
    "tracking": ("持續追蹤", "s-tracking"),
    "shift": ("觀點變化", "s-shift"),
    "cooling": ("降溫", "s-cooling"),
    "lead": ("早期線索", "s-lead"),
}
STATUS_BY_LABEL = {v[0]: k for k, v in STATUS.items()}
READ_LEVEL = {
    "full": "完整讀取",
    "partial": "部分讀取",
    "snippet": "只讀摘要／片段",
    "title_only": "只有標題",
    "metadata": "只有元數據",
    "failed": "讀取失敗",
}
VERIFY = {
    "verified": "已核實",
    "partially_verified": "部分核實",
    "unverified": "未核實",
    "disputed": "存在矛盾",
}
TRACK_KIND = {
    "follow_up": "持續追蹤",
    "correction": "更正",
    "shift": "觀點變化",
    "cooling": "降溫",
    "resolved": "已完結",
}
USAGE_FIELDS = [
    ("sources_attempted", "嘗試來源數"),
    ("sources_ok", "成功讀取來源"),
    ("items_collected", "收集項目"),
    ("items_read_full", "完整讀取項目"),
    ("llm_calls", "模型呼叫次數"),
    ("tokens_in", "輸入 tokens"),
    ("tokens_out", "輸出 tokens"),
    ("cost_usd", "估算成本（USD）"),
    ("runtime_seconds", "執行時間（秒）"),
]


class ReportError(Exception):
    pass


# --------------------------------------------------------------------------- helpers

def e(v) -> str:
    """HTML-escape anything (None -> '')."""
    if v is None:
        return ""
    return html.escape(str(v), quote=True)


def s(v) -> str:
    """Coerce a scalar JSON value to a stripped string."""
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return str(v).strip()


def paras(v) -> list[str]:
    """String or list of strings -> list of non-empty paragraphs."""
    if v is None:
        return []
    if isinstance(v, list):
        return [s(x) for x in v if s(x)]
    t = s(v)
    return [p.strip() for p in re.split(r"\n\s*\n", t) if p.strip()] if t else []


def safe_url(u) -> str | None:
    """Return the URL only if it is an absolute http(s) URL without control chars."""
    u = s(u)
    if not u or len(u) > 2048 or re.search(r"[\x00-\x20\x7f\"<>\\`]", u):
        return None
    try:
        p = urlsplit(u)
    except ValueError:
        return None
    if p.scheme.lower() not in ("http", "https") or not p.netloc:
        return None
    return u


def parse_ts(v, field: str) -> datetime:
    t = s(v)
    if not t:
        raise ReportError(f"{field}: missing timestamp")
    if t.endswith(("Z", "z")):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        raise ReportError(f"{field}: not ISO 8601: {v!r}")
    if dt.tzinfo is None:
        raise ReportError(f"{field}: timestamp must carry a zone (store UTC, e.g. ...Z): {v!r}")
    return dt.astimezone(timezone.utc)


def opt_ts(v, field: str) -> datetime | None:
    return parse_ts(v, field) if s(v) else None


def hk(dt: datetime) -> datetime:
    return dt.astimezone(HKT)


def fmt_hkt(dt: datetime | None, tz_label=True) -> str:
    if dt is None:
        return ""
    d = hk(dt)
    return d.strftime("%Y-%m-%d %H:%M") + (" HKT" if tz_label else "")


def fmt_window(a: datetime, b: datetime) -> str:
    ha, hb = hk(a), hk(b)
    end = hb.strftime("%H:%M") if ha.date() == hb.date() else hb.strftime("%Y-%m-%d %H:%M")
    return f"[{ha.strftime('%Y-%m-%d %H:%M')}, {end}) HKT"


def zh_date(date: str) -> str:
    y, m, d = (int(x) for x in date.split("-"))
    return f"{y}年{m}月{d}日"


def weekday(date: str) -> tuple[str, str]:
    w = datetime.strptime(date, "%Y-%m-%d").weekday()
    return WD_EN[w], WD_ZH[w]


def num(v) -> str:
    if isinstance(v, bool):
        return "是" if v else "否"
    if isinstance(v, int):
        return f"{v:,}"
    if isinstance(v, float):
        return f"{v:,.4f}".rstrip("0").rstrip(".")
    return s(v)


def slug(v: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", v).strip("-") or "x"


def status_of(v) -> tuple[str, str]:
    k = s(v)
    k = STATUS_BY_LABEL.get(k, k)
    if k in STATUS:
        return STATUS[k]
    return (k or "未標示", "s-other")


def tag(label: str, cls: str = "") -> str:
    return f'<span class="tag{(" " + cls) if cls else ""}">{e(label)}</span>'


def ext_link(u, text=None) -> str:
    url = safe_url(u)
    if not url:
        return f'<span class="nourl" title="非 http(s) 或無效連結，已停用">{e(s(u) or "（無連結）")}</span>'
    return (f'<a class="ext" href="{e(url)}" rel="noopener noreferrer nofollow ugc" '
            f'title="{e(url)}">{e(text if text is not None else url)}</a>')


def json_ld(obj) -> str:
    txt = json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=False)
    txt = txt.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return f'<script type="application/ld+json">\n{txt}\n</script>\n'


# --------------------------------------------------------------------------- model

class Report:
    def __init__(self, rid: str, data: dict, path: Path):
        self.id = rid
        self.data = data
        self.path = path
        m = REPORT_ID_RE.match(rid)
        self.date, self.hour = m.group(1), m.group(2)
        self.warnings: list[str] = []
        self._validate()

    def _validate(self):
        d = self.data
        if not isinstance(d, dict):
            raise ReportError("top level must be a JSON object")
        if d.get("schema_version") != 1:
            raise ReportError("schema_version must be 1")
        self.mode = s(d.get("mode"))
        if self.mode not in ("fixture", "live"):
            raise ReportError("mode must be 'fixture' or 'live'")
        w = d.get("window") or {}
        if not isinstance(w, dict):
            raise ReportError("window must be an object")
        self.start = parse_ts(w.get("start"), "window.start")
        self.end = parse_ts(w.get("end"), "window.end")
        if self.end <= self.start:
            raise ReportError("window.end must be after window.start")
        self.generated = parse_ts(d.get("generated_at"), "generated_at")
        hs = hk(self.start)
        if (hs.strftime("%Y-%m-%d"), hs.strftime("%H")) != (self.date, self.hour):
            self.warnings.append(
                f"filename {self.id} does not match window.start in HKT ({hs:%Y-%m-%d-%H}); filename wins")
        for key, cap in (("issues", MAX_ISSUES), ("early_leads", MAX_LEADS)):
            lst = d.get(key) or []
            if not isinstance(lst, list):
                raise ReportError(f"{key} must be a list")
            if len(lst) > cap:
                self.warnings.append(f"{key}: {len(lst)} given, only first {cap} rendered")
            lst = lst[:cap]
            for i, it in enumerate(lst):
                if not isinstance(it, dict):
                    raise ReportError(f"{key}[{i}] must be an object")
                for req in ("issue_id", "name"):
                    if not s(it.get(req)):
                        raise ReportError(f"{key}[{i}].{req} is required")
                for j, ev in enumerate(it.get("evidence") or []):
                    if not isinstance(ev, dict) or not s(ev.get("evidence_id")):
                        raise ReportError(f"{key}[{i}].evidence[{j}] needs evidence_id")
                    if s(ev.get("url")) and not safe_url(ev.get("url")):
                        self.warnings.append(f"{key}[{i}].evidence[{j}]: url is not http(s); rendered as text")
                    opt_ts(ev.get("published_at"), f"{key}[{i}].evidence[{j}].published_at")
                    opt_ts(ev.get("observed_at"), f"{key}[{i}].evidence[{j}].observed_at")
                obs = it.get("observed") or {}
                if obs:
                    opt_ts(obs.get("start"), f"{key}[{i}].observed.start")
                    opt_ts(obs.get("end"), f"{key}[{i}].observed.end")
            setattr(self, key, lst)
        self.tracking = d.get("tracking") or []
        if not isinstance(self.tracking, list) or not all(isinstance(t, dict) for t in self.tracking):
            raise ReportError("tracking must be a list of objects")
        for k in ("sources", "usage"):
            if d.get(k) is not None and not isinstance(d.get(k), dict):
                raise ReportError(f"{k} must be an object")
        self.sources = d.get("sources") or {}
        self.usage = d.get("usage") or {}

    # derived labels
    @property
    def when(self) -> str:
        return f"{self.date} {self.hour}:00"

    @property
    def title(self) -> str:
        return f"{zh_date(self.date)} {self.hour}:00 每小時議題快報"

    def heads(self) -> list[tuple[str, str, str]]:
        out = [(it, *status_of(it.get("status"))) for it in self.issues]
        out += [(it, *STATUS["lead"]) for it in self.early_leads]
        return [(s(it.get("name")), lab, cls) for it, lab, cls in out[:MAX_HEADS]]


def load_reports(data_dir: Path, strict: bool) -> tuple[list[Report], int]:
    reports, bad = [], 0
    for p in sorted(data_dir.glob("*.json")):
        rid = p.stem
        if not REPORT_ID_RE.match(rid):
            print(f"[skip] {p.name}: filename must be YYYY-MM-DD-HH.json", file=sys.stderr)
            bad += 1
            continue
        try:
            datetime.strptime(rid, "%Y-%m-%d-%H")
            with p.open(encoding="utf-8") as f:
                data = json.load(f)
            r = Report(rid, data, p)
        except (ReportError, ValueError, OSError) as ex:
            print(f"[invalid] {p.name}: {ex}", file=sys.stderr)
            bad += 1
            if strict:
                raise SystemExit(1)
            continue
        for w in r.warnings:
            print(f"[warn] {p.name}: {w}", file=sys.stderr)
        reports.append(r)
    reports.sort(key=lambda r: r.id, reverse=True)  # newest first
    return reports, bad


# --------------------------------------------------------------------------- rendering

class Site:
    def __init__(self, cfg: dict, reports: list[Report]):
        self.cfg = cfg
        self.reports = reports
        self.by_id = {r.id: r for r in reports}
        days: dict[str, list[Report]] = {}
        for r in reports:
            days.setdefault(r.date, []).append(r)
        self.days = dict(sorted(days.items(), reverse=True))  # newest first
        self.css = (ROOT / "assets" / "base.css").read_text(encoding="utf-8") + "\n" + \
                   (ROOT / "assets" / "extra.css").read_text(encoding="utf-8") + ADHD_CSS
        self.base_path = s(cfg.get("base_path")).rstrip("/")
        self.base_url = s(cfg.get("base_url")).rstrip("/")

    # urls
    def u(self, path: str) -> str:
        return self.base_path + path

    def abs(self, path: str) -> str:
        return self.base_url + self.base_path + path if self.base_url else ""

    @staticmethod
    def report_path(rid: str) -> str:
        return f"/reports/{rid}/"

    @staticmethod
    def day_path(date: str) -> str:
        return f"/days/{date}/"

    # ADHD-friendly helpers
    @staticmethod
    def capped(items: list[str], open_tag: str, close_tag: str, more_open: str | None = None) -> str:
        """Render a list showing at most LIST_CAP items (existing order kept); the rest go inside
        <details> so nothing is dropped. more_open overrides the opening tag of the hidden part."""
        html_ = open_tag + "".join(items[:LIST_CAP]) + close_tag
        rest = items[LIST_CAP:]
        if rest:
            html_ += (f'<details class="more"><summary>顯示其餘 {len(rest)} 項</summary>'
                      f'{more_open or open_tag}{"".join(rest)}{close_tag}</details>')
        return html_

    @staticmethod
    def issue_anchors(r: Report) -> dict[str, str]:
        """issue_id -> section anchor, computed exactly as issue_item() assigns them."""
        used: set = set()
        out: dict[str, str] = {}
        for it in r.issues + r.early_leads:
            a = "i-" + slug(s(it.get("issue_id")))
            while a in used:
                a += "-x"
            used.add(a)
            out.setdefault(s(it.get("issue_id")), a)
        return out

    @staticmethod
    def first_sentence(v) -> str:
        ps = paras(v)
        if not ps:
            return ""
        m = re.match(r"^(.+?[。！？!?])", ps[0])
        return m.group(1) if m else ps[0]

    def key_points(self, r: Report, href_prefix: str = "") -> str:
        """<ol> of the 1-3 most important issues (existing ranking), one sentence each, linked."""
        pool = [(it, False) for it in r.issues] or [(it, True) for it in r.early_leads]
        if not pool:
            return ""
        anchors = self.issue_anchors(r)
        lis = []
        for it, lead in pool[:MAX_KEY]:
            lab, cls = STATUS["lead"] if lead and not s(it.get("status")) else status_of(it.get("status"))
            sent = self.first_sentence(it.get("why")) or self.first_sentence(it.get("seen"))
            href = href_prefix + "#" + anchors.get(s(it.get("issue_id")), "")
            lis.append(f'<li>{tag(lab, cls)}<a href="{e(href)}">{e(s(it.get("name")))}</a>'
                       f'{"：" + e(sent) if sent else ""}</li>')
        return '<ol class="keypts">' + "".join(lis) + "</ol>"

    def diff_rows(self, r: Report, prev: Report | None) -> list[tuple[str, str]]:
        """同上一期比較 from issue_id / status / placement already in the data. [] if no prior edition."""
        if prev is None:
            return []
        cur_main = {s(it.get("issue_id")): it for it in r.issues}
        cur_lead = {s(it.get("issue_id")): it for it in r.early_leads}
        prev_main = {s(it.get("issue_id")): it for it in prev.issues}
        prev_lead = {s(it.get("issue_id")): it for it in prev.early_leads}
        prev_track = {s(t.get("issue_id")): t for t in prev.tracking if s(t.get("issue_id"))}
        cur_track = {s(t.get("issue_id")): t for t in r.tracking if s(t.get("issue_id"))}
        here = self.issue_anchors(r)
        there = self.issue_anchors(prev)
        prev_url = self.u(self.report_path(prev.id))

        def link(iid: str) -> str:
            src = cur_main.get(iid) or cur_lead.get(iid) or prev_main.get(iid) or prev_lead.get(iid) \
                or cur_track.get(iid) or prev_track.get(iid) or {}
            name = e(s(src.get("name")) or iid)
            if iid in here:
                return f'<a href="#{e(here[iid])}">{name}</a>'
            if iid in there:
                return f'<a href="{e(prev_url + "#" + there[iid])}">{name}</a>（上一期）'
            return name

        new, up, shift, cool, cont = [], [], [], [], []
        for iid, it in list(cur_main.items()) + list(cur_lead.items()):
            st = STATUS_BY_LABEL.get(s(it.get("status")), s(it.get("status")))
            if iid not in prev_main and iid not in prev_lead and iid not in prev_track:
                new.append(iid)
            elif st == "cooling":
                cool.append(iid)
            elif iid in cur_main and iid not in prev_main:
                up.append(iid)
            elif iid in cur_main and st == "shift":
                shift.append(iid)
            elif iid in cur_main:
                cont.append(iid)
        for iid in prev_main:  # left the main list (now early lead, tracking only, or absent)
            if iid not in cur_main and iid not in cool:
                cool.append(iid)
        for iid, t in cur_track.items():
            if s(t.get("kind")) in ("cooling", "resolved") and iid not in cool and iid not in cur_main:
                cool.append(iid)

        def cell(lst):
            return "、".join(link(i) for i in lst) if lst else '<span style="color:var(--muted)">無</span>'
        rows = [("新出現", cell(new)), ("升級為主要議題", cell(up)), ("降溫／移出主要議題", cell(cool))]
        if shift:
            rows.append(("觀點變化", cell(shift)))
        rows.append(("持續追蹤", f"{len(cont)} 項" if cont else '<span style="color:var(--muted)">無</span>'))
        return rows

    # chrome
    def logo(self) -> str:
        return ('<svg class="logo" viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="7" '
                'fill="currentColor"/><text x="16" y="21" text-anchor="middle" '
                'font-family="Geist Mono,ui-monospace,monospace" font-size="13" font-weight="700" '
                f'fill="var(--bg)">{e(self.cfg.get("logo_text", "HK"))}</text></svg>')

    def page(self, *, title, desc, path, main, body_class="", nav_current=False,
             noindex=False, ld=None, og_type="website", extra_head="") -> str:
        c = self.cfg
        canon = self.abs(path)
        head = [
            '<!DOCTYPE html>\n<html lang="zh-Hant-HK">\n<head>\n<meta charset="utf-8"/>\n',
            '<meta name="viewport" content="width=device-width, initial-scale=1"/>\n',
            f"<title>{e(title)}</title>\n",
            f'<meta name="description" content="{e(desc)}"/>\n',
        ]
        if canon:
            head.append(f'<link rel="canonical" href="{e(canon)}"/>\n')
        head.append('<meta name="robots" content="noindex,nofollow"/>\n' if noindex else
                    '<meta name="robots" content="index,follow"/>\n')
        head += [
            '<meta name="theme-color" content="#ffffff" media="(prefers-color-scheme: light)"/>\n',
            '<meta name="theme-color" content="#0a0a0a" media="(prefers-color-scheme: dark)"/>\n',
            f'<link rel="icon" href="{e(self.u("/favicon.svg"))}" type="image/svg+xml"/>\n',
            f'<link rel="sitemap" type="application/xml" href="{e(self.u("/sitemap.xml"))}"/>\n',
            extra_head,
            f'<meta property="og:type" content="{og_type}"/>\n',
            '<meta property="og:locale" content="zh_HK"/>\n',
            f'<meta property="og:site_name" content="{e(c["site_title"])}"/>\n',
            f'<meta property="og:title" content="{e(title)}"/>\n',
            f'<meta property="og:description" content="{e(desc)}"/>\n',
        ]
        if canon:
            head.append(f'<meta property="og:url" content="{e(canon)}"/>\n')
        if self.base_url:
            img = self.abs("/og.jpg")
            banner = self.abs("/x-banner.jpg")
            head += [
                f'<meta property="og:image" content="{e(img)}"/>\n',
                '<meta property="og:image:width" content="1200"/>\n',
                '<meta property="og:image:height" content="630"/>\n',
                f'<meta property="x:game:image" content="{e(banner)}"/>\n',
                '<meta name="twitter:card" content="summary_large_image"/>\n',
                f'<meta name="twitter:image" content="{e(img)}"/>\n',
            ]
        else:
            head.append('<meta name="twitter:card" content="summary"/>\n')
        head += [
            '<link rel="preconnect" href="https://fonts.googleapis.com"/>\n',
            '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>\n',
            '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700'
            '&amp;family=Geist+Mono:wght@400;500&amp;display=swap"/>\n',
        ]
        if ld and self.base_url:
            head.append(json_ld(ld))
        if self.cfg.get("inline_css"):
            head.append(f"<style>\n{self.css}</style>\n</head>\n")
        else:  # one cacheable file; hourly pushes then only touch changed pages
            head.append(f'<link rel="stylesheet" href="{e(self.u("/assets/site.css"))}"/>\n</head>\n')
        cur = ' aria-current="page"' if nav_current else ""
        body = (
            f'<body{(" class=" + chr(34) + body_class + chr(34)) if body_class else ""}>\n'
            '  <a class="skip" href="#main">跳到主要內容</a>\n'
            '  <header class="top"><div class="wrap">\n'
            f'    <a class="brand" href="{e(self.u("/"))}">{self.logo()}<span>{e(c["site_title"])}</span>'
            f'<small>{e(c.get("site_subtitle", ""))}</small></a>\n'
            f'    <nav aria-label="主要導覽"><a href="{e(self.u("/#latest"))}"{cur}>最新</a>'
            f'<a href="{e(self.u("/#archive"))}">按日存檔</a>'
            f'<a href="{e(self.u("/tracker/"))}"><span class="hide-sm">Threads </span>追蹤</a></nav>\n'
            '  </div></header>\n'
            f'  <main id="main">\n{main}  </main>\n'
            f'{self.footer()}</body>\n</html>\n'
        )
        return "".join(head) + body

    def footer(self) -> str:
        lines = "".join(f'    <p class="line">{e(t)}</p>\n' for t in self.cfg.get("footer_lines", []))
        disc = self.cfg.get("footer_disclaimer")
        if disc:
            lines += f'    <p class="line disc">{e(disc)}</p>\n'
        return f'  <footer class="site"><div class="wrap">\n{lines}  </div></footer>\n'

    # shared pieces
    def card(self, r: Report) -> str:
        en, zh = weekday(r.date)
        heads = r.heads()
        if heads:
            lis = "".join(f"<li>{tag(lab, cls)}{e(name)}</li>" for name, lab, cls in heads)
        else:
            lis = '<li class="bot">本輪未有達門檻的議題</li>'
        fx = "<span>FIXTURE · 示例資料</span>" if r.mode == "fixture" else ""
        return (
            '      <li class="card">\n'
            f'        <div class="when"><time datetime="{e(r.start.strftime("%Y-%m-%dT%H:%M:%SZ"))}">{e(r.when)}</time>'
            f'<span>{en} · {zh} · HKT</span>{fx}</div>\n'
            '        <div>\n'
            f'          <h3><a href="{e(self.u(self.report_path(r.id)))}">{e(r.title)}</a></h3>\n'
            f'          <ul class="heads">{lis}</ul>\n'
            '        </div>\n'
            '        <span class="arrow" aria-hidden="true">→</span>\n'
            '      </li>\n'
        )

    def day_grid(self) -> str:
        if not self.days:
            return '    <p class="empty">尚未有存檔。</p>\n'
        items = []
        for date, rs in self.days.items():
            en, zh = weekday(date)
            items.append(f'      <li class="month"><span class="label">{e(date)} · {en}</span>'
                         f'<a href="{e(self.u(self.day_path(date)))}">{e(zh_date(date))}（{len(rs)} 份）</a></li>\n')
        return '    ' + self.capped(items, '<ul class="months">\n', '    </ul>\n') + '\n'

    # pages
    def home(self) -> str:
        c = self.cfg
        n = int(c.get("latest_count", 24))
        latest = self.reports[:n]
        chips = []
        if self.reports:
            chips.append(f'<span class="chip dark">最新 {e(self.reports[0].when)} HKT</span>')
        else:
            chips.append('<span class="chip dark">尚未有快報</span>')
        chips.append(f'<span class="chip">{len(self.reports)} 份快報</span>')
        chips.append('<span class="chip">zh-Hant-HK</span>')
        if any(r.mode == "fixture" for r in self.reports):
            chips.append('<span class="chip dashed">含示例資料</span>')
        cards = [self.card(r) for r in latest]
        listing = ("    " + self.capped(cards, '<ul class="days">\n', '    </ul>\n') + "\n" if cards
                   else '    <p class="empty">尚未有快報。</p>\n')
        top = ""
        if self.reports:
            r0 = self.reports[0]
            kp = self.key_points(r0, self.u(self.report_path(r0.id)))
            if kp:
                top = ('  <section class="hl-top" aria-labelledby="h-key"><div class="wrap">\n'
                       f'    <h2 id="h-key" class="label">重點｜{e(r0.when)} HKT</h2>\n'
                       f'    {kp}\n'
                       f'    <a class="go" href="{e(self.u(self.report_path(r0.id)))}">閱讀 {e(r0.hour)}:00 快報全文 →</a>\n'
                       '  </div></section>\n')
        main = (
            top +
            '  <section class="hero" aria-labelledby="t"><div class="wrap">\n'
            f'    <p class="label">{e(c.get("hero_label", ""))}</p>\n'
            f'    <h1 id="t">{e(c["site_title"])}</h1>\n'
            f'    <p class="lede">{e(c.get("hero_lede", ""))}</p>\n'
            f'    <div class="meta-row">{"".join(chips)}</div>\n'
            '  </div></section>\n'
            '  <section class="section" id="latest" aria-labelledby="h-latest"><div class="wrap">\n'
            f'    <div class="sec-head"><h2 id="h-latest">最新{e(c.get("report_name", "每小時議題快報"))}</h2>'
            f'<span class="label">Latest {n}</span></div>\n'
            f'{listing}'
            '  </div></section>\n'
            '  <section class="section" id="archive" aria-labelledby="h-archive"><div class="wrap">\n'
            '    <div class="sec-head"><h2 id="h-archive">按日存檔</h2><span class="label">Archive</span></div>\n'
            f'{self.day_grid()}'
            '  </div></section>\n'
        )
        ld = {"@context": "https://schema.org", "@graph": [
            {"@type": "WebSite", "@id": self.abs("/") + "#website", "url": self.abs("/"),
             "name": c["site_title"], "alternateName": c.get("site_subtitle", ""), "inLanguage": "zh-Hant-HK"},
            {"@type": "CollectionPage", "url": self.abs("/"), "name": c["site_title"], "inLanguage": "zh-Hant-HK",
             "mainEntity": {"@type": "ItemList", "numberOfItems": len(latest), "itemListElement": [
                 {"@type": "ListItem", "position": i + 1, "url": self.abs(self.report_path(r.id)), "name": r.title}
                 for i, r in enumerate(latest)]}},
        ]}
        title = f'{c["site_title"]}｜{c.get("report_name", "每小時議題快報")}（{c.get("site_subtitle", "")}）'
        return self.page(title=title, desc=c.get("hero_lede", ""), path="/", main=main,
                         nav_current=True, ld=ld)

    def fields(self, rows: list[tuple[str, str]], cls: str = "") -> str:
        body = "".join(f"      <div><dt>{e(k)}</dt><dd>{v}</dd></div>\n" for k, v in rows)
        return f"      <dl class=\"fields{(' ' + cls) if cls else ''}\">\n{body}      </dl>\n"

    @classmethod
    def dash_list(cls, items: list[str]) -> str:
        return cls.capped([f"<li>{x}</li>" for x in items], "<ul>", "</ul>")

    def info_rows(self, r: Report) -> list[tuple[str, str]]:
        src = r.sources
        readable = []
        for x in src.get("readable") or []:
            if isinstance(x, dict):
                t = e(s(x.get("name")))
                bits = []
                if s(x.get("platform")):
                    bits.append(e(s(x.get("platform"))))
                if x.get("items") is not None:
                    bits.append(f"{e(num(x.get('items')))} 項")
                if s(x.get("note")):
                    bits.append(e(s(x.get("note"))))
                readable.append(t + (f'<span class="mono" style="color:var(--muted)">（{" · ".join(bits)}）</span>'
                                     if bits else ""))
            else:
                readable.append(e(s(x)))
        failed = []
        for x in src.get("failed") or []:
            if isinstance(x, dict):
                failed.append(f"{e(s(x.get('name')))}：{e(s(x.get('reason')) or '原因不詳')}")
            else:
                failed.append(e(s(x)))
        failed += [f"缺口：{e(g)}" for g in paras(src.get("gaps"))]
        mode = ("<span class=\"mono\">fixture</span>（示例資料，非真實收集）" if r.mode == "fixture"
                else "<span class=\"mono\">live</span>（實際收集）")
        rows = [
            ("觀察窗口", f'<span class="mono">{e(fmt_window(r.start, r.end))}</span>'),
            ("生成時間", f'<span class="mono">{e(fmt_hkt(r.generated))}</span>'),
            ("模式", mode),
            ("實際可讀來源", self.dash_list(readable) if readable else "（未有記錄）"),
            ("來源失敗／缺口", self.dash_list(failed) if failed else "（未有記錄）"),
        ]
        if paras(r.data.get("summary")):
            rows.insert(0, ("本輪摘要", "".join(f"{e(p)}<br/>" for p in paras(r.data.get("summary")))[:-5]))
        return rows

    def field(self, label: str, inner: str) -> str:
        return f'          <div class="field"><h4 class="label">{e(label)}</h4>{inner}</div>\n'

    @staticmethod
    def ps(v) -> str:
        return "".join(f"<p>{e(p)}</p>" for p in paras(v))

    @staticmethod
    def refs(ids) -> str:
        ids = [s(i) for i in (ids or []) if s(i)] if isinstance(ids, list) else ([s(ids)] if s(ids) else [])
        return f' <span class="dt-k">[{e(", ".join(ids))}]</span>' if ids else ""

    def issue_item(self, r: Report, it: dict, idx: int, lead: bool, used_ids: set) -> str:
        iid = s(it.get("issue_id"))
        anchor = "i-" + slug(iid)
        while anchor in used_ids:
            anchor += "-x"
        used_ids.add(anchor)
        lab, cls = STATUS["lead"] if lead and not s(it.get("status")) else status_of(it.get("status"))
        obs = it.get("observed") or {}
        o_a = opt_ts(obs.get("start"), "observed.start") or r.start
        o_b = opt_ts(obs.get("end"), "observed.end") or r.end
        numtxt = f"線索 {idx:02d}" if lead else f"{idx:02d}"
        out = [
            f'      <li class="item" id="{e(anchor)}">\n',
            f'        <span class="num">{numtxt}</span>\n',
            f'        <h3>{e(s(it.get("name")))}</h3>\n',
            f'        <p class="meta-line">{tag(lab, cls)}{tag("早期線索", "s-lead") if lead and lab != "早期線索" else ""}'
            f'<span>議題 ID <b>{e(iid)}</b></span><span>觀察時段 <b>{e(fmt_window(o_a, o_b))}</b></span></p>\n',
        ]
        seen = self.ps(it.get("seen"))
        out.append(self.field("今輪看到甚麼", seen or "<p>（未有記錄）</p>"))
        vps = []
        for v in it.get("viewpoints") or []:
            if isinstance(v, dict):
                share = f'<span class="share">{e(s(v.get("share")))}</span>' if s(v.get("share")) else ""
                who = f'<span class="who">{e(s(v.get("label")))}</span>' if s(v.get("label")) else ""
                summ = e(s(v.get("summary")))
                vps.append(f"<li>{share}{who}{'：' if who and summ else ''}{summ}{self.refs(v.get('evidence_ids'))}</li>")
            elif s(v):
                vps.append(f"<li>{e(s(v))}</li>")
        out.append(self.field("觀點分布", self.capped(vps, '<ul class="dash vp">', "</ul>") if vps else "<p>（未有足夠材料判斷）</p>"))
        data = []
        for dpt in it.get("data") or []:
            if isinstance(dpt, dict):
                k = f'<span class="dt-k">{e(s(dpt.get("metric")))}</span>' if s(dpt.get("metric")) else ""
                cmp_ = f"（{e(s(dpt.get('comparison')))}）" if s(dpt.get("comparison")) else ""
                data.append(f"<li>{k}{e(num(dpt.get('value')))}{cmp_}{self.refs(dpt.get('evidence_ids'))}</li>")
            elif s(dpt):
                data.append(f"<li>{e(s(dpt))}</li>")
        out.append(self.field("數據與比較", self.capped(data, '<ul class="dash">', "</ul>") if data else "<p>（無可比較數據）</p>"))
        out.append(self.field("為甚麼列入", self.ps(it.get("why")) or "<p>（未有記錄）</p>"))
        ver = it.get("verification") or {}
        if not isinstance(ver, dict):
            ver = {"status": ver}
        vkey = s(ver.get("status"))
        vtxt = ""
        if vkey or s(ver.get("note")):
            vtxt = (f'<p class="verify">{tag(VERIFY.get(vkey, vkey or "未標示"))}'
                    f'{e(s(ver.get("note")))}</p>')
        evs = []
        for ev in it.get("evidence") or []:
            meta = []
            if s(ev.get("platform")):
                meta.append(f'<span class="plat">{e(s(ev.get("platform")))}</span>')
            pub = opt_ts(ev.get("published_at"), "published_at")
            obs_t = opt_ts(ev.get("observed_at"), "observed_at")
            meta.append(f"<span>發布 {e(fmt_hkt(pub)) if pub else '時間不詳'}</span>")
            if obs_t:
                meta.append(f"<span>觀測 {e(fmt_hkt(obs_t))}</span>")
            rl = s(ev.get("read_level"))
            meta.append(f"<span>讀取：{e(READ_LEVEL.get(rl, rl or '未標示'))}</span>")
            note = f'<div class="note">{e(s(ev.get("note")))}</div>' if s(ev.get("note")) else ""
            evs.append(f'<li><div class="row1"><span class="id">{e(s(ev.get("evidence_id")))}</span>'
                       f'{ext_link(ev.get("url"))}</div><div class="m">{"".join(meta)}</div>{note}</li>')
        evhtml = self.capped(evs, '<ol class="ev">', "</ol>", f'<ol class="ev" start="{LIST_CAP + 1}">') if evs else "<p>（未附證據）</p>"
        out.append(self.field("證據與核實狀態", vtxt + evhtml))
        lim = []
        for k, lab2 in (("limits", "限制"), ("next_steps", "下一步")):
            for i, p in enumerate(paras(it.get(k))):
                lim.append(f'<p>{f"<span class={chr(34)}dt-k{chr(34)}>{lab2}</span>" if i == 0 else ""}{e(p)}</p>')
        out.append(self.field("限制及下一步", "".join(lim) or "<p>（未有記錄）</p>"))
        out.append("      </li>\n")
        return "".join(out)

    def tracking_items(self, r: Report) -> str:
        if not r.tracking:
            return '      <p class="empty">本輪沒有持續追蹤或更正項目。</p>\n'
        lis = []
        for i, t in enumerate(r.tracking, 1):
            kind = s(t.get("kind"))
            rel = s(t.get("related_report"))
            rel_html = ""
            if rel:
                if rel in self.by_id:
                    rel_html = f'<span>相關快報 <a href="{e(self.u(self.report_path(rel)))}">{e(rel)}</a></span>'
                else:
                    rel_html = f"<span>相關快報 <b>{e(rel)}</b>（未在本站）</span>"
            iid = f"<span>議題 ID <b>{e(s(t.get('issue_id')))}</b></span>" if s(t.get("issue_id")) else ""
            lis.append(
                '      <li class="item track">\n'
                f'        <span class="num">T{i:02d}</span>\n'
                f'        <h3>{e(s(t.get("name")) or s(t.get("issue_id")) or "（未命名）")}</h3>\n'
                f'        <p class="meta-line">{tag(TRACK_KIND.get(kind, kind or "追蹤"), "s-new" if kind == "correction" else "")}{iid}{rel_html}</p>\n'
                f'        {self.ps(t.get("text"))}\n'
                '      </li>\n')
        return '      ' + self.capped(lis, '<ol class="items">\n', '      </ol>',
                                   f'<ol class="items" start="{LIST_CAP + 1}">\n') + '\n'

    def usage_rows(self, r: Report) -> list[tuple[str, str]]:
        u = r.usage
        def fmt(k, v):
            if k == "cost_usd" and isinstance(v, (int, float)) and not isinstance(v, bool):
                return f"{v:,.4f}"
            return num(v)
        rows = [(lab, f'<span class="mono">{e(fmt(k, u[k]))}</span>' if u[k] is not None
                 else '<span style="color:var(--muted)">未計量</span>') for k, lab in USAGE_FIELDS if k in u]
        extra = u.get("extra") or {}
        if isinstance(extra, dict):
            rows += [(s(k), e(num(v))) for k, v in extra.items()]
        if paras(u.get("notes")):
            rows.append(("備註", "<br/>".join(e(p) for p in paras(u.get("notes")))))
        return rows

    def pager(self, prev_html: str, mid_html: str, next_html: str, label: str) -> str:
        return (f'    <nav class="pager" aria-label="{e(label)}">\n'
                f'      {prev_html}\n      {mid_html}\n      {next_html}\n    </nav>\n')

    @staticmethod
    def pg(href, cls, l, v, rel="") -> str:
        if href is None:
            return (f'<span class="{cls} off" aria-disabled="true"><span class="l">{e(l)}</span>'
                    f'<span class="v">{e(v)}</span></span>')
        r = f' rel="{rel}"' if rel else ""
        return f'<a class="{cls}" href="{e(href)}"{r}><span class="l">{e(l)}</span><span class="v">{e(v)}</span></a>'

    def report_page(self, r: Report) -> str:
        c = self.cfg
        i = self.reports.index(r)
        newer = self.reports[i - 1] if i > 0 else None
        older = self.reports[i + 1] if i + 1 < len(self.reports) else None
        en, zh = weekday(r.date)
        chips = [f'<span class="chip dark"><time datetime="{e(r.start.strftime("%Y-%m-%dT%H:%M:%SZ"))}">'
                 f'{e(r.when)} HKT</time></span>',
                 f'<span class="chip">{en} · {zh}</span>',
                 f'<span class="chip">{len(r.issues)} 個議題</span>']
        if r.early_leads:
            chips.append(f'<span class="chip">{len(r.early_leads)} 條早期線索</span>')
        chips.append(f'<span class="chip{" dashed" if r.mode == "fixture" else ""}">'
                     f'{"FIXTURE · 示例資料" if r.mode == "fixture" else "LIVE"}</span>')
        used: set = set()
        parts = []
        if r.mode == "fixture":
            parts.append('    <p class="notice"><strong>示例資料（fixture）</strong>：本頁內容全屬虛構，'
                         '只用於預覽版面；所有連結指向 example.com，並非真實來源。</p>\n')
        kp = self.key_points(r)
        if kp:
            parts.append('    <section class="group" aria-labelledby="g-key">\n'
                         '      <h2 id="g-key" class="label">重點</h2>\n'
                         f'      {kp}\n    </section>\n')
        drows = self.diff_rows(r, older)
        if drows:
            parts.append('    <section class="group" aria-labelledby="g-diff">\n'
                         f'      <h2 id="g-diff" class="label">同上一期比較（對比 {e(older.hour)}:00）</h2>\n'
                         f'{self.fields(drows, "diff")}    </section>\n')
        parts.append('    <section class="group" aria-labelledby="g-info">\n'
                     '      <h2 id="g-info" class="label">報告資訊</h2>\n'
                     f'{self.fields(self.info_rows(r))}    </section>\n')
        if r.issues:
            items = "".join(self.issue_item(r, it, n, False, used) for n, it in enumerate(r.issues, 1))
            body = f'      <ol class="items">\n{items}      </ol>\n'
        else:
            body = '      <p class="empty">本輪沒有達到列入門檻的議題。</p>\n'
        parts.append('    <section class="group" aria-labelledby="g-issues">\n'
                     f'      <h2 id="g-issues" class="label">主要議題（{len(r.issues)}／{MAX_ISSUES}）</h2>\n'
                     f'{body}    </section>\n')
        if r.early_leads:
            items = "".join(self.issue_item(r, it, n, True, used) for n, it in enumerate(r.early_leads, 1))
            parts.append('    <section class="group" aria-labelledby="g-leads">\n'
                         f'      <h2 id="g-leads" class="label">早期線索（{len(r.early_leads)}／{MAX_LEADS}）</h2>\n'
                         f'      <ol class="items">\n{items}      </ol>\n    </section>\n')
        parts.append('    <section class="group" aria-labelledby="g-track">\n'
                     '      <h2 id="g-track" class="label">持續追蹤與更正</h2>\n'
                     f'{self.tracking_items(r)}    </section>\n')
        urows = self.usage_rows(r)
        parts.append('    <section class="group" aria-labelledby="g-usage">\n'
                     '      <h2 id="g-usage" class="label">用量</h2>\n'
                     + (self.fields(urows, "grid2") if urows else '      <p class="empty">未有用量記錄。</p>\n')
                     + '    </section>\n')
        parts.append(f'    <aside class="disclaimer" aria-label="聲明"><span class="label">聲明</span>{e(DISCLAIMER)}</aside>\n')
        parts.append(self.pager(
            self.pg(self.u(self.report_path(older.id)) if older else None, "prev", "← 上一份快報",
                    f"{older.when} HKT" if older else "已是最早", "prev"),
            self.pg(self.u(self.day_path(r.date)), "mid", "當日存檔", zh_date(r.date)),
            self.pg(self.u(self.report_path(newer.id)) if newer else None, "next", "下一份快報 →",
                    f"{newer.when} HKT" if newer else "已是最新", "next"),
            "快報導覽"))
        main = (
            '  <section class="hero" aria-labelledby="t"><div class="wrap">\n'
            f'    <nav aria-label="麵包屑"><ol class="crumbs"><li><a href="{e(self.u("/"))}">{e(c["site_title"])}</a></li>'
            f'<li><a href="{e(self.u(self.day_path(r.date)))}">{e(r.date)}</a></li>'
            f'<li aria-current="page">{e(r.hour)}:00</li></ol></nav>\n'
            f'    <p class="label" style="margin-top:20px">【{e(c.get("report_name", "每小時議題快報"))}｜{e(zh_date(r.date))} {e(r.hour)}:00 HKT】</p>\n'
            f'    <h1 id="t">{e(zh_date(r.date))} {e(r.hour)}:00</h1>\n'
            f'    <div class="meta-row">{"".join(chips)}</div>\n'
            '  </div></section>\n'
            f'  <article class="section" aria-label="{e(r.title)}內容"><div class="wrap"><div class="article">\n'
            + "".join(parts) +
            '  </div></div></article>\n'
        )
        heads = [h[0] for h in r.heads()]
        desc = f"【{c.get('report_name', '每小時議題快報')}｜{zh_date(r.date)} {r.hour}:00 HKT】" + \
               (" · ".join(heads) if heads else "本輪未有達門檻的議題") + "。"
        cites = []
        for it in r.issues + r.early_leads:
            for ev in it.get("evidence") or []:
                u_ = safe_url(ev.get("url"))
                if u_ and u_ not in cites:
                    cites.append(u_)
        ld = {"@context": "https://schema.org", "@graph": [
            {"@type": "Report", "@id": self.abs(self.report_path(r.id)) + "#report",
             "mainEntityOfPage": self.abs(self.report_path(r.id)), "headline": r.title, "description": desc,
             "inLanguage": "zh-Hant-HK", "datePublished": r.generated.strftime("%Y-%m-%dT%H:%M:%SZ"),
             "temporalCoverage": f"{r.start:%Y-%m-%dT%H:%M:%SZ}/{r.end:%Y-%m-%dT%H:%M:%SZ}",
             "isPartOf": {"@id": self.abs("/") + "#website"}, "citation": cites},
            {"@type": "BreadcrumbList", "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": c["site_title"], "item": self.abs("/")},
                {"@type": "ListItem", "position": 2, "name": zh_date(r.date), "item": self.abs(self.day_path(r.date))},
                {"@type": "ListItem", "position": 3, "name": f"{r.hour}:00", "item": self.abs(self.report_path(r.id))},
            ]},
        ]}
        extra = ""
        if older and self.base_url:
            extra += f'<link rel="prev" href="{e(self.abs(self.report_path(older.id)))}"/>\n'
        if newer and self.base_url:
            extra += f'<link rel="next" href="{e(self.abs(self.report_path(newer.id)))}"/>\n'
        extra += f'<meta property="article:published_time" content="{r.generated:%Y-%m-%dT%H:%M:%SZ}"/>\n'
        title = f"{r.title}" + (f"：{heads[0]}" if heads else "") + f"｜{c['site_title']}"
        return self.page(title=title, desc=desc, path=self.report_path(r.id), main=main, body_class="day",
                         noindex=(r.mode == "fixture"), ld=ld, og_type="article", extra_head=extra)

    def day_page(self, date: str) -> str:
        c = self.cfg
        rs = self.days[date]
        dates = list(self.days)
        i = dates.index(date)
        newer = dates[i - 1] if i > 0 else None
        older = dates[i + 1] if i + 1 < len(dates) else None
        en, zh = weekday(date)
        n_issues = sum(len(r.issues) for r in rs)
        main = (
            '  <section class="hero" aria-labelledby="t"><div class="wrap">\n'
            f'    <nav aria-label="麵包屑"><ol class="crumbs"><li><a href="{e(self.u("/"))}">{e(c["site_title"])}</a></li>'
            f'<li><a href="{e(self.u("/#archive"))}">按日存檔</a></li><li aria-current="page">{e(date)}</li></ol></nav>\n'
            f'    <p class="label" style="margin-top:20px">【{e(c.get("report_name", "每小時議題快報"))}｜{e(zh_date(date))}】</p>\n'
            f'    <h1 id="t">{e(zh_date(date))}</h1>\n'
            f'    <div class="meta-row"><span class="chip dark"><time datetime="{e(date)}">{e(date)}</time></span>'
            f'<span class="chip">{en} · {zh}</span><span class="chip">{len(rs)} 份快報</span>'
            f'<span class="chip">{n_issues} 個議題條目</span></div>\n'
            '  </div></section>\n'
            '  <section class="section" id="list" aria-labelledby="h-list"><div class="wrap">\n'
            f'    <div class="sec-head"><h2 id="h-list">當日快報</h2><span class="label">{len(rs)} reports · HKT</span></div>\n'
            '    ' + self.capped([self.card(r) for r in rs], '<ul class="days">\n', '    </ul>\n') + '\n'
            + self.pager(
                self.pg(self.u(self.day_path(older)) if older else None, "prev", "← 上一日",
                        zh_date(older) if older else "已是最早", "prev"),
                self.pg(self.u("/#archive"), "mid", "全部存檔", "按日存檔"),
                self.pg(self.u(self.day_path(newer)) if newer else None, "next", "下一日 →",
                        zh_date(newer) if newer else "已是最新", "next"),
                "日期導覽") +
            '  </div></section>\n'
        )
        all_fx = all(r.mode == "fixture" for r in rs)
        return self.page(title=f"{zh_date(date)} {c.get('report_name', '每小時議題快報')}存檔｜{c['site_title']}",
                         desc=f"{zh_date(date)}（{zh}）共 {len(rs)} 份{c.get('report_name', '每小時議題快報')}。",
                         path=self.day_path(date), main=main, noindex=all_fx)

    def not_found(self) -> str:
        main = ('  <section class="hero" aria-labelledby="t"><div class="wrap">\n'
                '    <p class="label">404</p>\n    <h1 id="t">找不到頁面</h1>\n'
                f'    <p class="lede">此頁不存在或已移除。<a href="{e(self.u("/"))}">返回首頁</a></p>\n'
                '  </div></section>\n')
        return self.page(title=f"找不到頁面｜{self.cfg['site_title']}", desc="找不到頁面", path="/404.html",
                         main=main, noindex=True)

    def favicon(self) -> str:
        t = e(self.cfg.get("logo_text", "HK"))
        return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
                '<style>rect{fill:#0a0a0a}text{fill:#fff}@media (prefers-color-scheme:dark)'
                '{rect{fill:#ededed}text{fill:#0a0a0a}}</style>'
                '<rect width="32" height="32" rx="7"/><text x="16" y="21" text-anchor="middle" '
                'font-family="Geist Mono,ui-monospace,Menlo,monospace" font-size="13" font-weight="700">'
                f'{t}</text></svg>\n')

    def sitemap(self) -> str:
        if not self.base_url:
            return None
        urls = []
        live = [r for r in self.reports if r.mode != "fixture"]
        urls.append((self.abs("/"), max((r.generated for r in live), default=None)))
        for date, rs in self.days.items():
            lv = [r for r in rs if r.mode != "fixture"]
            if lv:
                urls.append((self.abs(self.day_path(date)), max(r.generated for r in lv)))
        for r in live:
            urls.append((self.abs(self.report_path(r.id)), r.generated))
        body = "".join(
            f"  <url><loc>{e(u)}</loc>" + (f"<lastmod>{lm:%Y-%m-%dT%H:%M:%SZ}</lastmod>" if lm else "") + "</url>\n"
            for u, lm in urls)
        return ('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + body + "</urlset>\n")


# --------------------------------------------------------------------------- main

def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", default=str(ROOT / "data" / "reports"))
    ap.add_argument("--out", default=str(ROOT / "public"))
    ap.add_argument("--config", default=str(ROOT / "config.json"))
    ap.add_argument("--strict", action="store_true", help="abort on any invalid report file")
    a = ap.parse_args(argv)

    cfg = json.loads(Path(a.config).read_text(encoding="utf-8"))
    for k in ("site_title",):
        if not s(cfg.get(k)):
            print(f"config: {k} is required", file=sys.stderr)
            return 1
    data_dir = Path(a.data)
    if not data_dir.is_dir():
        print(f"data dir not found: {data_dir}", file=sys.stderr)
        return 1
    reports, bad = load_reports(data_dir, a.strict)
    site = Site(cfg, reports)

    out = Path(a.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".build-", dir=out.parent))
    try:
        write(tmp / "index.html", site.home())
        write(tmp / "404.html", site.not_found())
        write(tmp / "favicon.svg", site.favicon())
        write(tmp / ".nojekyll", "")  # GitHub Pages: serve files as-is
        if not cfg.get("inline_css"):
            write(tmp / "assets" / "site.css", site.css)
        sm = site.sitemap()
        if sm:
            write(tmp / "sitemap.xml", sm)
        if sm and not site.base_path:  # robots.txt is only honoured at the host root
            write(tmp / "robots.txt", f"User-agent: *\nAllow: /\nSitemap: {site.abs('/sitemap.xml')}\n")
        for r in reports:
            write(tmp / "reports" / r.id / "index.html", site.report_page(r))
        for date in site.days:
            write(tmp / "days" / date / "index.html", site.day_page(date))
        os.chmod(tmp, 0o755)
        old = None
        if out.exists():
            old = out.with_name(f".old-{out.name}-{os.getpid()}")
            out.rename(old)
        tmp.rename(out)
        if old:
            shutil.rmtree(old, ignore_errors=True)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    print(f"built {len(reports)} report(s), {len(site.days)} day page(s) -> {out}"
          + (f"; {bad} file(s) skipped" if bad else ""))
    return 2 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
