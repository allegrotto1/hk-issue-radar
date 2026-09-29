#!/usr/bin/env python3
"""Threads 帖文互動追蹤 helper — writes tracker/data.json next to this file.

  python3 track.py add  <url> --summary "..." [--tag 外勞入侵] [--group grad-labour] [--posted-rel 23h] [--at ISO]
  python3 track.py snap <url> --likes 2.2K --replies 302 --reposts 78 --shares 193 --views 106K [--at ISO]
  python3 track.py stop <url> [--at ISO]   # 停止追蹤（頁面顯示「已停止追蹤」；fetch_counts 會跳過）
  python3 track.py report
  python3 track.py thin [--keep 24] [--every 6]   # 檔案接近 20KB 時精簡舊快照

Counter values are the display strings exactly as Threads shows them
(e.g. 2.2K, 106K, 1.3M, 3.4萬, 1,234). Omit a flag (or pass "-") when the
counter is not shown -> stored as null. Times default to now in HKT (+08:00).
"""
import argparse, json, os, re, sys
from datetime import datetime, timedelta, timezone

HKT = timezone(timedelta(hours=8))
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data.json")
METRICS = ["likes", "replies", "reposts", "shares", "views"]
LABELS = {"likes": "讚", "replies": "回覆", "reposts": "轉發", "shares": "分享", "views": "瀏覽"}
MULT = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000, "萬": 10_000, "万": 10_000, "億": 100_000_000, "亿": 100_000_000}


# ---------- parsing ----------
def parse_count(raw):
    """'2.2K' -> {'raw':'2.2K','value':2200,'approx':True}; '-'/None -> None."""
    if raw is None:
        return None
    s = str(raw).strip()
    if s in ("", "-", "—", "null", "none"):
        return None
    m = re.fullmatch(r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*([KkMmBb萬万億亿]?)", s)
    if not m:
        raise SystemExit(f"無法解析數字：{raw!r}（例：302、2.2K、106K、1.3M、3.4萬）")
    num, suf = m.group(1).replace(",", ""), m.group(2)
    if suf:
        return {"raw": s, "value": int(round(float(num) * MULT[suf.lower()])), "approx": True}
    return {"raw": s, "value": int(float(num)), "approx": False}


def parse_rel(rel):
    """'23h' / '19小時' / '5m' / '2d' / '1w' -> timedelta."""
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(s|m|min|h|d|w|秒|分鐘|分|小時|時|日|天|週|周)\s*", str(rel))
    if not m:
        raise SystemExit(f"無法解析相對時間：{rel!r}（例：23h、19h、45m、2d、1w）")
    n, u = float(m.group(1)), m.group(2)
    secs = {"s": 1, "秒": 1, "m": 60, "min": 60, "分鐘": 60, "分": 60, "h": 3600, "小時": 3600, "時": 3600,
            "d": 86400, "日": 86400, "天": 86400, "w": 604800, "週": 604800, "周": 604800}[u]
    return timedelta(seconds=n * secs)


def parse_at(at):
    if not at:
        return datetime.now(HKT).replace(second=0, microsecond=0)
    dt = datetime.fromisoformat(at.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=HKT)
    return dt.astimezone(HKT)


def iso(dt):
    return dt.astimezone(HKT).isoformat(timespec="seconds")


def post_id(url):
    m = re.search(r"/post/([A-Za-z0-9_-]+)", url)
    if not m:
        raise SystemExit(f"唔似 Threads 帖文網址：{url}")
    return m.group(1)


def clean_url(url):
    return url.split("?")[0].split("#")[0].rstrip("/")


# ---------- storage ----------
def load():
    if os.path.exists(DATA):
        with open(DATA, encoding="utf-8") as f:
            return json.load(f)
    return {"schema": 1, "title": "Threads 帖文互動追蹤", "timezone": "Asia/Hong_Kong",
            "updated_at": None, "generated_at": None, "posts": []}


def save(d):
    stamps = [s["taken_at"] for p in d["posts"] for s in p["snapshots"]]
    d["updated_at"] = max(stamps, key=lambda t: parse_at(t)) if stamps else None
    d["generated_at"] = iso(datetime.now(HKT).replace(microsecond=0))
    tmp = DATA + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(dumps(d))
    os.replace(tmp, DATA)
    size = os.path.getsize(DATA)
    print(f"已寫入 {DATA}（{size:,} bytes）")
    if size > 16_000:
        print("⚠ data.json 已超過 16KB（連接器約 34KB 會失敗，目標 <20KB）：請跑 `track.py thin`。", file=sys.stderr)


def dumps(d):
    """Readable but compact: one snapshot per line keeps data.json small (connector limit)."""
    j = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":"))
    head = {k: v for k, v in d.items() if k != "posts"}
    out = ["{"] + [f" {j(k)}: {j(v)}," for k, v in head.items()] + [' "posts": [']
    for i, p in enumerate(d["posts"]):
        meta = {k: v for k, v in p.items() if k != "snapshots"}
        out.append("  {")
        out += [f"   {j(k)}: {j(v)}," for k, v in meta.items()]
        out.append('   "snapshots": [')
        out.append(",\n".join("    " + j(s) for s in p["snapshots"]))
        out.append("   ]")
        out.append("  }" + ("," if i < len(d["posts"]) - 1 else ""))
    out += [" ]", "}", ""]
    return "\n".join(x for x in out if x != "")+"\n"


