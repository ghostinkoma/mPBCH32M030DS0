#!/usr/bin/env python3
"""ミシン目 (マウスバイト) パネル: MCU モジュール + パワー段子基板 A / B / C を 1 枚 (100 x 100mm 以内) に面付けする。

  python3 gen_panel.py            # hardware/panel/ に KiCad 基板, hardware/fab/ に製造データ, docs/pcb/ に図

配置 (上から見た図, 単位 mm):
  ┌─┐┌──────┐  ┌──────┐  ┌────────────┐
  │左││  A   │==│  C   │==│     B      │   A / C / B は長辺どうしをタブでつなぐ
  │の││      │  │      │==│            │   (A / C の上下辺はソケット・J3/J4 が端に寄っているのでタブを付けない)
  │桟││      │==│      │==│            │
  │ │└──────┘  └──────┘  └────┬───────┘
  │ │=┌────────────────────┐=┌┴┐              モジュールは横向き (USB-C は右, J1 側が上)。両端の短辺を左右の桟へつなぐ
  │ │ │ M (横向き)          │ │右│             (長辺はピンヘッダ沿いに配線が走っているのでタブを付けない)
  └─┘ └────────────────────┘ └─┘
各基板は 2mm の溝で切り離し, タブの両端にマウスバイトの穴 (0.5mm, 0.8mm ピッチ, 基板側へ 0.25mm 寄せる) を開ける。
タブは, 基板端から 1.2mm 以内に銅 (パッド・配線・ビア) の無い区間にだけ置く (ベタは gen_pcb.py zone_edge で 1.0mm 後退済み)。
"""
import os
import shutil
import subprocess
import zipfile

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
F, T = pcbnew.FromMM, pcbnew.ToMM
NAME = "mPBCH32M030DS0_panel"
GAP = 2.0                      # 基板間の溝 (ルータ径)
BAR = 3.0                      # 捨て桟の幅
MB_D, MB_PITCH, MB_OFF = 0.5, 0.8, 0.25   # マウスバイト: 穴径, ピッチ, 基板側へのずらし量

MW, MH, AH, BW, BH = 22.86, 53.34, 70.74, 43.18, 66.94
XA = BAR + GAP                 # A の左端
XC = XA + MW + GAP
XB = XC + MW + GAP
YB = AH - BH                   # B は下端を A / C にそろえる
YM = AH + GAP                  # モジュール (横向き) の上端
XM = XA                        # モジュールの左端 (21 番ピン側の短辺が左)
XR = XM + MH + GAP             # 右の桟 (B の下辺から吊る)
PW, PH = XB + BW, YM + MW      # パネル外形

BOARDS = [  # (記号, 基板ファイル, 回転 [deg], 左上の位置)
    ("M", "mPBCH32M030DS0.kicad_pcb", 270, (XM, YM)),
    ("A", "daughter/PWR_A/mPBCH32M030DS0_PWR_A.kicad_pcb", 0, (XA, 0.0)),
    ("C", "daughter/PWR_C/mPBCH32M030DS0_PWR_C.kicad_pcb", 0, (XC, 0.0)),
    ("B", "daughter/PWR_B/mPBCH32M030DS0_PWR_B.kicad_pcb", 0, (XB, YB)),
]
BARS = [(0.0, 0.0, BAR, PH),               # 左の桟 (A の左辺とモジュールの左端を支える)
        (XR, YM, XR + 4.0, PH)]            # 右の桟 (B の下辺から吊り, モジュールの右端を支える)
