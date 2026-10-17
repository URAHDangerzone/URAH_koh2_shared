"""Extract textures from a game asset bundle by container path.

Usage: python python/extract_bundle_assets.py <bundle_file> <out_dir> <asset_path> [<asset_path> ...]
Asset paths as listed in AssetBundles/manifest.txt, e.g. assets/europe/realmsdata.png. A name without
"/" is a texture name instead, for textures without a container path, e.g. the political view's paper
map that the HRE and Iceland builds paint over:
  python python/extract_bundle_assets.py "<game>/AssetBundles/ui" out BigMap_WV
"""

import sys
from pathlib import Path

import UnityPy


def main() -> None:
    bundle, out_dir, wanted = Path(sys.argv[1]), Path(sys.argv[2]), {p.lower() for p in sys.argv[3:]}
    out_dir.mkdir(parents=True, exist_ok=True)
    env = UnityPy.load(str(bundle))
    found = set()
    for path, obj in env.container.items():
        if path.lower() not in wanted:
            continue
        data = obj.read()
        info = f"{path}: {obj.type.name}"
        if obj.type.name == "Texture2D":
            info += f" {data.m_Width}x{data.m_Height} format={data.m_TextureFormat}"
            img = data.image
            out = out_dir / (Path(path).stem + ".png")
            img.save(out)
            info += f" mode={img.mode} -> {out}"
        print(info)
        found.add(path.lower())
    for name in sorted(n for n in wanted - found if "/" not in n):
        for obj in env.objects:
            if obj.type.name == "Texture2D":
                data = obj.read()
                if data.m_Name.lower() == name:
                    out = out_dir / (data.m_Name + ".png")
                    data.image.save(out)
                    print(f"{data.m_Name}: Texture2D {data.m_Width}x{data.m_Height} format={data.m_TextureFormat} -> {out}")
                    found.add(name)
                    break
    for p in sorted(wanted - found):
        print(f"not found: {p}")


if __name__ == "__main__":
    main()
