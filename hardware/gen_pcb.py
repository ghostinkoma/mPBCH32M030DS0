#!/usr/bin/env python3
"""
mPBCH32M030DS0 Rev 0.4 の基板 (2 層) を生成する。KiCad 8 (pcbnew 8.0.x) の Python で実行する。

  python3 gen_schematic.py                 # 先に parts.json を作る
  python3 gen_pcb.py [main|A|B|C|all] [--no-route] [--reroute]
  python3 gen_pcb.py fab                   # 製造データ (hardware/fab/*.zip)
  python3 gen_pcb.py summary               # docs/pcb/drc_summary.md を更新

構成 (上から見た座標, 原点 = 左上):
  MCU モジュール  20.32 x 53.34mm (8 x 21 マス)。左右端に 21 ピン x 2 列 (x = 2.54 / 17.78, 列間 15.24mm)
                  → ブレッドボードに直接挿せる。USB-C は上端。LED・スイッチ・ジャンパは上面。
  パワー段子基板  モジュールと同じ位置に 1x21 ピンソケット x2 (上面, 左右対称)。モジュールは上から挿す。
                  MOSFET・シャント等は下面 (ヒートシンク側)。電源入力 J3 / モータ出力 J4 は下端。
"""
import os
import subprocess
import sys

import pcblib
from pcblib import Pcb

REUSE = True
FR_OPTS_MAIN = tuple(os.environ.get("MPB_FR_OPTS", "-us hybrid -hr 1:1").split())   # Freerouting の追加オプション
FR_OPTS = tuple(os.environ.get("MPB_FR_OPTS_D", "").split())                           # 子基板 (試行で hybrid より良好)
MW, MH = 20.32, 53.34          # モジュール外形
PIN_X = (2.54, 17.78)          # DIP 端子列の x
PIN_Y0 = 1.27                  # 1 番ピンの y


def hicur_daughter(b):
    """子基板の大電流ネット: 自動配線は 0.3mm で通し (SOT-23-6 の LM74700 や ソケット端子の間も抜けられる),
    後でベタで太らせる (grow_zones)."""
    b.classes["HiCur"].SetTrackWidth(pcblib.MM(0.3))
    b.classes["HiCur"].SetClearance(pcblib.MM(0.15))
    b.classes["HiCur"].SetViaDiameter(pcblib.MM(0.8))
    b.classes["HiCur"].SetViaDrill(pcblib.MM(0.4))
    b.netclass("HiCur", ["VBUS", "VIN", "VIN_F", "ISH", "USB_VBUS", "USB_VBUS_P"])
    # 相出力・ローサイドのソース (モータ電流) は通常の太さで配線し (配線しやすさ優先), 後でベタで太らせる
    b.grow_extra = [f"SW{i}" for i in range(4)] + [f"SRC{i}" for i in range(4)]


def pre_route(b, ref, pts, width):
    """部品の腹下などに短い配線を先に置く。pts はパッド番号 "3" か, 2 パッドの中点 ("3", "4") の並び."""
    fp = b.fps[ref]
    xy = lambda p: b.pad_xy(ref, p) if isinstance(p, str) else \
        tuple((u + v) / 2 for u, v in zip(b.pad_xy(ref, p[0]), b.pad_xy(ref, p[1])))
    net = next(q for q in fp.Pads() if q.GetNumber() == pts[0]).GetNet()
    for p1, p2 in zip(pts, pts[1:]):
        t = pcblib.pcbnew.PCB_TRACK(b.b)
        t.SetStart(pcblib.P(*xy(p1)))
        t.SetEnd(pcblib.P(*xy(p2)))
        t.SetWidth(pcblib.MM(width))
        t.SetLayer(pcblib.pcbnew.B_Cu if fp.IsFlipped() else pcblib.pcbnew.F_Cu)
        t.SetNet(net)
        b.b.Add(t)


def put(b, ref, left, top, rot=0, side="F"):
    """courtyard の左上が (left, top) になるように置く."""
    b.place(ref, 0, 0, rot, side)
    l, t, _, _ = b.bbox(ref)
    return b.place(ref, left - l, top - t, rot, side)


