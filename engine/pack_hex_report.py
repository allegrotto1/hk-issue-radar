#!/usr/bin/env python3
"""Pack a built report HTML into hex-chunk loader for GitHub Pages MCP push limits."""
import argparse, math, zlib
from pathlib import Path

def pack(html_path: Path, out_dir: Path, title_hour: str, date_label: str, n_parts: int = 8):
    html = html_path.read_bytes()
    comp = zlib.compress(html, 9)
    hx = comp.hex()
    out_dir.mkdir(parents=True, exist_ok=True)
    for p in out_dir.glob("h*.hex"):
        p.unlink()
    chunk = math.ceil(len(hx) / n_parts) if n_parts else len(hx)
    names = []
    for i in range(n_parts):
        part = hx[i * chunk : (i + 1) * chunk]
        name = "h%d.hex" % i
        (out_dir / name).write_text(part + "\n", encoding="ascii")
        names.append(name)
    canon = "https://allegrotto1.github.io/hk-issue-radar/reports/%s/" % out_dir.name
    parts_js = ", ".join(repr(n) for n in names)
    idx = """<!DOCTYPE html>
<html lang="zh-Hant-HK">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>%s 每小時議題快報｜香港議題雷達</title>
<link rel="canonical" href="%s"/>
</head>
<body>
<p id="s">載入 %s 快報全文…</p>
<script>
(async () => {
  const parts = [%s];
  const texts = await Promise.all(parts.map(p => fetch(new URL(p, location.href)).then(r => {
    if (!r.ok) throw new Error(p + " " + r.status);
    return r.text();
  })));
  const hex = texts.join("").trim();
  const bin = new Uint8Array(hex.length/2);
  for (let i=0;i<bin.length;i++) bin[i]=parseInt(hex.substr(i*2,2),16);
  const ds = new DecompressionStream("deflate");
  const html = await new Response(new Blob([bin]).stream().pipeThrough(ds)).text();
  document.open(); document.write(html); document.close();
})().catch(e => { document.getElementById("s").textContent = "\u8f09\u5165\u5931\u6557\uff1a" + e; });
</script>
</body>
</html>
""" % (date_label, canon, title_hour, parts_js)
    (out_dir / "index.html").write_text(idx, encoding="utf-8")
    (out_dir / "full.html.local").write_bytes(html)
    print("packed %s -> %s (%d bytes -> %d zlib, %d hex parts)" % (
        html_path, out_dir, len(html), len(comp), n_parts))

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("html")
    ap.add_argument("out_dir")
    ap.add_argument("--hour", required=True)
    ap.add_argument("--date-label", required=True)
    ap.add_argument("--parts", type=int, default=8)
    a = ap.parse_args()
    pack(Path(a.html), Path(a.out_dir), a.hour, a.date_label, a.parts)
