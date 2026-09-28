#!/usr/bin/env python3
"""KiCad 8 の標準ライブラリに 3D モデルが無い部品のモデルを作る (CadQuery)。

  python3 tools/gen_3dmodels.py        # hardware/lib/mPB.3dshapes/ に .step と .wrl を出力

寸法は各データシート / 外形図の公称値 (干渉チェックと外観図用。端子の細部は省略):
  QFN-48-1EP_5x5mm_P0.35mm_EP3.7x3.7mm  CH32M030C8U7 (5 x 5 x 0.75mm, 0.35mm ピッチ, 裏面パッド 3.7mm)
  TSON_Advance_3.3x3.3mm                 TPN1R603PL / TPN2R304PL (3.3 x 3.3 x 0.95mm, PowerPAK 1212-8 互換ランド)
  Fuse_1812_4532Metric                   1812 チップヒューズ (4.5 x 3.2 x 1.4mm)
  Fuse_Littelfuse_NANO2_2410             Littelfuse 0451/0453 NANO2 (6.10 x 2.69 x 2.69mm, 端子キャップ 1.0mm)
座標は KiCad のモデル座標 (原点 = フットプリント原点, X 右, Y 上 = 基板の -y, Z = 基板面から上)。
"""
import os

import cadquery as cq

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib", "mPB.3dshapes")
BLACK, METAL, CERAMIC, TAN, MARK = (0.12, 0.12, 0.13), (0.82, 0.82, 0.84), (0.92, 0.91, 0.86), (0.85, 0.76, 0.55), (0.9, 0.9, 0.9)


def box(x0, y0, z0, x1, y1, z1):
    return cq.Workplane("XY").box(x1 - x0, y1 - y0, z1 - z0, centered=False).translate((x0, y0, z0))


def qfn48():
    parts = [(box(-2.5, -2.5, 0.02, 2.5, 2.5, 0.75).edges("|Z").fillet(0.05), BLACK)]
    pads = None
    for k in range(12):
        c = -1.925 + 0.35 * k
        for (x0, y0, x1, y1) in ((c - 0.09, -2.5, c + 0.09, -2.1), (c - 0.09, 2.1, c + 0.09, 2.5),
                                 (-2.5, c - 0.09, -2.1, c + 0.09), (2.1, c - 0.09, 2.5, c + 0.09)):
            p = box(x0, y0, 0, x1, y1, 0.2)
            pads = p if pads is None else pads.union(p)
    pads = pads.union(box(-1.85, -1.85, 0, 1.85, 1.85, 0.02))
    parts.append((pads, METAL))
    parts.append((cq.Workplane("XY").circle(0.2).extrude(0.01).translate((-1.9, -1.9, 0.75)), MARK))   # 1 番ピン (左下)
    return parts


def tson33():
    """ランドは PowerPAK 1212-8: 1〜3 = S, 4 = G (x = -1.435), ドレイン = 右側の大パッド."""
    parts = [(box(-1.65, -1.65, 0.05, 1.65, 1.65, 0.95), BLACK)]
    leads = None
    for y in (-0.99, -0.33, 0.33, 0.99):
        p = box(-1.75, y - 0.17, 0, -1.3, y + 0.17, 0.2)
        leads = p if leads is None else leads.union(p)
    leads = leads.union(box(-0.35, -1.2, 0, 1.75, 1.2, 0.05)).union(box(1.3, -1.45, 0, 1.75, 1.45, 0.2))
    parts.append((leads, METAL))
    parts.append((cq.Workplane("XY").circle(0.15).extrude(0.01).translate((-1.25, 1.25, 0.95)), MARK))
    return parts


def fuse1812():
    return [(box(-1.75, -1.6, 0, 1.75, 1.6, 1.4), TAN),
            (box(-2.25, -1.6, 0, -1.75, 1.6, 1.4).union(box(1.75, -1.6, 0, 2.25, 1.6, 1.4)), METAL)]


def nano2():
    h = 2.69
    return [(box(-2.05, -h / 2, 0.02, 2.05, h / 2, h), CERAMIC),
            (box(-3.05, -h / 2, 0, -2.05, h / 2, h).union(box(2.05, -h / 2, 0, 3.05, h / 2, h)), METAL)]


MODELS = {
    "QFN-48-1EP_5x5mm_P0.35mm_EP3.7x3.7mm": qfn48,
    "TSON_Advance_3.3x3.3mm": tson33,
    "Fuse_1812_4532Metric": fuse1812,
    "Fuse_Littelfuse_NANO2_2410": nano2,
}


def write_wrl(path, parts):
    """VRML 2.0 (KiCad の単位 = 0.1 インチ)。部品ごとに色を付ける."""
    with open(path, "w") as f:
        f.write("#VRML V2.0 utf8\n")
        for wp, col in parts:
            verts, tris = wp.val().tessellate(0.01, 0.2)
            f.write("Shape { appearance Appearance { material Material { diffuseColor %.3f %.3f %.3f "
                    "specularColor 0.3 0.3 0.3 shininess 0.4 } }\n" % col)
            f.write(" geometry IndexedFaceSet { creaseAngle 0.5 coord Coordinate { point [\n")
            f.write(",\n".join("%.5f %.5f %.5f" % (v.x / 2.54, v.y / 2.54, v.z / 2.54) for v in verts))
            f.write("] }\n coordIndex [\n")
            f.write(",\n".join("%d,%d,%d,-1" % t for t in tris))
            f.write("] } }\n")


def main():
    os.makedirs(OUT, exist_ok=True)
    for name, fn in MODELS.items():
        parts = fn()
        asm = cq.Assembly()
        for i, (wp, col) in enumerate(parts):
            asm.add(wp, name=f"{name}_{i}", color=cq.Color(*col))
        asm.save(os.path.join(OUT, name + ".step"), exportType="STEP")
        write_wrl(os.path.join(OUT, name + ".wrl"), parts)
        print("model:", name)


if __name__ == "__main__":
    main()