def find(d, url):
    pid = post_id(url)
    for p in d["posts"]:
        if p["id"] == pid:
            return p
    return None


# ---------- commands ----------
def cmd_add(a):
    d = load()
    if find(d, a.url):
        raise SystemExit("呢個帖文已經喺追蹤名單。")
    seen = parse_at(a.at)
    post = {"id": post_id(a.url), "url": clean_url(a.url), "platform": "threads",
            "summary": a.summary, "tag": a.tag or None, "group": a.group or None, "first_seen": iso(seen),
            "estimated_posted_at": None, "snapshots": []}
    if a.posted_rel:
        post["estimated_posted_at"] = {
            "value": iso(seen - parse_rel(a.posted_rel)), "estimate": True,
            "relative_shown": a.posted_rel, "observed_at": iso(seen),
            "note": "由 Threads 顯示嘅相對時間推算（只精確到單位，例如小時），屬估算"}
    d["posts"].append(post)
    save(d)
    print(f"已加入 {post['id']}")


def cmd_snap(a):
    d = load()
    p = find(d, a.url)
    if not p:
        raise SystemExit("未追蹤呢個帖文，請先用 add。")
    snap = {"taken_at": iso(parse_at(a.at))}
    for k in METRICS:
        snap[k] = parse_count(getattr(a, k))
    if any(s["taken_at"] == snap["taken_at"] for s in p["snapshots"]):
        raise SystemExit(f"{p['id']} 已有 {snap['taken_at']} 嘅快照。")
    p["snapshots"].append(snap)
    p["snapshots"].sort(key=lambda s: parse_at(s["taken_at"]))
    save(d)
    print(f"{p['id']} 已加入快照 {snap['taken_at']}（共 {len(p['snapshots'])} 個）")


def view_growth(old, new):
    """Fractional change in views. None when either side is missing or the base is 0."""
    if not old or not new or not old.get("value"):
        return None
    return (new["value"] - old["value"]) / old["value"]


def should_autostop(old, new):
    """10:01 HKT rule: stop when views grew by less than 10% versus the previous snapshot."""
    g = view_growth(old, new)
    return g is not None and g < 0.10


def cmd_stop(a):
    d = load()
    p = find(d, a.url)
    if not p:
        raise SystemExit("未追蹤呢個帖文。")
    when = iso(parse_at(a.at))
    if p.get("stopped_at"):
        print(f"{p['id']} 已經停止追蹤（{p['stopped_at']}）")
        return
    p["stopped_at"] = when
    save(d)
    print(f"{p['id']} 已停止追蹤 {p['stopped_at']}")


def cmd_thin(a):
    """Keep first snapshot, the latest --keep, and one per --every hours before that."""
    d = load()
    removed = 0
    for p in d["posts"]:
        snaps = p["snapshots"]
        if len(snaps) <= a.keep + 1:
            continue
        old, recent = snaps[:-a.keep], snaps[-a.keep:]
        kept, last = [old[0]], parse_at(old[0]["taken_at"])
        for s in old[1:]:
            t = parse_at(s["taken_at"])
            if t - last >= timedelta(hours=a.every):
                kept.append(s); last = t
        removed += len(old) - len(kept)
        p["snapshots"] = kept + recent
    save(d)
    print(f"已精簡，刪除 {removed} 個舊快照（保留首個、最近 {a.keep} 個、之前每 {a.every} 小時一個）")


