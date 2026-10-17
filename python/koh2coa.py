"""Coat of arms atlases of Knights of Honor II (CoatOfArmsAtlas<Mode>.png).

Kingdom shields are drawn straight from pre-rendered atlas textures: crest id i is tile i, tiles
row-major with row 0 at the bottom of the texture (columns = atlas_width // width). A mod ships edited
copies as <mod>/Maps/europe/CoatOfArmsAtlas<Mode>.png.
"""

from __future__ import annotations

from PIL import Image

MODES = {  # name: (atlas file mode suffix, tile width, tile height) from Defs/CoatOfArms/coatOfArms.def
    "shield": (72, 96),
    "flag": (128, 64),
    "banner": (64, 128),
    "small_shield": (36, 48),
}


def tile_box(img: Image.Image, idx: int, w: int, h: int):
    cols = img.width // w
    c, r = idx % cols, idx // cols
    top = img.height - (r + 1) * h
    return (c * w, top, c * w + w, top + h)