def put_c(b, ref, cx, cy, rot=0, side="F"):
    """courtyard の中心を (cx, cy) に置く."""
    b.place(ref, 0, 0, rot, side)
    l, t, r, bt = b.bbox(ref)
    return b.place(ref, cx - (l + r) / 2, cy - (t + bt) / 2, rot, side)


def shift_right(b, refs, x_right, side="F", rot=0):
    """1 行に並べた refs を, 右端が x_right に揃うよう平行移動する."""
    dx = x_right - max(b.bbox(r)[2] for r in refs)
    for r in refs:
        l, t, _, _ = b.bbox(r)
        put(b, r, l + dx, t, rot=rot, side=side)


def pin_labels(b, refs_maps, layer, dx, size=0.6):
    """DIP 端子の信号名をシルクに入れる (ブレッドボードで使うとき用)."""
    for ref, pinmap, sgn in refs_maps:
        for n, net in pinmap.items():
            x, y = b.pad_xy(ref, n)
            t = b.text(net.replace("_IN", "").replace("USB_VBUS", "UVBUS"), x + sgn * dx, y, size, layer=layer)
            left = (sgn > 0) != layer.startswith("B.")   # 裏面の文字は鏡像なので揃えも反転
            t.SetHorizJustify(pcblib.pcbnew.GR_TEXT_H_ALIGN_LEFT if left else pcblib.pcbnew.GR_TEXT_H_ALIGN_RIGHT)


# ---------------------------------------------------------------------------
# MCU モジュール
# ---------------------------------------------------------------------------
HICUR_MAIN = ["USB_VBUS"]


def build_main(route=True):
    import gen_schematic as gs
    b = Pcb(".", MW, MH, "mPBCH32M030DS0 MCU module (DIP-42, CH32M030C8U7)", rev="0.4")
    b.classes["HiCur"].SetTrackWidth(pcblib.MM(0.3))                    # 自動配線は細く通し, 後でベタで太らせる
    b.classes["HiCur"].SetClearance(pcblib.MM(0.15))
    b.netclass("HiCur", HICUR_MAIN)
    dflt = b.b.GetDesignSettings().m_NetSettings.m_DefaultNetClass
    dflt.SetTrackWidth(pcblib.MM(0.127))
    dflt.SetClearance(pcblib.MM(0.127))
    # ---- 端子・USB (上面) ----
    b.place("J1", PIN_X[0], PIN_Y0)
    b.place("J2", PIN_X[1], PIN_Y0)
    put_c(b, "J8", MW / 2, 3.7, rot=180)                  # USB-C: 差込口は上端
    put(b, "U3", 4.45, 8.6)
    put(b, "SW1", 10.95, 8.5)
    put_c(b, "U1", MW / 2, 19.6)                          # ゲートピン → 右列 J2, USB/アナログ → 左列 J1
    put(b, "Y1", 7.2, 23.2)
    yj = b.pack(["JP2", "JP3", "JP4", "JP8"], 4.45, 27.0, 7.1, rot=90, row_gap=0.3)
    yd = b.pack(["D5", "D6", "D4", "F2"], 7.4, 27.4, 13.2, rot=0, row_gap=0.3)
    # ゲート確認 LED は右下 (y ≥ 38) に 3 列。QFN 右辺のゲートピン → J2 の引き出しを塞がない
    y0 = max(yd, 37.9) + 0.4
    b.pack(["R50", "D10", "R51", "D11", "R52", "D12", "R53", "D13",
            "R54", "D14", "R55", "D15", "R56", "D16", "R57", "D17"], 12.45, y0, b.bbox("J2")[0] - 0.05,
           rot=90, gap=0.15, row_gap=0.2)
    put(b, "SW2", 7.4, y0)
    b.pack(["D7", "R4", "D2", "R3", "D8", "R5", "D3", "R112"], 7.4, b.bbox("SW2")[3] + 0.3, 12.2, rot=90, gap=0.2)
    # ---- 下面 (高さ ≤2mm の CR) ----
    B = "B"
    # MCU の電源ピン (VHV/VDD8/VDD33) は上辺 → 容量は MCU の上側の裏。裏面パッドのサーマルビア直下は空ける
    y = b.pack(["R7", "R8", "C7", "R130", "C130", "R131", "C133"], 4.45, 8.4, 13.3, side=B)
    y = b.pack(["C10", "C12"], 4.45, y + 0.2, 13.3, side=B)
    b.pack(["C14", "C11", "C13", "C15"], 4.45, y + 0.2, 13.3, side=B)
    b.pack(["C21", "C22", "C23", "C24"], 13.45, 12.2, 15.95, rot=90, side=B)              # ブートストラップ
    b.pack(["R16", "R17", "C19", "R18", "R19", "C20"], 4.45, 17.2, 6.95, rot=90, side=B)  # 電流アンプ入力
    # QFN 下辺ピンの真下 (y 22〜25) は両面とも空けてビアで引き出せるようにする
    b.pack(["C131", "C132", "R13", "C17", "R14", "R15", "C18", "C16", "R10"], 7.0, 25.6, 13.4, side=B)
    b.pack(["R100", "R101", "C100", "R103", "R104", "C101", "R106", "R107", "C102"], 4.45, 34.6, 10.2, rot=90, side=B)
    b.pack(["R123", "C105", "C103", "R110", "R111", "R114", "R115", "R120", "R122"], 10.6, 34.6, 15.9, rot=90, side=B)
    pin_labels(b, [("J1", gs.PINMAP_L, +1), ("J2", gs.PINMAP_R, -1)], "B.SilkS", 1.15)
    return finish(b, route, silk=[("mPB CH32M030", MW / 2, MH - 3.4, 0.8, "B.SilkS"),
                                  ("ghostinkoma/mPBCH32M030DS0", MW / 2, MH - 1.8, 0.6, "B.SilkS")],
                  outside_ok={"J8", "J1", "J2"}, fr_opts=FR_OPTS_MAIN)


