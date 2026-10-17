"""Read/write Knights of Honor II campaign map data files.

Formats (verified against the game code):

realms.bin
    Raw int16 little-endian, N x N with N = sqrt(bytes / 2) (2048 for europe), no header.
    Loaded by Logic.Game.LoadRealmIDMap via Buffer.BlockCopy into short[N, N], indexed
    realm_id_map[x, z] (WorldMap.RealmIDAt), so the flat index is x * N + z.
    Value = realm id: land realms are positive, sea realms negative.

Realm ids (Logic.Game.LoadRealms):
    1. Land realms (no `isSeaRealm = true`) in realms.def order get ids 1, 2, 3, ...
    2. Realms only present in realms.csv are appended after them (game logs a warning).
    3. Sea realms in realms.def order get id = -(position in the full list), i.e. they
       continue the numbering after all land realms, negated.
    Adding a land realm therefore shifts every sea realm id.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

DEF_RE = re.compile(r"^\s*def\s+(\w+)\s*:\s*Realm\b")
SEA_RE = re.compile(r"^\s*bool\s+isSeaRealm\s*=\s*true\b")


@dataclass
class RealmInfo:
    id: int
    name: str
    is_sea: bool
    map_color: tuple[int, int, int] | None


def parse_realms_def(path: Path) -> list[tuple[str, bool, tuple[int, int, int] | None]]:
    """Return (name, is_sea, map_color) for each `def X : Realm` in file order."""
    out: list[list] = []
    color_re = re.compile(r'^\s*map_color\s*=\s*"(\d+),(\d+),(\d+)"')
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if m := DEF_RE.match(line):
            out.append([m.group(1), False, None])
        elif out and SEA_RE.match(line):
            out[-1][1] = True
        elif out and out[-1][2] is None and (m := color_re.match(line)):
            out[-1][2] = tuple(int(g) for g in m.groups())
    return [tuple(r) for r in out]


def csv_realm_names(path: Path) -> list[str]:
    names = []
    for line in path.read_text(encoding="utf-8-sig").splitlines()[1:]:
        name = line.split(",", 1)[0].strip()
        if not name or name.startswith("//"):
            continue
        name = name.split(".", 1)[0]  # strip period suffix (Name.E / Name.M / Name.L)
        if name.startswith("Name_"):
            name = name[5:]
        names.append(name)
    return names


def realm_ids(map_dir: Path, mod_map_dirs: list[Path] = ()) -> dict[int, RealmInfo]:
    """Reproduce Logic.Game.LoadRealms id assignment.

    Realms that mods add in their own Maps/<map>/realms.def are appended after the
    original defs (new DT keys go to the end), so they come after all vanilla land realms.
    """
    defs = parse_realms_def(map_dir / "realms.def")
    known_defs = {name for name, _, _ in defs}
    for mod_dir in mod_map_dirs:
        if (mod_dir / "realms.def").exists():
            for d in parse_realms_def(mod_dir / "realms.def"):
                if d[0] not in known_defs:
                    defs.append(d)
                    known_defs.add(d[0])
    infos: list[RealmInfo] = []
    known = set()
    for name, is_sea, color in defs:
        if not is_sea:
            infos.append(RealmInfo(len(infos) + 1, name, False, color))
            known.add(name)
    csv = map_dir / "realms.csv"
    if csv.exists():
        for name in csv_realm_names(csv):
            if name not in known:
                infos.append(RealmInfo(len(infos) + 1, name, False, None))
                known.add(name)
    for name, is_sea, color in defs:
        if is_sea:
            infos.append(RealmInfo(-(len(infos) + 1), name, True, color))
    return {r.id: r for r in infos}


def read_realms_bin(path: Path) -> np.ndarray:
    """Return array indexed [x, z] like the game's realm_id_map."""
    raw = np.fromfile(path, dtype="<i2")
    n = int(np.sqrt(raw.size))
    if n * n != raw.size:
        raise ValueError(f"{path}: {raw.size} values is not a square")
    return raw.reshape(n, n)


def write_realms_bin(path: Path, realm_map: np.ndarray) -> None:
    if realm_map.ndim != 2 or realm_map.shape[0] != realm_map.shape[1]:
        raise ValueError("realm map must be square")
    realm_map.astype("<i2").tofile(path)


