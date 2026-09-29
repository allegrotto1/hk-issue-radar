#!/usr/bin/env python3
"""Read Threads post counters logged-out with headless Chrome (fresh incognito profile per post).

  python3 fetch_counts.py                 # read all active posts, print JSON to stdout
  python3 fetch_counts.py --snap          # ...and call `track.py snap` for each post
  python3 fetch_counts.py --only DdyCsmTkt3H --only <url>   # subset
  options: --max-age-days 7  --wait 25  --shots /workspace/tracker-shots  --lang en-US
           --force (snap even if a counter dropped sharply)  --save-html (always keep page HTML)

For every post: launches `google-chrome --headless=new --incognito --user-data-dir=<new temp dir>`,
loads the canonical post URL, waits for the counters to render, dismisses the logged-out
"Continue with Instagram" pop-up if it has a close button, extracts likes / replies / reposts /
shares / views exactly as displayed (e.g. "3.6K", "406K", "2,351"), and saves a screenshot.
Never logs in and never clicks Like / Reply / Repost / Share / Follow.
Stdlib only: talks to Chrome over the DevTools protocol with a tiny built-in WebSocket client.
"""
import argparse, base64, json, os, random, shutil, socket, struct, subprocess, sys, tempfile, time
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import track  # noqa: E402  (parse_count / parse_at / load / METRICS)

HKT = timezone(timedelta(hours=8))
METRICS = track.METRICS
CHROME_CANDIDATES = [
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
    "/opt/pw-browsers/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell",
]
UA = None  # keep Chrome's own UA (headless=new reports a normal Chrome UA minus "Headless" in most builds)


def log(*a):
    print(*a, file=sys.stderr, flush=True)