# ---------------------------------------------------------------------------
# パワー段子基板 A / C (幅 = モジュールと同じ 20.32mm)
# ---------------------------------------------------------------------------
DH_EXT = 18.6                 # モジュール下端より下に伸ばす長さ (電源入力 J3 / モータ出力 J4)
LEG = {"A": dict(W=MW, H=MH + DH_EXT), "C": dict(W=MW, H=MH + DH_EXT)}


def build_daughter(key, route=True):
    import gen_schematic as gs
    if key == "B":
        return build_daughter_b(route)
    L = LEG[key]
    W, H = L["W"], L["H"]
    b = Pcb(f"daughter/PWR_{key}", W, H, f"mPBCH32M030DS0 power board {key}", rev="0.4")
    hicur_daughter(b)
    # ---- 上面: ソケット (モジュールと同じ位置), 電源入力・モータ出力, モジュール真下の背の低い電源部品 ----
    b.place("J1", PIN_X[0], PIN_Y0)
    b.place("J2", PIN_X[1], PIN_Y0)
    put_c(b, "J4", W / 2, H - 3.3, rot=90)              # モータ出力 2x8 (下端)
    put_c(b, "J3", W / 2, H - 9.9, rot=90)              # 電源入力 2x6
    y = 0.6
    # 上から: USB-PD 経路・78L05・VBUS 分圧 (J1-1〜5 の USB_VBUS / VBUS_SNS / PD_PWR_EN / +5V の近く)
    #        → バルク容量 (モジュールの真下, 高さ 6.2mm) → 電源入力 VIN 経路 (下端の J3 の近く)
    for row in ([["F3", "Q10"], ["D9", "C6", "R6"], ["U5", "R11", "R12"], ["U2", "C3", "C4"]] +
                [[r] for r in ("C7", "C8", "C9") if r in b.fps] +
                [["F1", "C5"], [("D1", 90), "Q9"], ["U4", ("C1", 90)]]):
        x = 4.45
        rowb = y
        for it in row:
            ref, rot = it if isinstance(it, tuple) else (it, 0)
            put(b, ref, x, y, rot=rot)
            l, t, r, bt = b.bbox(ref)
            x = r + 0.25
            rowb = max(rowb, bt)
        y = rowb + 0.7
    # ---- 下面 (ヒートシンク側): 4 レッグ + バスシャント + 分圧 ----
    B = "B"
    y = 1.2                        # 上端のゲートパッドへ配線が入れるよう基板端から離す
    for i in (3, 2, 1, 0):         # J2 のゲートピンの並び (上から HO3 … LO0) に合わせる
        rb = 30 + 10 * i
        y = b.pack([f"Q{1 + 2 * i}", f"Q{2 + 2 * i}"], 4.45, y, 15.9, side=B, gap=0.4)
        put(b, f"R{rb + 4}", 4.45, y + 0.2, side=B)                          # シャント
        put(b, f"C{rb + 1}", b.bbox(f"R{rb + 4}")[2] + 0.25, y + 0.2, rot=90, side=B)
        y = max(b.bbox(f"R{rb + 4}")[3], b.bbox(f"C{rb + 1}")[3])
        extra = ["TH1"] if i == 1 else []          # NTC は MOSFET の間
        # ゲート抵抗 (HO/LO から) は J2 側 (右端) に置く
        row = [f"C{rb}", f"R{rb + 1}", f"R{rb + 3}", f"R{rb + 2}", f"R{rb}"]
        yr = y + 0.3
        y = b.pack(row, 4.45, yr, 15.9, rot=90, side=B)
        shift_right(b, row, 15.9, side=B, rot=90)
        for r in extra:                            # NTC は左端 (J1-10 の近く)
            put(b, r, 4.45, yr, rot=90, side=B)
            y = max(y, b.bbox(r)[3])
        y += 1.4
    put(b, "R70", 4.45, y, side=B)                                           # バスシャント
    put(b, "JP5", b.bbox("R70")[2] + 0.25, y, rot=90, side=B)
    y = max(b.bbox("R70")[3], b.bbox("JP5")[3]) + 0.2
    put(b, "JP7", 4.45, y, rot=90, side=B)
    b.pack(["R71", "R72", "C71", "R74", "R75", "C72", "R77", "R78", "C73"], b.bbox("JP7")[2] + 0.25, y, 15.9,
           rot=90, side=B, gap=0.15, row_gap=0.2)
    for ref, txt in (("J3", "VIN / GND"), ("J4", "OUT0  OUT1  OUT2  OUT3")):
        l, t, r, bt = b.bbox(ref)
        b.text(txt, (l + r) / 2, t - 0.6, 0.7)
    return finish(b, route, silk=[(f"mPB PWR-{key}", W / 2, 54.3, 0.7)],
                  outside_ok={"J4", "J1", "J2"}, fr_opts=FR_OPTS)