# タブ: (向き, 溝の中心線の位置, 溝に沿った中心, 幅)。向き "v" = 縦の溝 (左右をつなぐ), "h" = 横の溝 (上下をつなぐ)
TABS = [
    ("v", BAR + GAP / 2, 15.0, 4.0), ("v", BAR + GAP / 2, 69.03, 3.0),          # 左の桟 ↔ A (A 左辺の空き 0〜30.2 / 67.3〜70.7)
    ("v", XA + MW + GAP / 2, 10.0, 4.0), ("v", XA + MW + GAP / 2, 66.0, 4.0),   # A ↔ C
    ("v", XC + MW + GAP / 2, 6.9, 4.0), ("v", XC + MW + GAP / 2, 67.97, 4.0),   # C ↔ B
    ("v", BAR + GAP / 2, YM + MW / 2, 4.0),                                       # 左の桟 ↔ モジュール (21 番ピン側の短辺)
    ("v", XM + MH + GAP / 2, YM + 5.17, 3.0),                                     # モジュール (USB 側の短辺, 空き 3.4〜6.9) ↔ 右の桟
    ("h", AH + GAP / 2, XR + 2.0, 3.0),                                           # B の下辺 ↔ 右の桟
]


def rect(x0, y0, x1, y1):
    p = pcbnew.SHAPE_POLY_SET()
    p.NewOutline()
    for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        p.Append(F(x), F(y))
    return p


def copy_board(panel, tag, path, rot, pos):
    """基板の部品・配線・ベタ・図形 (外形以外) をパネルへ写す。ネット名は "<記号>/<ネット>" にして基板ごとに分ける."""
    src = pcbnew.LoadBoard(os.path.join(HERE, path))
    nets = {}
    for code, ni in src.GetNetsByNetcode().items():
        if code == 0:
            continue
        n = pcbnew.NETINFO_ITEM(panel, f"{tag}/{ni.GetNetname()}")
        panel.Add(n)
        nets[code] = n
    items = []
    for fp in src.GetFootprints():
        c = pcbnew.FOOTPRINT(fp)
        for pad in c.Pads():
            if pad.GetNetCode() in nets:
                pad.SetNet(nets[pad.GetNetCode()])
        items.append(c)
    for t in src.GetTracks():
        c = t.Duplicate()
        c.SetNet(nets[t.GetNetCode()]) if t.GetNetCode() in nets else None
        items.append(c)
    for z in src.Zones():
        c = pcbnew.ZONE(z)
        if z.GetNetCode() in nets:
            c.SetNet(nets[z.GetNetCode()])
        items.append(c)
    for d in src.GetDrawings():
        if d.GetLayerName() != "Edge.Cuts":
            items.append(d.Duplicate())
    eb = src.GetBoardEdgesBoundingBox()
    w, h = T(eb.GetRight()) - 0.05, T(eb.GetBottom()) - 0.05          # 原点 = 左上
    for it in items:
        panel.Add(it)
        if rot:
            it.Rotate(pcbnew.VECTOR2I(0, 0), pcbnew.EDA_ANGLE(rot, pcbnew.DEGREES_T))
    # 回転後の外形の左上を pos へ。KiCad の回転 +90° は (x, y) → (y, -x), 270° は (x, y) → (-y, x)
    # (270°: USB 側の上辺が右, J1 側の左辺が上になる)
    dx, dy = {0: pos, 90: (pos[0], pos[1] + w), 270: (pos[0] + h, pos[1])}[rot]
    for it in items:
        it.Move(pcbnew.VECTOR2I(F(dx), F(dy)))
    ww, hh = (h, w) if rot in (90, 270) else (w, h)
    ol = pcbnew.SHAPE_POLY_SET()                   # 基板外形 (角 R1.0mm)
    src.GetBoardPolygonOutlines(ol)
    ol.Rotate(pcbnew.EDA_ANGLE(rot, pcbnew.DEGREES_T), pcbnew.VECTOR2I(0, 0)) if rot else None
    ol.Move(pcbnew.VECTOR2I(F(dx), F(dy)))
    bb = ol.BBox()
    assert abs(T(bb.GetLeft()) - pos[0]) < 0.1 and abs(T(bb.GetTop()) - pos[1]) < 0.1, (tag, T(bb.GetLeft()), T(bb.GetTop()))
    return ol, (pos[0], pos[1], pos[0] + ww, pos[1] + hh)


