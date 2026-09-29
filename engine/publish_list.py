#!/usr/bin/env python3
"""List which files in public/ changed since the last push, so hourly updates push only those.

State is kept in .publish-manifest.json (path -> sha256 of the content last pushed).

Usage:
  python3 publish_list.py                  # human-readable: added / modified / deleted
  python3 publish_list.py --json           # push payload: {"files":[{"path","content"}...], "deleted":[...]}
                                           #   (feed "files" to GitHub push_files in ONE commit;
                                           #    delete each "deleted" path separately)
  python3 publish_list.py --mark           # after a successful push: record current public/ as pushed
  python3 publish_list.py --public DIR --manifest FILE

Exit code: 0 = nothing to push, 1 = changes pending (handy in scripts).
"""
import argparse, hashlib, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def scan(pub: Path) -> dict:
    out = {}
    for p in sorted(pub.rglob("*")):
        if p.is_file():
            out[p.relative_to(pub).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--public", default=str(ROOT / "public"))
    ap.add_argument("--manifest", default=str(ROOT / ".publish-manifest.json"))
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--json", action="store_true")
    g.add_argument("--mark", action="store_true")
    a = ap.parse_args()
    pub, man = Path(a.public), Path(a.manifest)
    cur = scan(pub)
    old = json.loads(man.read_text(encoding="utf-8")) if man.exists() else {}
    added = [k for k in cur if k not in old]
    modified = [k for k in cur if k in old and old[k] != cur[k]]
    deleted = [k for k in old if k not in cur]

    if a.mark:
        man.write_text(json.dumps(cur, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"marked {len(cur)} files as pushed -> {man}")
        return 0
    if a.json:
        files = [{"path": k, "content": (pub / k).read_text(encoding="utf-8")} for k in added + modified]
        json.dump({"files": files, "deleted": deleted}, sys.stdout, ensure_ascii=False)
        print()
    else:
        for tag, lst in (("A", added), ("M", modified), ("D", deleted)):
            for k in lst:
                print(f"{tag}\t{k}")
        print(f"# {len(added)} added, {len(modified)} modified, {len(deleted)} deleted, "
              f"{len(cur) - len(added) - len(modified)} unchanged", file=sys.stderr)
    return 1 if (added or modified or deleted) else 0


if __name__ == "__main__":
    sys.exit(main())