BW = 40.64                    # 子基板 B の幅 (16 マス)。モジュールは中央 (左右対称)
BOFF = (BW - MW) / 2


def build_daughter_b(route=True):
    """TO-263 x8 は下面に 3 列 x 3 段 (ソケット端子列の間を避ける)。ゲート抵抗・シャントは上面の外側."""
    W, H = BW, MH + 13.6           # 40.64 x 66.94mm (Rev 0.3 の 66 x 66mm から -38%)
    b = Pcb("daughter/PWR_B", W, H, "mPBCH32M030DS0 power board B", rev="0.4")
    hicur_daughter(b)
    b.place("J1", BOFF + PIN_X[0], PIN_Y0)
    b.place("J2", BOFF + PIN_X[1], PIN_Y0)
    put_c(b, "J4", W / 2, H - 3.3, rot=90)
    put_c(b, "J3", W / 2, H - 9.9, rot=90)
    zl0, zr0 = 1.0, b.bbox("J1")[0] - 0.2                                  # モジュールの左外側 (基板端から 1mm 空けて配線を通す)
    zl1, zr1 = b.bbox("J2")[2] + 0.2, W - 0.4                               # モジュールの右外側
    x0, x1 = b.bbox("J1")[2] + 0.25, b.bbox("J2")[0] - 0.25                 # ソケット列の間 (モジュールの真下)

    def flow(items, xa, xb, y, gap=0.25):
        """items を xa..xb の幅で折り返しながら上から並べ, 最下端を返す."""
        x, rowb = xa, y
        for it in items:
            ref, rot = it if isinstance(it, tuple) else (it, 0)
            put(b, ref, x, y, rot=rot)
            if b.bbox(ref)[2] > xb + 1e-6 and x > xa:
                x, y = xa, rowb + gap + 0.05
                put(b, ref, x, y, rot=rot)
            x = b.bbox(ref)[2] + gap
            rowb = max(rowb, b.bbox(ref)[3])
        return rowb
    # モジュールの真下: バルク容量 → 電源入力 (J3 側)
    y = flow(["C7", "C8", "C9"], x0, x1, 0.6)
    flow(["F1", "C5", ("D1", 90), "Q9", "U4", ("C1", 90)], x0, x1, y + 0.6)
    # 左外側 (J1 の USB_VBUS / VBUS_SNS / +5V の近く): USB-PD 経路, 78L05, VBUS 分圧
    y = flow(["F3", "D9", "Q10", "U5", "C6", "R6", "U2", "C3", "C4", "R11", "R12"], zl0, zr0, 0.6, gap=0.7)
    # 左外側の下: 各レッグのシャント + VBUS-SRC 容量 (ISH は J1-18 と下面の R70 へ)
    y += 0.6
    for i in (3, 2, 1, 0):
        rb = 30 + 10 * i
        put(b, f"R{rb + 4}", 0.4, y)                                        # シャントは基板端まで寄せる
        put(b, f"C{rb + 1}", b.bbox(f"R{rb + 4}")[2] + 0.3, y, rot=90)
        y = max(b.bbox(f"R{rb + 4}")[3], b.bbox(f"C{rb + 1}")[3]) + 0.4
    # 右外側: ゲート抵抗・プルダウン・0.1µF を J2 の HOx の高さに合わせて並べる
    for i in (3, 2, 1, 0):
        rb = 30 + 10 * i
        yh = b.pad_xy("J2", str(15 - 3 * i))[1]                             # J2-6 = HO3 … J2-15 = HO0
        row = [f"R{rb}", f"R{rb + 2}", f"R{rb + 1}", f"R{rb + 3}", f"C{rb}"]
        b.pack(row, zl1, yh - 1.0, zr1, rot=90)
    # ---- 下面 (ヒートシンク側): MOSFET 3 列 x 3 段 ----
    B = "B"
    cols = (0.3, BOFF + PIN_X[0] + 1.15, BOFF + PIN_X[1] + 1.15)      # 各列の左端
    # (列, 段): レッグ 3 = 左列, 2 = 右列, 1 = 中央列 (上 2 段), 0 = 最下段の左右 (J2-15〜17 と J4 に近い)
    slots = {"Q7": (0, 0), "Q8": (0, 1), "Q5": (2, 0), "Q6": (2, 1),
             "Q3": (1, 0), "Q4": (1, 1), "Q1": (0, 2), "Q2": (2, 2)}
    rows_y = (0.4, 17.9, 35.4)
    for q, (c, r) in slots.items():
        put(b, q, cols[c], rows_y[r], rot=90, side=B)
    # 中央下段: バスシャント, 電流チャネル選択, 相電圧分圧, NTC
    y = rows_y[2]
    cx0, cx1 = cols[1], BOFF + PIN_X[1] - 1.15
    put(b, "R70", cx0, y, side=B)
    put(b, "TH1", b.bbox("R70")[2] + 0.3, y, side=B)
    y = b.bbox("R70")[3] + 0.3
    put(b, "JP5", cx0, y, rot=90, side=B)
    put(b, "JP7", b.bbox("JP5")[2] + 0.3, y, rot=90, side=B)
    y = b.bbox("JP5")[3] + 0.3
    b.pack(["R71", "R72", "C71", "R74", "R75", "C72", "R77", "R78", "C73"], cx0, y, cx1,
           rot=90, side=B, gap=0.2, row_gap=0.25)
    # U4 (LM74700) の EN (3) は ANODE (6) = VIN_F と同電位。IC の腹下を先に結んでおく (外側からは入れないため)
    pre_route(b, "U4", ["3", ("3", "4"), ("6", "1"), "6"], 0.25)
    for ref, txt in (("J3", "VIN / GND"), ("J4", "OUT0  OUT1  OUT2  OUT3")):
        l, t, r, bt = b.bbox(ref)
        b.text(txt, (l + r) / 2, t - 0.6, 0.7)
    return finish(b, route, silk=[("mPB PWR-B", W / 2, 54.3, 0.7)], outside_ok={"J4", "J1", "J2"},
                  fr_opts=FR_OPTS)