def mousebites(panel, ori, c, along, width, sides):
    """タブの両端 (溝の両岸) に NPTH の穴を並べる。sides: 溝の両岸それぞれが基板なら True (穴を基板側へ寄せる)."""
    fp = pcbnew.FOOTPRINT(panel)
    fp.SetReference("MB")
    fp.Reference().SetVisible(False)
    fp.Value().SetVisible(False)
    fp.SetAttributes(pcbnew.FP_EXCLUDE_FROM_POS_FILES | pcbnew.FP_EXCLUDE_FROM_BOM | pcbnew.FP_BOARD_ONLY)
    panel.Add(fp)
    n = int((width - MB_D) / MB_PITCH) + 1
    offs = [(k - (n - 1) / 2) * MB_PITCH for k in range(n)]
    for side, is_board in zip((-1, 1), sides):
        edge = c + side * GAP / 2 + (side * MB_OFF if is_board else 0.0)
        for o in offs:
            x, y = (edge, along + o) if ori == "v" else (along + o, edge)
            pad = pcbnew.PAD(fp)
            pad.SetAttribute(pcbnew.PAD_ATTRIB_NPTH)
            pad.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
            pad.SetSize(pcbnew.VECTOR2I(F(MB_D), F(MB_D)))
            pad.SetDrillSize(pcbnew.VECTOR2I(F(MB_D), F(MB_D)))
            ls = pcbnew.LSET()
            for L in (pcbnew.F_Cu, pcbnew.B_Cu, pcbnew.F_Mask, pcbnew.B_Mask):
                ls.AddLayer(L)
            pad.SetLayerSet(ls)
            fp.Add(pad)
            pad.SetPosition(pcbnew.VECTOR2I(F(x), F(y)))


def main():
    panel = pcbnew.BOARD()
    ref = pcbnew.LoadBoard(os.path.join(HERE, "mPBCH32M030DS0.kicad_pcb"))
    panel.SetCopperLayerCount(2)
    panel.SetEnabledLayers(ref.GetEnabledLayers())
    panel.SetVisibleLayers(ref.GetEnabledLayers())
    ds, rs = panel.GetDesignSettings(), ref.GetDesignSettings()      # 基板のルール (DRC 用。プロジェクトも写す)
    for k in ("m_TrackMinWidth", "m_MinClearance", "m_ViasMinSize", "m_MinThroughDrill", "m_CopperEdgeClearance",
              "m_HoleToHoleMin", "m_HoleClearance"):
        setattr(ds, k, getattr(rs, k))
    outline = pcbnew.SHAPE_POLY_SET()
    rects = {}
    for tag, path, rot, pos in BOARDS:
        ol, r = copy_board(panel, tag, path, rot, pos)
        outline.BooleanAdd(ol, pcbnew.SHAPE_POLY_SET.PM_FAST)
        rects[tag] = r
    for x0, y0, x1, y1 in BARS:
        outline.BooleanAdd(rect(x0, y0, x1, y1), pcbnew.SHAPE_POLY_SET.PM_FAST)
    for ori, c, along, width in TABS:
        x0, x1 = c - GAP / 2 - 0.5, c + GAP / 2 + 0.5          # 溝の両岸へ 0.5mm ずつ食い込ませて一体にする
        tab = rect(x0, along - width / 2, x1, along + width / 2) if ori == "v" else rect(along - width / 2, x0, along + width / 2, x1)
        outline.BooleanAdd(tab, pcbnew.SHAPE_POLY_SET.PM_FAST)

        def is_board(px, py):
            return any(r[0] - 0.01 <= px <= r[2] + 0.01 and r[1] - 0.01 <= py <= r[3] + 0.01 for r in rects.values())
        pts = [(c - GAP / 2 - 0.01, along), (c + GAP / 2 + 0.01, along)] if ori == "v" else \
              [(along, c - GAP / 2 - 0.01), (along, c + GAP / 2 + 0.01)]
        mousebites(panel, ori, c, along, width, [is_board(*p) for p in pts])
    outline.Simplify(pcbnew.SHAPE_POLY_SET.PM_STRICTLY_SIMPLE)
    for i in range(outline.OutlineCount()):
        chains = [outline.Outline(i)] + [outline.Hole(i, h) for h in range(outline.HoleCount(i))]
        for ch in chains:
            n = ch.PointCount()
            for k in range(n):
                a, b = ch.CPoint(k), ch.CPoint((k + 1) % n)
                s = pcbnew.PCB_SHAPE(panel)
                s.SetShape(pcbnew.SHAPE_T_SEGMENT)
                s.SetLayer(pcbnew.Edge_Cuts)
                s.SetWidth(F(0.1))
                s.SetStart(a)
                s.SetEnd(b)
                panel.Add(s)
    # JLCPCB の注文番号の位置 (発注時に "Specify a location" を選ぶと, ここに印字される)
    t = pcbnew.PCB_TEXT(panel)
    t.SetText("JLCJLCJLCJLC")
    t.SetLayer(pcbnew.F_SilkS)
    t.SetTextSize(pcbnew.VECTOR2I(F(0.8), F(0.8)))
    t.SetTextThickness(F(0.15))
    t.SetTextAngle(pcbnew.EDA_ANGLE(90, pcbnew.DEGREES_T))
    t.SetPosition(pcbnew.VECTOR2I(F(BAR / 2), F(45.0)))
    panel.Add(t)
    out = os.path.join(HERE, "panel")
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, NAME + ".kicad_pcb")
    assert pcbnew.SaveBoard(path, panel)
    shutil.copy(os.path.join(HERE, "mPBCH32M030DS0.kicad_pro"), path[:-10] + ".kicad_pro")
    bb = outline.BBox()
    print(f"panel: {T(bb.GetWidth()):.2f} x {T(bb.GetHeight()):.2f} mm, outlines {outline.OutlineCount()}, "
          f"holes {sum(outline.HoleCount(i) for i in range(outline.OutlineCount()))} -> {os.path.relpath(path, HERE)}")
    fab(path)
    render(path)