def w(s):
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in s)


def rj(s, n):
    return " " * max(0, n - w(s)) + s


def lj(s, n):
    return s + " " * max(0, n - w(s))


def fmt_val(c):
    if c is None:
        return "—"
    return ("≈" + c["raw"]) if c["approx"] else f"{c['value']:,}"


def pct(new, old):
    if new is None or old is None or old["value"] in (None, 0):
        return "—"
    v = (new["value"] - old["value"]) / old["value"] * 100
    return ("≈" if new["approx"] or old["approx"] else "") + f"{v:+.1f}%"


def delta(new, old):
    if new is None or old is None:
        return "—"
    v = new["value"] - old["value"]
    return ("≈" if new["approx"] or old["approx"] else "") + f"{v:+,}"


def latest_views(p):
    s = p["snapshots"][-1] if p["snapshots"] else None
    return (s or {}).get("views") and s["views"]["value"] or -1


def cmd_report(a):
    d = load()
    posts = sorted(d["posts"], key=latest_views, reverse=True)
    upd = parse_at(d["updated_at"]).strftime("%Y-%m-%d %H:%M") + " HKT" if d.get("updated_at") else "—"
    print(f"Threads 帖文互動追蹤｜最後快照 {upd}｜{len(posts)} 個帖文（按瀏覽排序）")
    print("≈ = Threads 縮寫數字（K/M/萬）推算，百分比只屬約數")
    for i, p in enumerate(posts, 1):
        snaps = p["snapshots"]
        print()
        print(f"{i}. {p['url']}" + (f"  [{p['tag']}]" if p.get("tag") else ""))
        print(f"   {p['summary']}")
        if not snaps:
            print("   （未有快照）")
            continue
        last, prev, first = snaps[-1], (snaps[-2] if len(snaps) > 1 else None), snaps[0]
        t = parse_at(last["taken_at"]).strftime("%m-%d %H:%M")
        print(f"   快照 {len(snaps)} 個，最新 {t} HKT")
        print("   " + lj("", 6) + rj("最新", 10) + rj("對上一次", 12) + rj("%", 10) + rj("對首次 %", 11))
        for k in METRICS:
            c = last.get(k)
            dp = delta(c, prev.get(k)) if prev else "—"
            pp = pct(c, prev.get(k)) if prev else "—"
            pf = pct(c, first.get(k)) if len(snaps) > 1 else "—"
            print("   " + lj(LABELS[k], 6) + rj(fmt_val(c), 10) + rj(dp, 12) + rj(pp, 10) + rj(pf, 11))
    print("\n計數來自未登入 Threads 公開頁面，每小時讀取一次；樣本由編輯揀選，不具代表性。")


def main():
    ap = argparse.ArgumentParser(description="Threads 帖文互動追蹤 helper")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add", help="加入帖文")
    p.add_argument("url"); p.add_argument("--summary", required=True)
    p.add_argument("--tag"); p.add_argument("--group", help="上層組別 id（見 data.json 嘅 groups）"); p.add_argument("--posted-rel", help="Threads 顯示嘅相對時間，例如 23h")
    p.add_argument("--at", help="首次見到時間（ISO，預設現在 HKT）")
    p.set_defaults(fn=cmd_add)
    p = sub.add_parser("snap", help="加入一次快照")
    p.add_argument("url")
    for k in METRICS:
        p.add_argument(f"--{k}", help=f"{LABELS[k]}（照 Threads 顯示，例如 2.2K）")
    p.add_argument("--at", help="快照時間（ISO，預設現在 HKT）")
    p.set_defaults(fn=cmd_snap)
    p = sub.add_parser("stop", help="停止追蹤（寫入 stopped_at）")
    p.add_argument("url")
    p.add_argument("--at", help="停止時間（ISO，預設現在 HKT）")
    p.set_defaults(fn=cmd_stop)
    p = sub.add_parser("thin", help="data.json 太大時精簡舊快照")
    p.add_argument("--keep", type=int, default=24, help="保留最近幾多個快照（預設 24）")
    p.add_argument("--every", type=int, default=6, help="更早嘅快照每幾多小時留一個（預設 6）")
    p.set_defaults(fn=cmd_thin)
    p = sub.add_parser("report", help="列印純文字報告")
    p.set_defaults(fn=cmd_report)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