# ---------------------------------------------------------------------------
def finish(b, route, silk=(), zones_hicur=(), fr_opts=(), outside_ok=()):
    bad, missing, outside = b.check_overlaps()
    outside = [r for r in outside if r not in outside_ok]
    print(f"[{b.name}] overlaps={bad} missing={sorted(missing)} outside={outside}")
    b.outline()
    b.edge_keepout()
    for item in silk:
        b.text(*item[:4], layer=item[4] if len(item) > 4 else "F.SilkS")
    if route:
        b.reload()   # ネットクラス (プロジェクトのパターン割当) を有効にしてから DSN を書き出す
        t, v = b.autoroute(reuse=REUSE, opts=fr_opts)
        print(f"[{b.name}] routed: tracks={t} vias={v}")
        b.reload()   # 取り込んだ配線をファイル経由で読み直す (メモリ上のままだと DRC が落ちることがある)
        nu = sum(x.startswith("[unconnected_items]") for x in b._drc_items())
        if nu and not os.environ.get("MPB_NO_PASS2"):   # 残りがあれば, 配線済みの状態から Freerouting をもう一度 (引き剥がし再配線)
            b.second_pass(passes=int(os.environ.get("MPB_FR_PASSES2", "60")), opts=fr_opts)
            b.reload()
            nu2 = sum(x.startswith("[unconnected_items]") for x in b._drc_items())
            print(f"[{b.name}] second pass: unconnected {nu} -> {nu2}")
        # ベタを入れる前 (経路が空いているうち) に残りを補修する。GND は後のベタでつながるので対象外
        early = b.repair_unrouted(skip_nets=("GND",))
        if early:
            print(f"[{b.name}] repaired before pours: {early}")
        g = b.grow_zones(list(b.assign_hicur()) + list(getattr(b, "grow_extra", [])))
        print(f"[{b.name}] grown power zones: {g}")
    for net, layer, pts in zones_hicur:
        b.zone(net, layer, pts, priority=2)
    ol = [(0.3, 0.3), (b.W - 0.3, 0.3), (b.W - 0.3, b.H - 0.3), (0.3, b.H - 0.3)]
    b.zone("GND", "F.Cu", ol, priority=0)
    b.zone("GND", "B.Cu", ol, priority=0)
    b.reload()
    b.fill()
    if route:
        n = b.stitch()
        n2 = sum(b.stitch(net=net, pitch=1.3, dia=1.0, drill=0.5, margin=0.25) for net in ("VBUS", "VIN_F", "USB_VBUS_P")
                 if net in b.nets and net in b.assign_hicur())
        b.fill()
        print(f"[{b.name}] stitching vias: GND {n}, power {n2}")
        ni = b.stitch_islands()
        if ni:
            b.fill()
            print(f"[{b.name}] island stitching vias: {ni}")
        fixed = b.repair_unrouted()
        if fixed:
            b.fill()
            print(f"[{b.name}] repaired unrouted connections: {fixed}")
    nd = b.drop_floating_islands()
    if nd:
        print(f"[{b.name}] removed floating copper islands: {nd}")
    npr = b.prune_isolated_pieces()
    if npr:
        print(f"[{b.name}] removed redundant isolated copper pieces: {npr}")
    ndv = b.remove_dangling_vias()
    if ndv:
        print(f"[{b.name}] removed dangling vias: {ndv}")
    path = b.save()
    kinds, unconn, rpt = b.drc()
    print(f"[{b.name}] DRC: {kinds} unconnected={unconn} ({os.path.relpath(rpt, pcblib.HERE)})")
    render(path, b)
    return b