# ---------------- minimal WebSocket client (RFC 6455, client side) ----------------
class WS:
    def __init__(self, url, timeout=60):
        assert url.startswith("ws://")
        rest = url[5:]
        hostport, path = rest.split("/", 1)
        host, port = hostport.split(":")
        self.s = socket.create_connection((host, int(port)), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (f"GET /{path} HTTP/1.1\r\nHost: {hostport}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        self.s.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.s.recv(4096)
            if not chunk:
                raise ConnectionError("websocket handshake failed")
            buf += chunk
        head, self.buf = buf.split(b"\r\n\r\n", 1)
        if b" 101 " not in head.split(b"\r\n")[0]:
            raise ConnectionError(head.decode(errors="replace"))

    def _recv_exact(self, n):
        while len(self.buf) < n:
            chunk = self.s.recv(max(65536, n - len(self.buf)))
            if not chunk:
                raise ConnectionError("websocket closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def send(self, text):
        data = text.encode()
        hdr = bytearray([0x81])
        n = len(data)
        if n < 126:
            hdr.append(0x80 | n)
        elif n < 65536:
            hdr.append(0x80 | 126); hdr += struct.pack(">H", n)
        else:
            hdr.append(0x80 | 127); hdr += struct.pack(">Q", n)
        mask = os.urandom(4)
        hdr += mask
        self.s.sendall(bytes(hdr) + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def recv(self):
        msg = b""
        while True:
            b1, b2 = self._recv_exact(2)
            op, n = b1 & 0x0F, b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._recv_exact(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._recv_exact(8))[0]
            if b2 & 0x80:
                mask = self._recv_exact(4)
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(self._recv_exact(n)))
            else:
                payload = self._recv_exact(n)
            if op == 0x8:
                raise ConnectionError("websocket closed by peer")
            if op == 0x9:  # ping -> ignore (Chrome doesn't ping)
                continue
            msg += payload
            if b1 & 0x80:
                return msg.decode("utf-8", errors="replace")

    def close(self):
        try:
            self.s.close()
        except Exception:
            pass


class CDP:
    def __init__(self, ws_url):
        self.ws = WS(ws_url)
        self.i = 0

    def call(self, method, params=None, session=None, timeout=60):
        self.i += 1
        mid = self.i
        m = {"id": mid, "method": method, "params": params or {}}
        if session:
            m["sessionId"] = session
        self.ws.send(json.dumps(m))
        end = time.time() + timeout
        while time.time() < end:
            r = json.loads(self.ws.recv())
            if r.get("id") == mid:
                if "error" in r:
                    raise RuntimeError(f"{method}: {r['error']}")
                return r.get("result", {})
        raise TimeoutError(method)


# ---------------- page-side extraction ----------------
EXTRACT_JS = r"""
(() => {
  const NUM = /^[0-9][0-9,]*(?:\.[0-9]+)?\s*[KkMmBb萬万億亿]?$/;
  const pid = location.pathname.split('/post/')[1]?.split(/[/?#]/)[0] || '';
  const titleOf = svg => ((svg.getAttribute('aria-label') || svg.getAttribute('title') ||
                          svg.querySelector('title')?.textContent || '')).trim();
  const KIND = {like:'likes','讚':'likes','赞':'likes','讚好':'likes','赞好':'likes',
                comment:'replies',reply:'replies','回覆':'replies','回复':'replies','留言':'replies','回應':'replies','回应':'replies',
                repost:'reposts','轉發':'reposts','转发':'reposts','轉貼':'reposts',
                share:'shares','分享':'shares'};
  const kindOf = svg => KIND[titleOf(svg).toLowerCase()] || KIND[titleOf(svg)] || null;
  // Main post container: the pressable block that links to its own permalink and has a Like button.
  let root = null;
  const links = [...document.querySelectorAll('a[href*="/post/' + pid + '"]')];
  for (const a of links) {
    let el = a;
    while (el && el !== document.body) {
      if (el.matches && el.matches('[data-pressable-container]')) break;
      el = el.parentElement;
    }
    if (el && el !== document.body && [...el.querySelectorAll('svg')].some(s => kindOf(s) === 'likes')) { root = el; break; }
  }
  const scope = root || document;
  const out = {likes:null, replies:null, reposts:null, shares:null, views:null};
  const seen = new Set();
  for (const svg of scope.querySelectorAll('svg')) {
    const k = kindOf(svg);
    if (!k || seen.has(k)) continue;
    const btn = svg.closest('[role="button"]') || svg.parentElement;
    seen.add(k);
    const txt = [...btn.querySelectorAll('span')].map(s => s.textContent.trim()).find(t => NUM.test(t));
    out[k] = txt || null;
    if (seen.size === 4) break;
  }
  // Views: header text like "406K views" / "40.6萬次瀏覽" / "406K 次瀏覽".
  for (const s of document.querySelectorAll('span')) {
    if (s.children.length) continue;
    const t = s.textContent.trim();
    let m = t.match(/^([0-9][0-9,]*(?:\.[0-9]+)?\s*[KkMmBb萬万億亿]?)\s*(?:views?|次瀏覽|次浏览|次查看|瀏覽次數)$/i);
    if (m) { out.views = m[1].replace(/\s+/g, ''); break; }
  }
  const body = document.body ? document.body.innerText : '';
  return {
    counts: out,
    scoped: !!root,
    pid,
    canonical: document.querySelector('link[rel="canonical"]')?.href || null,
    title: document.title,
    likeButtons: [...document.querySelectorAll('svg')].filter(s => kindOf(s) === 'likes').length,
    sayMoreModal: /Say more with Threads|用 Threads 分享更多|透過 Threads 暢所欲言/.test(body),
    continueIG: /Continue with Instagram|使用 Instagram 繼續|以 Instagram 帳號繼續/.test(body),
    snippet: body.slice(0, 600),
  };
})()
"""

# Close ONLY a dialog's close (X) button. Never touches action buttons.
CLOSE_POPUP_JS = r"""
(() => {
  const labels = ['close', '關閉', '关闭'];
  const dlgs = [...document.querySelectorAll('[role="dialog"]')];
  for (const d of dlgs) {
    for (const el of d.querySelectorAll('svg, [aria-label]')) {
      const t = (el.getAttribute('aria-label') || el.querySelector?.('title')?.textContent || '').trim().toLowerCase();
      if (labels.includes(t)) {
        const btn = el.closest('[role="button"], button') || el;
        btn.click();
        return 'closed';
      }
    }
  }
  return dlgs.length ? 'dialog-without-close' : 'no-dialog';
})()
"""


def find_chrome():
    for c in CHROME_CANDIDATES:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
        p = shutil.which(c)
        if p:
            return p
    raise SystemExit("找不到 Chrome/Chromium（試過 " + ", ".join(CHROME_CANDIDATES) + "）")


def read_post(url, shots_dir, wait=25, lang="en-US", save_html=False, tag=""):
    """Load one post in a brand-new incognito headless Chrome; return dict with counts + diagnostics."""
    chrome = find_chrome()
    prof = tempfile.mkdtemp(prefix="threads-prof-")
    proc = None
    res = {"url": url, "id": track.post_id(url), "counts": {k: None for k in METRICS}, "ok": False}
    try:
        proc = subprocess.Popen(
            [chrome, "--headless=new", "--incognito", "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
             f"--user-data-dir={prof}", "--remote-debugging-port=0",
             "--no-first-run", "--no-default-browser-check", "--disable-extensions", "--disable-sync",
             "--disable-background-networking", "--mute-audio", "--hide-scrollbars", f"--lang={lang}",
             "--window-size=1280,2000", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        port_file = os.path.join(prof, "DevToolsActivePort")
        for _ in range(150):
            if os.path.exists(port_file) and os.path.getsize(port_file) > 0:
                break
            time.sleep(0.1)
        port, path = open(port_file).read().split()[:2]
        cdp = CDP(f"ws://127.0.0.1:{port}{path}")
        tgt = cdp.call("Target.createTarget", {"url": "about:blank"})["targetId"]
        sess = cdp.call("Target.attachToTarget", {"targetId": tgt, "flatten": True})["sessionId"]
        cdp.call("Page.enable", session=sess)
        cdp.call("Network.enable", session=sess)
        cdp.call("Network.setExtraHTTPHeaders", {"headers": {"Accept-Language": f"{lang},en;q=0.8"}}, session=sess)
        cdp.call("Emulation.setDeviceMetricsOverride",
                 {"width": 1280, "height": 2000, "deviceScaleFactor": 1, "mobile": False}, session=sess)
        cdp.call("Page.navigate", {"url": url}, session=sess)

        def ev(js):
            r = cdp.call("Runtime.evaluate", {"expression": js, "returnByValue": True}, session=sess)
            return r.get("result", {}).get("value")

        info, t0 = None, time.time()
        while time.time() - t0 < wait:
            time.sleep(1.5)
            try:
                info = ev(EXTRACT_JS)
            except Exception:
                continue
            if info and info["counts"].get("likes") is not None and info["counts"].get("views") is not None:
                time.sleep(1.5)  # let late counters settle, then re-read
                info = ev(EXTRACT_JS) or info
                break
        res["popup"] = ev(CLOSE_POPUP_JS)
        if res["popup"] == "dialog-without-close":  # try Escape (keyboard only; never clicks the page)
            for typ in ("keyDown", "keyUp"):
                cdp.call("Input.dispatchKeyEvent", {"type": typ, "key": "Escape", "code": "Escape",
                                                    "windowsVirtualKeyCode": 27}, session=sess)
            time.sleep(0.5)
            res["popup"] = "escape:" + ev(CLOSE_POPUP_JS)
        time.sleep(0.8)
        info = ev(EXTRACT_JS) or info or {}
        res.update({k: info.get(k) for k in ("scoped", "canonical", "title", "likeButtons", "sayMoreModal", "continueIG")})
        res["counts"] = {k: (info.get("counts") or {}).get(k) for k in METRICS}
        res["read_at"] = datetime.now(HKT).replace(microsecond=0).isoformat()
        res["ok"] = any(v is not None for v in res["counts"].values())
        stamp = datetime.now(HKT).strftime("%Y%m%d-%H%M%S")
        base = os.path.join(shots_dir, f"{stamp}-{res['id']}{tag}")
        shot = cdp.call("Page.captureScreenshot", {"format": "png"}, session=sess, timeout=90)
        with open(base + ".png", "wb") as f:
            f.write(base64.b64decode(shot["data"]))
        res["screenshot"] = base + ".png"
        if save_html or not res["ok"]:
            html = ev("document.documentElement.outerHTML") or ""
            with open(base + ".html", "w", encoding="utf-8") as f:
                f.write(html)
            res["html"] = base + ".html"
            res["page_text"] = info.get("snippet")
        try:
            cdp.call("Browser.close", timeout=5)
        except Exception:
            pass
        cdp.ws.close()
    except Exception as e:  # report, keep going with other posts
        res["error"] = f"{type(e).__name__}: {e}"
    finally:
        if proc:
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
        shutil.rmtree(prof, ignore_errors=True)
    return res


def compare(post, counts):
    """Diff vs previous snapshot. Returns (changes, warnings)."""
    prev = post["snapshots"][-1] if post["snapshots"] else None
    changes, warns = {}, []
    for k in METRICS:
        new = track.parse_count(counts.get(k)) if counts.get(k) else None
        old = prev.get(k) if prev else None
        changes[k] = {"prev": old["raw"] if old else None, "now": counts.get(k),
                      "delta": (new["value"] - old["value"]) if (new and old) else None}
        if new and old and old["value"] > 0:
            drop = (old["value"] - new["value"]) / old["value"]
            # abbreviated numbers (K/萬) round, so allow slack; flag real drops
            slack = 0.12 if (new["approx"] or old["approx"]) else 0.03
            if drop > slack and (old["value"] - new["value"]) > 2:
                warns.append(f"{k} {old['raw']} -> {counts[k]} ({-drop*100:.1f}%)")
        if old and not new:
            warns.append(f"{k} missing now (was {old['raw']})")
    return (prev["taken_at"] if prev else None), changes, warns


def maybe_stop_cold(post, counts, read_at):
    """After the 10:01 HKT read, stop a post whose views grew less than 10%."""
    if track.parse_at(read_at).hour != 10:
        return None
    prev = post["snapshots"][-1] if post.get("snapshots") else None
    old = (prev or {}).get("views") if prev else None
    new = track.parse_count((counts or {}).get("views"))
    if not track.should_autostop(old, new):
        return None
    cmd = [sys.executable, os.path.join(HERE, "track.py"), "stop", post["url"], "--at", read_at]
    cp = subprocess.run(cmd, capture_output=True, text=True, cwd=HERE)
    note = (cp.stdout + cp.stderr).strip()
    if cp.returncode != 0:
        return note or "停止追蹤失敗"
    return "已停止追蹤（瀏覽增長少於 10%）。" + ((" " + note) if note else "")


def main():
    ap = argparse.ArgumentParser(description="Logged-out headless read of Threads counters for tracked posts")
    ap.add_argument("--snap", action="store_true", help="call track.py snap for each post")
    ap.add_argument("--only", action="append", help="post id or URL (repeatable)")
    ap.add_argument("--max-age-days", type=float, default=7, help="skip posts whose first snapshot is older (default 7)")
    ap.add_argument("--wait", type=float, default=25, help="max seconds to wait for render (default 25)")
    ap.add_argument("--shots", default="/workspace/tracker-shots", help="screenshot dir")
    ap.add_argument("--lang", default="en-US", help="browser language (default en-US -> K/M abbreviations)")
    ap.add_argument("--retries", type=int, default=1, help="re-read attempts when result is empty/suspicious (default 1)")
    ap.add_argument("--force", action="store_true", help="snap even if a counter dropped sharply")
    ap.add_argument("--save-html", action="store_true", help="always save page HTML next to the screenshot")
    a = ap.parse_args()
    os.makedirs(a.shots, exist_ok=True)

    d = track.load()
    now = datetime.now(HKT)
    results = []
    for p in d["posts"]:
        if p.get("stopped_at"):
            results.append({"id": p["id"], "url": p["url"], "skipped": f"tracking stopped at {p['stopped_at']}"}); continue
        if a.only and not any(o == p["id"] or track.post_id(o) == p["id"] if "/post/" in o else o == p["id"] for o in a.only):
            continue
        first = p["snapshots"][0]["taken_at"] if p["snapshots"] else p.get("first_seen")
        if first and now - track.parse_at(first) > timedelta(days=a.max_age_days):
            results.append({"id": p["id"], "url": p["url"], "skipped": f"first snapshot {first} > {a.max_age_days:g} days old"})
            continue
        attempt, r = 0, None
        while True:
            log(f"[{p['id']}] reading {p['url']} (attempt {attempt+1})")
            r = read_post(p["url"], a.shots, a.wait, a.lang, a.save_html, tag=f"-a{attempt+1}" if attempt else "")
            r["prev_taken_at"], r["changes"], r["warnings"] = compare(p, r["counts"]) if r["ok"] else (None, {}, [])
            if (r["ok"] and not r["warnings"]) or attempt >= a.retries:
                break
            attempt += 1
            log(f"[{p['id']}] {'no counts' if not r['ok'] else 'suspicious: ' + '; '.join(r['warnings'])} -> re-reading")
            time.sleep(3 + random.random() * 3)
        r["attempts"] = attempt + 1
        if a.snap:
            if not r["ok"]:
                r["snapped"] = False; r["snap_note"] = "all counters missing - not snapped"
            elif r["warnings"] and not a.force:
                r["snapped"] = False; r["snap_note"] = "sharp drop/missing vs previous snapshot - not snapped (use --force)"
            else:
                cmd = [sys.executable, os.path.join(HERE, "track.py"), "snap", p["url"]]
                for k in METRICS:
                    cmd += [f"--{k}", r["counts"][k] or "-"]
                cmd += ["--at", r["read_at"]]
                cp = subprocess.run(cmd, capture_output=True, text=True, cwd=HERE)
                r["snapped"] = cp.returncode == 0
                r["snap_note"] = (cp.stdout + cp.stderr).strip()
                if r["snapped"]:
                    stop_note = maybe_stop_cold(p, r["counts"], r["read_at"])
                    if stop_note:
                        r["stopped"] = True
                        r["snap_note"] = (r["snap_note"] + "\n" + stop_note).strip()
        results.append(r)
        time.sleep(2 + random.random() * 2)  # be gentle between posts

    print(json.dumps({"run_at": now.replace(microsecond=0).isoformat(), "posts": results}, ensure_ascii=False, indent=1))
    failed = [r for r in results if not r.get("skipped") and not r.get("ok")]
    for r in failed:
        log(f"[{r['id']}] NO COUNTS: sayMoreModal={r.get('sayMoreModal')} error={r.get('error')} html={r.get('html')} shot={r.get('screenshot')}")
    return 2 if failed and len(failed) == len([r for r in results if not r.get("skipped")]) else (1 if failed else 0)


if __name__ == "__main__":
    sys.exit(main())
