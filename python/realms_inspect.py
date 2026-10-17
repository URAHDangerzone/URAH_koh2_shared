"""Inspect realms.bin: id stats, name mapping check, PNG render, round-trip test.

Usage: python python/realms_inspect.py <map_dir> <out_dir>
"""

import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

from koh2map import read_realms_bin, realm_ids, to_image_rows, write_realms_bin


def main() -> None:
    map_dir, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)

    rmap = read_realms_bin(map_dir / "realms.bin")
    ids = realm_ids(map_dir)
    used, counts = np.unique(rmap, return_counts=True)

    print(f"size: {rmap.shape}, distinct values: {len(used)}")
    print(f"realms by id rules: {sum(not r.is_sea for r in ids.values())} land, "
          f"{sum(r.is_sea for r in ids.values())} sea")
    unknown = [(int(v), int(c)) for v, c in zip(used, counts) if v not in ids]
    missing = [r for i, r in ids.items() if i not in set(used.tolist())]
    print(f"ids in bin without realm: {unknown[:20]}{' ...' if len(unknown) > 20 else ''}")
    print(f"realms with no pixels: {[r.name for r in missing][:30]}")
    top = sorted(zip(counts, used), reverse=True)[:5]
    print("largest:", [(ids[v].name if v in ids else int(v), int(c)) for c, v in top])

    # render with map_color from realms.def where available, else hash color
    lut = {}
    for v in used:
        r = ids.get(int(v))
        if r and r.map_color and r.map_color != (0, 0, 0):
            lut[int(v)] = r.map_color
        else:
            h = (int(v) * 2654435761) & 0xFFFFFF
            lut[int(v)] = ((h >> 16) & 255, (h >> 8) & 255, h & 255)
    img_ids = to_image_rows(rmap)
    rgb = np.zeros(img_ids.shape + (3,), np.uint8)
    for v, c in lut.items():
        rgb[img_ids == v] = c
    Image.fromarray(rgb).save(out_dir / "realms.png")
    print(f"wrote {out_dir / 'realms.png'}")

    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "realms.bin"
        write_realms_bin(p, read_realms_bin(map_dir / "realms.bin"))
        same = p.read_bytes() == (map_dir / "realms.bin").read_bytes()
    print(f"round-trip byte-identical: {same}")


if __name__ == "__main__":
    main()
