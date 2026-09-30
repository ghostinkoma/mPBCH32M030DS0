#!/usr/bin/env python3
"""配線済みのモジュール基板で, ピンヘッダ J1/J2 を下面 (ピンが MCU と反対側へ出る向き) へ裏返し, シルクを直す。

  python3 tools/module_headers_bottom.py mPBCH32M030DS0.kicad_pcb

gen_pcb.py main で作り直す場合は同じ処理 (flip_after_route / ピン番号) が入っている。
これは作り直さずに, 確定した配線をそのまま使って向きだけ変えるためのもの (何度実行しても同じ結果)。
  - J1/J2 を 180° 回して下面へ (穴の位置・1 番ピンの位置は変わらないことを確認)
  - 下面の信号名はピンヘッダの樹脂 (ピン中心から 1.27mm) の外へずらす (1.15 → 1.5mm)
  - 上面 (MCU 側) の外縁にピン番号 1〜21
"""
import os
import sys

import pcbnew

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import gen_schematic as gs   # noqa: E402

MM, TO = pcbnew.FromMM, pcbnew.ToMM
path = sys.argv[1]
b = pcbnew.LoadBoard(path)
fps = {f.GetReference(): f for f in b.GetFootprints()}
W = TO(b.GetBoardEdgesBoundingBox().GetWidth())
pads = {}
for ref in ("J1", "J2"):
    fp = fps[ref]
    before = {p.GetNumber(): (p.GetPosition().x, p.GetPosition().y) for p in fp.Pads()}
    if not fp.IsFlipped():
        fp.SetOrientationDegrees(fp.GetOrientationDegrees() + 180)
        fp.Flip(fp.GetPosition(), False)
    after = {p.GetNumber(): (p.GetPosition().x, p.GetPosition().y) for p in fp.Pads()}
    assert all(abs(before[k][0] - after[k][0]) + abs(before[k][1] - after[k][1]) < 1000 for k in before), ref
    pads[ref] = {k: (TO(x), TO(y)) for k, (x, y) in after.items()}

labels = [(net.replace("_IN", "").replace("USB_VBUS", "UVBUS"), ref, n, sgn)
          for ref, pm, sgn in (("J1", gs.PINMAP_L, +1), ("J2", gs.PINMAP_R, -1)) for n, net in pm.items()]
ys = {(s, round(pads[ref][n][1], 2)) for s, ref, n, _ in labels}
nums = {str(n) for n in range(1, 22)}
for d in list(b.GetDrawings()):          # 前回の信号名 (下面) とピン番号 (上面) を消して入れ直す
    if d.GetClass() != "PCB_TEXT":
        continue
    x, y = TO(d.GetPosition().x), TO(d.GetPosition().y)
    t = d.GetText()
    if d.GetLayer() == pcbnew.B_SilkS and (t, round(y, 2)) in ys:
        b.Remove(d)
    elif d.GetLayer() == pcbnew.F_SilkS and t in nums and (x < 1.5 or x > W - 1.5):
        b.Remove(d)


def text(s, x, y, size, layer, left=None):
    t = pcbnew.PCB_TEXT(b)
    t.SetText(s)
    t.SetPosition(pcbnew.VECTOR2I(MM(x), MM(y)))
    t.SetLayer(layer)
    t.SetTextSize(pcbnew.VECTOR2I(MM(size), MM(size)))
    t.SetTextThickness(MM(max(0.1, size * 0.14)))
    if layer == pcbnew.B_SilkS:
        t.SetMirrored(True)
    if left is not None:
        t.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_LEFT if left else pcbnew.GR_TEXT_H_ALIGN_RIGHT)
    b.Add(t)


for s, ref, n, sgn in labels:
    x, y = pads[ref][n]
    text(s, x + sgn * 1.5, y, 0.6, pcbnew.B_SilkS, left=(sgn < 0))   # 裏面の文字は鏡像なので揃えも反転
for ref, xn in (("J1", 0.95), ("J2", W - 0.95)):
    for n in range(1, 22):
        text(str(n), xn, pads[ref][str(n)][1], 0.6, pcbnew.F_SilkS)
pcbnew.ZONE_FILLER(b).Fill(b.Zones())
b.Save(path)
print(f"{path}: J1/J2 -> bottom, labels {len(labels)}, pin numbers 42")