def to_image_rows(realm_map: np.ndarray) -> np.ndarray:
    """[x, z] -> image rows (top = north = max z)."""
    return realm_map.T[::-1]


def from_image_rows(img: np.ndarray) -> np.ndarray:
    return img[::-1].T


# RealmBounds.bin: .NET BinaryFormatter serialization of List<float>, 6 floats per realm
# (min x, y, z, max x, y, z) in game.realms order (WorldMap.LoadRealmBounds).
# Layout after the fixed class header: _items ref (0x09, id=2), _size i32, _version i32,
# ArraySinglePrimitive record (0x0F, id i32, capacity i32, 0x0B, float32[capacity]), MessageEnd 0x0B.
_ITEMS_REF = b"\x09\x02\x00\x00\x00"


def read_realm_bounds(path: Path) -> np.ndarray:
    """Return float32 array of shape (n_realms, 6)."""
    data = path.read_bytes()
    i = data.index(_ITEMS_REF) + len(_ITEMS_REF)
    size, _version = np.frombuffer(data, "<i4", 2, i)
    i += 8
    if data[i] != 0x0F or data[i + 9] != 0x0B:
        raise ValueError("unexpected BinaryFormatter layout")
    capacity = int(np.frombuffer(data, "<i4", 1, i + 5)[0])
    floats = np.frombuffer(data, "<f4", capacity, i + 10)
    return floats[:size].reshape(-1, 6).copy()


def write_realm_bounds(path: Path, bounds: np.ndarray, template: Path) -> None:
    """Write bounds using `template` (an existing RealmBounds.bin) for the class header."""
    data = template.read_bytes()
    head = data[: data.index(_ITEMS_REF) + len(_ITEMS_REF)]
    version = np.frombuffer(data, "<i4", 1, len(head) + 4)[0]
    template_capacity = int(np.frombuffer(data, "<i4", 1, len(head) + 13)[0])
    flat = np.asarray(bounds, "<f4").ravel()
    capacity = max(flat.size, template_capacity)  # List<T> backing array is zero-padded
    out = bytearray(head)
    out += np.array([flat.size, version], "<i4").tobytes()
    out += b"\x0f" + np.array([2, capacity], "<i4").tobytes() + b"\x0b"
    out += flat.tobytes() + bytes(4 * (capacity - flat.size))
    out += b"\x0b"
    path.write_bytes(bytes(out))


# realmsdata.png (bundle asset assets/europe/realmsdata.png, 2048x2048 RGB24, same
# orientation as to_image_rows): R + 256 * G = abs(realm id); B = terrain detail
# (relief + rivers, province-independent, sea = 255). Mod override path:
# <Mod>/europe/realmsdata.png (ModManager strips the leading "assets/").
def encode_realmsdata(realm_map: np.ndarray, template_rgb: np.ndarray) -> np.ndarray:
    """Build realmsdata RGB from a realm map ([x, z]) and an existing image for B."""
    ids = np.abs(to_image_rows(realm_map).astype(np.int32))
    out = template_rgb.copy()
    out[..., 0] = ids & 0xFF
    out[..., 1] = ids >> 8
    return out


def read_border_records(path: Path) -> list[tuple[int, int, np.ndarray]]:
    """*BordersTrapezoidData.bin: raw float32 triples. Each record is a header
    (realm id a, realm id b, -1), point triples (x, y, z) and a terminator (-1, -1, -1)."""
    a = np.fromfile(path, "<f4").reshape(-1, 3)
    recs, i = [], 0
    while i < len(a):
        h = a[i]
        if h[2] != -1:
            raise ValueError(f"{path}: expected record header at triple {i}")
        i += 1
        start = i
        while not (a[i] == -1).all():
            i += 1
        recs.append((int(h[0]), int(h[1]), a[start:i].copy()))
        i += 1
    return recs


def write_border_records(path: Path, recs) -> None:
    parts = []
    for ra, rb, pts in recs:
        parts.append(np.array([[ra, rb, -1]], "<f4"))
        parts.append(np.asarray(pts, "<f4").reshape(-1, 3))
        parts.append(np.full((1, 3), -1, "<f4"))
    np.concatenate(parts).astype("<f4").tofile(path)


def decode_realmsdata(rgb: np.ndarray) -> np.ndarray:
    """Return abs(realm id) in image-row orientation."""
    return rgb[..., 0].astype(np.int32) + 256 * rgb[..., 1].astype(np.int32)
