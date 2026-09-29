"""Copy shared/ sources into every integration that vendors them.

    python tools/sync_vendored.py           # write copies
    python tools/sync_vendored.py --check   # exit 1 if any copy has drifted (CI)

The mapping lives in tools/vendored.json. Comparison ignores CRLF/LF differences
so a Windows checkout doesn't read as drift.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "tools" / "vendored.json"


def _norm(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def main(argv: list[str]) -> int:
    check = "--check" in argv
    manifest = {k: v for k, v in json.loads(MANIFEST.read_text("utf-8")).items()
                if not k.startswith("_")}
    drifted, written = [], 0
    for source, targets in manifest.items():
        src = _norm((ROOT / source).read_bytes())
        for target in targets:
            path = ROOT / target
            if path.exists() and _norm(path.read_bytes()) == src:
                continue
            if check:
                drifted.append(f"{target}  (source: {source})")
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(src)
                written += 1
                print(f"synced {target}")
    if check:
        if drifted:
            print("Vendored copies differ from shared/ sources:")
            print("\n".join(f"  {d}" for d in drifted))
            print("Edit the shared/ file, then run: python tools/sync_vendored.py")
            return 1
        print(f"vendored copies in sync ({sum(len(t) for t in manifest.values())} files)")
        return 0
    print(f"{written} file(s) updated")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