def render(path, b):
    """TOP / BOTTOM の図を docs/pcb/ に出力 (kicad-cli svg → Chromium で PNG)."""
    out = os.path.join(pcblib.HERE, "..", "docs", "pcb")
    os.makedirs(out, exist_ok=True)
    for side, layers in (("top", "F.Cu,F.SilkS,F.Mask,Edge.Cuts"), ("bottom", "B.Cu,B.SilkS,B.Mask,Edge.Cuts")):
        svg = os.path.join(out, f"{b.name}_{side}.svg")
        cmd = ["kicad-cli", "pcb", "export", "svg", "--layers", layers, "--exclude-drawing-sheet",
               "--page-size-mode", "2", "-o", svg, path]
        if side == "bottom":
            cmd.insert(4, "--mirror")
        subprocess.run(cmd, check=True, capture_output=True)
        w = 1400
        h = int(w * (b.H + 4) / (b.W + 4))
        subprocess.run([os.path.join(pcblib.HERE, "tools", "svg2png.sh"), svg, svg[:-4] + ".png", str(w), str(h)],
                       check=False)
    return out


BOARDS = ((".", "mPBCH32M030DS0"), ("daughter/PWR_A", "mPBCH32M030DS0_PWR_A"),
          ("daughter/PWR_B", "mPBCH32M030DS0_PWR_B"), ("daughter/PWR_C", "mPBCH32M030DS0_PWR_C"))