def fab(pcb):
    """ガーバー (銅・レジスト・シルク・ペースト・外形), ドリル (PTH / NPTH 別) を hardware/fab/<NAME>.zip に."""
    out = os.path.join(HERE, "fab", NAME)
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    layers = "F.Cu,B.Cu,F.Paste,B.Paste,F.Silkscreen,B.Silkscreen,F.Mask,B.Mask,Edge.Cuts"
    subprocess.run(["kicad-cli", "pcb", "export", "gerbers", "--layers", layers, "--subtract-soldermask",
                    "-o", out + "/", pcb], check=True, capture_output=True)
    subprocess.run(["kicad-cli", "pcb", "export", "drill", "--format", "excellon", "--excellon-separate-th",
                    "--generate-map", "--map-format", "pdf", "-o", out + "/", pcb], check=True, capture_output=True)
    zp = out + ".zip"
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(os.listdir(out)):
            z.write(os.path.join(out, f), f)
    print("fab:", os.path.relpath(zp, HERE), sorted(os.listdir(out)))


def render(pcb):
    out = os.path.join(HERE, "..", "docs", "pcb")
    for side, layers in (("top", "F.Cu,F.SilkS,F.Mask,Edge.Cuts"), ("bottom", "B.Cu,B.SilkS,B.Mask,Edge.Cuts")):
        svg = os.path.join(out, f"{NAME}_{side}.svg")
        cmd = ["kicad-cli", "pcb", "export", "svg", "--layers", layers, "--exclude-drawing-sheet",
               "--page-size-mode", "2", "-o", svg, pcb]
        if side == "bottom":
            cmd.insert(4, "--mirror")
        subprocess.run(cmd, check=True, capture_output=True)
        w = 1400
        subprocess.run([os.path.join(HERE, "tools", "svg2png.sh"), svg, svg[:-4] + ".png", str(w),
                        str(int(w * (PH + 4) / (PW + 4)))], check=False)


if __name__ == "__main__":
    main()