def fab():
    """製造データ: hardware/fab/<基板名>/ にガーバー・ドリル・部品座標 (両面) を出力し zip にまとめる."""
    import shutil
    for d, name in BOARDS:
        pcb = os.path.join(pcblib.HERE, d, name + ".kicad_pcb")
        out = os.path.join(pcblib.HERE, "fab", name)
        shutil.rmtree(out, ignore_errors=True)
        os.makedirs(out)
        layers = "F.Cu,B.Cu,F.Paste,B.Paste,F.Silkscreen,B.Silkscreen,F.Mask,B.Mask,Edge.Cuts"
        subprocess.run(["kicad-cli", "pcb", "export", "gerbers", "--layers", layers, "--subtract-soldermask",
                        "-o", out + "/", pcb], check=True, capture_output=True)
        subprocess.run(["kicad-cli", "pcb", "export", "drill", "--format", "excellon", "--excellon-separate-th",
                        "--generate-map", "--map-format", "pdf", "-o", out + "/", pcb], check=True, capture_output=True)
        subprocess.run(["kicad-cli", "pcb", "export", "pos", "--format", "csv", "--units", "mm", "--side", "both",
                        "-o", os.path.join(out, name + "-pos.csv"), pcb], check=True, capture_output=True)
        shutil.make_archive(out, "zip", out)
        print("fab:", os.path.relpath(out + ".zip", pcblib.HERE))


ERRORS = ("clearance", "shorting_items", "tracks_crossing", "unconnected_items", "copper_edge_clearance",
          "hole_clearance", "hole_near_hole", "drill_out_of_range", "track_width", "via_diameter",
          "annular_width", "starved_thermal", "courtyards_overlap", "malformed_courtyard", "invalid_outline")


def summarize():
    """各基板の DRC レポートを docs/pcb/drc_summary.md にまとめる."""
    import re
    rows = []
    for d, name in BOARDS:
        rpt = os.path.join(pcblib.HERE, d, "build", name + "_drc.rpt")
        if not os.path.exists(rpt):
            continue
        txt = open(rpt, encoding="utf-8").read()
        kinds = {}
        for m in re.finditer(r"^\[(\w+)\]:", txt, re.M):
            kinds[m.group(1)] = kinds.get(m.group(1), 0) + 1
        err = {k: v for k, v in kinds.items() if k in ERRORS}
        warn = {k: v for k, v in kinds.items() if k not in ERRORS and k != "lib_footprint_issues"}
        fmt = lambda dct: ", ".join(f"{k} {v}" for k, v in sorted(dct.items())) or "なし"
        rows.append(f"| {name} | {fmt(err)} | {fmt(warn)} |")
    out = os.path.join(pcblib.HERE, "..", "docs", "pcb", "drc_summary.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("# DRC 結果 (KiCad 8 pcbnew, gen_pcb.py 実行時に自動生成)\n\n"
                "ルール: 2 層 / 最小線幅・間隙 0.127mm / ビア 0.6mm (穴 0.3mm, 大電流 0.8mm, QFN サーマルビア 0.2mm) / 基板端 0.25mm。\n"
                "「lib_footprint_issues」(ライブラリ照合) はスクリプト生成のため対象外。\n\n"
                "| 基板 | 電気的エラー (配線・間隙・未接続など) | 警告 (シルク等, 製造時にクリップされるもの) |\n|---|---|---|\n")
        f.write("\n".join(rows) + "\n")
    return out


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "main"
    if what in ("fab", "summary"):
        fab() if what == "fab" else print(summarize())
        sys.exit(0)
    route = "--no-route" not in sys.argv
    REUSE = "--reroute" not in sys.argv   # 配置が変わっていなければ前回の配線結果 (build/*.ses) を使う
    if what in ("main", "all"):
        build_main(route)
    for k in ("A", "B", "C"):
        if what in (k, "all"):
            build_daughter(k, route)
    print(summarize())
