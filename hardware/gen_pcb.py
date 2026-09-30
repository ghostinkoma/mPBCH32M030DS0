#!/usr/bin/env python3
"""
mPBCH32M030DS0 Rev 0.4 の基板 (2 層) を生成する。KiCad 8 (pcbnew 8.0.x) の Python で実行する。

  python3 gen_schematic.py                 # 先に parts.json を作る
  python3 gen_pcb.py [main|A|B|C|all] [--no-route] [--reroute]
  python3 gen_pcb.py fab                   # 製造データ (hardware/fab/*.zip)
  python3 gen_pcb.py summary               # docs/pcb/drc_summary.md を更新
  python3 gen_pcb.py nopour                # ベタなし版 (hardware/nopour/)
  python3 gen_pcb.py zone_edge             # 配線済みの基板のベタだけを基板端から 1.0mm 離して塗り直す

構成 (上から見た座標, 原点 = 左上):
  MCU モジュール  22.86 x 53.34mm (9 x 21 マス)。左右端に 21 ピン x 2 列 (x = 2.54 / 20.32, 列間 17.78mm)
                  → ブレッドボードに直接挿せる。USB-C は上端。LED・スイッチ・ジャンパは上面。
  パワー段子基板  モジュールと同じ位置に 1x21 ピンソケット x2 (上面, 左右対称)。モジュールは上から挿す。
                  MOSFET・シャント等は下面 (ヒートシンク側)。電源入力 J3 / モータ出力 J4 は下端。
"""
import math
import os
import subprocess
import sys

import pcblib
from pcblib import Pcb

REUSE = True
FR_OPTS_MAIN = tuple(os.environ.get("MPB_FR_OPTS", "-us hybrid -hr 1:1").split())   # Freerouting の追加オプション
FR_OPTS = tuple(os.environ.get("MPB_FR_OPTS_D", "").split())                           # 子基板 (試行で hybrid より良好)
# 幅は 9 マス (22.86mm, 端子列 0.7in = Pico と同じ列間隔)。
# (旧 8 マス版 20.32mm は 2 層標準 0.127mm で配線しきれず廃止。部品配置の座標は 20.32mm 幅基準で書き, 横に比例して広げる)
VAR = ""
MW, MH = 22.86, 53.34          # モジュール外形
PIN_X = (2.54, MW - 2.54)      # DIP 端子列の x
XL, XR = PIN_X[0] + 1.91, PIN_X[1] - 1.88         # 端子列の内側で部品を置ける範囲
PIN_Y0 = 1.27                  # 1 番ピンの y


def hicur_daughter(b):
    """子基板の大電流ネット: 自動配線は 0.3mm で通し (SOT-23-6 の LM74700 や ソケット端子の間も抜けられる),
    後でベタで太らせる (grow_zones)."""
    hw = float(os.environ.get("MPB_HC_W", "0.3"))
    b.classes["HiCur"].SetTrackWidth(pcblib.MM(hw))
    b.classes["HiCur"].SetClearance(pcblib.MM(0.15 if hw < 0.5 else 0.2))
    b.classes["HiCur"].SetViaDiameter(pcblib.MM(0.8))
    b.classes["HiCur"].SetViaDrill(pcblib.MM(0.4))
    motor = [f"SW{i}" for i in range(4)] + [f"SRC{i}" for i in range(4)]
    b.netclass("HiCur", ["VBUS", "VIN", "VIN_F", "ISH", "USB_VBUS", "USB_VBUS_P"] +
               (motor if os.environ.get("MPB_HC_ALL") else []))
    # 相出力・ローサイドのソース (モータ電流) は通常の太さで配線し (配線しやすさ優先), 後でベタで太らせる
    b.grow_extra = motor
    b.widen = ([f"SW{i}" for i in range(4)] + [f"SRC{i}" for i in range(4)] +
               ["ISH", "VBUS", "VIN", "VIN_F", "GND", "USB_VBUS", "USB_VBUS_P"])


def prj(prjdir):
    """出力先のプロジェクトフォルダ。VAR があれば回路図一式をその下へ写し, ライブラリの相対パスを直す."""
    if not VAR:
        return prjdir
    import glob
    import shutil
    src = os.path.join(pcblib.HERE, prjdir)
    dst = os.path.join(pcblib.HERE, VAR + prjdir)
    os.makedirs(dst, exist_ok=True)
    for f in (glob.glob(os.path.join(src, "*.kicad_sch")) + glob.glob(os.path.join(src, "*.kicad_pro")) +
              [os.path.join(src, n) for n in ("parts.json", "expected_nets.txt", "bom.csv")]):
        if os.path.exists(f) and not (f.endswith(".kicad_pro") and os.path.exists(os.path.join(dst, os.path.basename(f)))):
            shutil.copy(f, dst)
    for n in ("fp-lib-table", "sym-lib-table"):
        if os.path.exists(os.path.join(src, n)):
            txt = open(os.path.join(src, n), encoding="utf-8").read().replace("${KIPRJMOD}/", "${KIPRJMOD}/../")
            open(os.path.join(dst, n), "w", encoding="utf-8").write(txt)
    return VAR + prjdir


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
    b = Pcb(prj("."), MW, MH, "mPBCH32M030DS0 MCU module (DIP-42, CH32M030C8U7)", rev="0.4")
    b.classes["HiCur"].SetTrackWidth(pcblib.MM(0.3))                    # 自動配線は細く通し, 後でベタで太らせる
    b.classes["HiCur"].SetClearance(pcblib.MM(0.15))
    b.netclass("HiCur", HICUR_MAIN)
    dflt = b.b.GetDesignSettings().m_NetSettings.m_DefaultNetClass
    # JLCPCB の 2 層標準の最小値 (線幅・間隙 0.127mm, ビア 0.6/0.3)。試行用に MPB_RULE / MPB_VIA で変えられる
    rule = float(os.environ.get("MPB_RULE", "0.127"))
    via = [float(v) for v in os.environ.get("MPB_VIA", "0.6,0.3").split(",")]
    ds = b.b.GetDesignSettings()
    ds.m_TrackMinWidth = ds.m_MinClearance = pcblib.MM(rule)
    dflt.SetTrackWidth(pcblib.MM(rule))
    dflt.SetClearance(pcblib.MM(rule))
    dflt.SetViaDiameter(pcblib.MM(via[0]))
    dflt.SetViaDrill(pcblib.MM(via[1]))
    # ---- 端子: ピンヘッダは下面に実装し, ピンを MCU と反対側 (下) へ出す (ブレッドボード・ソケットへ挿しても
    #      USB-C とボタンが上に来る)。穴の位置は表裏で同じなので, 配線は表に置いた状態で行い (前回の配線を再利用),
    #      配線の後で下面へ裏返す (finish の flip_after_route)
    b.place("J1", PIN_X[0], PIN_Y0)
    b.place("J2", PIN_X[1], PIN_Y0)
    b.flip_after_route = ("J1", "J2")
    # ---- USB (上面) ----
    put_c(b, "J8", MW / 2, 3.7, rot=180)                  # USB-C: 差込口は上端
    put(b, "U3", 4.45, 8.6)
    put(b, "SW1", 10.95, 8.5)
    put_c(b, "U1", MW / 2, 19.6)                          # ゲートピン → 右列 J2, USB/アナログ → 左列 J1
    put(b, "Y1", 7.2, 23.2)
    yj = b.pack(["JP2", "JP3", "JP4", "JP8"], 4.45, 27.0, 7.1, rot=90, row_gap=0.3)
    # QFN の真下は小物だけ (USER/BOOT と電源 LED) にして, 下辺・左辺の信号が下半分へ抜ける通り道を残す
    put(b, "SW2", 7.4, 27.4)
    yl = b.pack(["D7", "R4", "D2", "R3", "D8", "R5", "D3", "R112"], 7.4, b.bbox("SW2")[3] + 0.3, 12.2, rot=90, gap=0.2)
    # ゲート確認 LED は右下 (y ≥ 38) に 3 列。QFN 右辺のゲートピン → J2 の引き出しを塞がない
    b.pack(["R50", "D10", "R51", "D11", "R52", "D12", "R53", "D13",
            "R54", "D14", "R55", "D15", "R56", "D16", "R57", "D17"],
           b.bbox("J2")[0] - 0.05 - 3.85, 38.3, b.bbox("J2")[0] - 0.05,
           rot=90, gap=0.15, row_gap=0.2)
    # VHV 保護・USB 給電のダイオードと PTC は下端の帯へ (大電流のベタが中央の通り道を塞がないように)
    b.pack(["D5", "D6", "D4", "F2"], 7.4, yl + 0.3, 12.2, rot=0, row_gap=0.25)
    # ---- 下面 (高さ ≤2mm の CR) ----
    B = "B"
    # MCU の電源ピン (VHV/VDD8/VDD33) は上辺 → 容量は MCU の上側の裏。裏面パッドのサーマルビア直下は空ける
    y = b.pack(["R7", "R8", "C7", "R130", "C130", "R131", "C133"], 4.45, 8.4, 13.3, side=B)
    y = b.pack(["C10", "C12"], 4.45, y + 0.2, 13.3, side=B)
    b.pack(["C14", "C11", "C13", "C15"], 4.45, y + 0.2, 13.3, side=B)
    b.pack(["C21", "C22", "C23", "C24"], 13.45, 12.2, 15.95, rot=90, side=B)              # ブートストラップ
    # 電流アンプ入力 RC は J1 の ISA_SEL / ISH / ISB_SEL の近く (下側) へ。QFN の周りはビアで引き出せるよう空ける
    # QFN 下辺ピンの真下 (y 22〜25) は両面とも空けてビアで引き出せるようにする。水晶の負荷容量だけ近くに置く
    b.pack(["C131", "C132"], 7.0, 25.6, 13.4, side=B)
    b.pack(["R100", "R101", "C100", "R103", "R104", "C101", "R106", "R107", "C102"], 4.45, 34.6, 10.2, rot=90, side=B)
    b.pack(["R123", "C105", "C103", "R110", "R111", "R114", "R115", "R120", "R122"], 10.6, 34.6, 15.9, rot=90, side=B)
    ya = max(b.bbox(r)[3] for r in ("R100", "C102", "R123", "R122")) + 0.6
    b.pack(["R16", "R17", "C19", "R18", "R19", "C20"], 4.45, ya, 10.2, rot=90, side=B)         # 電流アンプ入力
    b.pack(["R13", "C17", "R14", "R15", "C18", "C16", "R10"], 10.6, ya, 15.9, rot=90, side=B)  # IBUS, OCP 基準, VBUS 監視
    if True:   # 20.32mm 幅基準の配置を横方向に比例して広げる (ゲート確認 LED 群は J2 に寄せて置いてある)
        k = float(os.environ.get("MPB_W9K", MW / 20.32))              # 横方向の倍率 (試行用に変えられる)
        off = pcblib.MM(float(os.environ.get("MPB_W9OFF", "0")))         # 横方向のずらし量 (mm)
        gl = {f"R{50 + i}" for i in range(8)} | {f"D{10 + i}" for i in range(8)}
        for ref, fp in b.fps.items():
            if ref not in ("J1", "J2") and ref not in gl:
                p = fp.GetPosition()
                fp.SetPosition(pcblib.pcbnew.VECTOR2I(int(p.x * k) + off, p.y))
    if True:   # 水晶は XI/XO (QFN 下辺の 8/9 番ピン) の真下の裏面へ。表の下辺ピン 1〜7 の引き出しを空ける
        x89 = (b.pad_xy("U1", "8")[0] + b.pad_xy("U1", "9")[0]) / 2
        put_c(b, "Y1", x89 - 0.45, 24.5, rot=90, side="B")
        yb = b.bbox("Y1")[3] + 0.25
        b.pack(["C131", "C132"], b.bbox("Y1")[0], yb, b.bbox("Y1")[2] + 0.4, side="B", gap=0.25)
    # nFAULT (TIM1 BKIN) のノイズ対策 1nF: nFAULT の配線沿いで空いている裏面の位置 (MCU の 2 番ピンから 5mm)
    put_c(b, "C120", 10.15, 26.93, rot=90, side="B")
    # 信号名は下面 (ピンヘッダの樹脂 = ピン中心から 1.27mm の外側), ピン番号は上面 (MCU 側) の外縁
    pin_labels(b, [("J1", gs.PINMAP_L, +1), ("J2", gs.PINMAP_R, -1)], "B.SilkS", 1.5)
    for ref, xn in (("J1", 0.95), ("J2", MW - 0.95)):
        for n in range(1, 22):
            b.text(str(n), xn, b.pad_xy(ref, str(n))[1], 0.6, layer="F.SilkS")
    return finish(b, route, silk=[("mPB CH32M030", MW / 2, MH - 3.4, 0.8, "B.SilkS"),
                                  ("ghostinkoma/mPBCH32M030DS0", MW / 2, MH - 1.8, 0.6, "B.SilkS")],
                  outside_ok={"J8", "J1", "J2"}, fr_opts=FR_OPTS_MAIN)


# ---------------------------------------------------------------------------
# パワー段子基板 A / C (幅 = モジュールと同じ 22.86mm)
# ---------------------------------------------------------------------------
AC_H = float(os.environ.get("MPB_AC_H", "74.9"))   # 子基板 A / C の長さ (面付けで 100mm 枠に収まる上限 ≒75)
LEG_Y0 = {"A": float(os.environ.get("MPB_A_LEGY", "12.0")), "C": float(os.environ.get("MPB_C_LEGY", "16.0"))}


def build_daughter(key, route=True):
    """子基板 A / C (幅 = モジュールと同じ 22.86mm)。
    電源入力 J3 は左, モータ出力 J4 は右に縦置き (モジュールの下端より下)。レッグは下面でモジュールの真下の
    下寄りに積み, 相出力 (SW) が J3 をまたがずに J4 へ届くようにする。入力の F1 / Q9 / U4 は J3 のすぐ横."""
    import gen_schematic as gs
    if key == "B":
        return build_daughter_b(route)
    if key in ("A", "C") and not os.environ.get("MPB_AC_OLD"):
        return build_daughter_a(route, key)
    W, H = MW, AC_H
    b = Pcb(prj(f"daughter/PWR_{key}"), W, H, f"mPBCH32M030DS0 power board {key}", rev="0.4")
    hicur_daughter(b)
    # ---- 上面: ソケット, 縦置きの J3 (左) / J4 (右) ----
    b.place("J1", PIN_X[0], PIN_Y0)
    b.place("J2", PIN_X[1], PIN_Y0)
    yc = MH + 2.39                                      # J3 / J4 の 1 番ピン (ソケットと courtyard が重ならない位置)
    b.place("J3", PIN_X[0], yc)                         # 2x6: 1-6 = VIN (上 3 段), 7-12 = GND (下 3 段)
    b.place("J4", PIN_X[1] - 2.54, yc)                  # 2x8: OUT0 (上) … OUT3 (下)
    jl, jr = b.bbox("J3")[2] + 0.25, b.bbox("J4")[0] - 0.25   # J3 と J4 の間
    # モジュールの真下 (上から): USB-PD 経路・78L05 → バルク容量 → VBUS 分圧 → TVS / 10µF
    rows = ([["F3", "Q10"], ["D9", "C6", "R6"], ["U5", "C3", "C4"], ["U2"]] +
            [[r] for r in ("C7", "C8", "C9") if r in b.fps] + [["R11", "R12"], [("D1", 90), ("C1", 90)]])
    y = 0.6
    for row in rows:
        x = XL
        rowb = y
        for it in row:
            ref, rot = it if isinstance(it, tuple) else (it, 0)
            put(b, ref, x, y, rot=rot)
            l, t, r, bt = b.bbox(ref)
            x = r + 0.25
            rowb = max(rowb, bt)
        y = rowb + 0.7
    # 電源入力: J3 の VIN (上 3 段) → F1 (縦) → Q9 → VBUS。LM74700 (U4) と C5 は Q9 の下
    put(b, "F1", jl, yc - 1.0, rot=90)
    put(b, "Q9", jl, b.bbox("F1")[3] + 0.3, rot=90)
    b.pack(["U4", "C5"], jl, b.bbox("Q9")[3] + 0.3, jl + 7.0, gap=0.25)
    # ---- 下面 (ヒートシンク側): 4 レッグをモジュールの真下の下寄りに ----
    B = "B"
    y = LEG_Y0[key]
    for i in (3, 2, 1, 0):         # J2 のゲートピンの並び (上から HO3 … LO0) に合わせる
        rb = 30 + 10 * i
        y = b.pack([f"Q{1 + 2 * i}", f"Q{2 + 2 * i}"], XL, y, XR, side=B, gap=0.4)
        put(b, f"R{rb + 4}", XL, y + 0.2, side=B)                          # シャント (1206)
        put(b, f"C{rb + 1}", b.bbox(f"R{rb + 4}")[2] + 0.25, y + 0.2, rot=90, side=B)
        y = max(b.bbox(f"R{rb + 4}")[3], b.bbox(f"C{rb + 1}")[3])
        row = [f"C{rb}", f"R{rb + 1}", f"R{rb + 3}", f"R{rb + 2}", f"R{rb}"]
        yr = y + 0.3
        y = b.pack(row, XL, yr, XR, rot=90, side=B)
        shift_right(b, row, XR, side=B, rot=90)
        extra = {1: ["TH1"]}.get(i, [])
        if extra:
            y = max(y, b.pack(extra, XL, yr, b.bbox(row[0])[0] - 0.2, rot=90, side=B, gap=0.15))
        y += 0.6
    # J3 と J4 の間 (下面): バスシャント, 電流チャネル選択, 相電圧分圧
    y = max(y, yc - 1.2)
    put(b, "R70", jl, y, rot=90, side=B)
    x = b.bbox("R70")[2] + 0.3
    put(b, "JP5", x, y, rot=90, side=B)
    put(b, "JP7", b.bbox("JP5")[2] + 0.3, y, rot=90, side=B)
    b.pack(["R71", "R72", "C71", "R74", "R75", "C72", "R77", "R78", "C73"], x, b.bbox("JP5")[3] + 0.3, jr,
           rot=90, side=B, gap=0.15, row_gap=0.2)
    for ref, txt in (("J3", "VIN"), ("J4", "OUT0-3")):
        l, t, r, bt = b.bbox(ref)
        b.text(txt, (l + r) / 2, bt + 0.6, 0.6)
    return finish(b, route, silk=[(f"mPB PWR-{key}", W / 2, H - 1.4, 0.7)],
                  outside_ok={"J4", "J1", "J2", "J3"}, fr_opts=FR_OPTS)


# ---- 子基板 A: 電源の銅箔を手で決める (約 5A / 相, 1oz) ----
# レッグ = 下面に LS (上, 0°) / HS (下, 180°) を縦に積んだブロック。左列 = SRC (LS ソース) と VBUS (HS ドレイン) が
# 上下に並ぶので 10µF をその間に最短で渡せ, 右列 = SW (LS ドレイン + HS ソース)。ブロックの左は ISH の背骨 (下面),
# 右 (J2 寄り) はゲート抵抗と J2 から来るゲート配線の場所。上面は VBUS の縦帯と, 各相の SW を J4 へ運ぶ階段状の帯。
A_XC = 11.3                                          # レッグブロック (MOSFET) の中心 x
A_LSY = {3: 13.16, 2: 22.16, 1: 31.16, 0: 40.16}     # LS の中心 y (J2 の HOi/SWi/LOi の並びに合わせる)
A_DY = 3.82                                          # LS → HS の中心間
A_SW_LANE = {3: (17.45, 19.2), 2: (15.4, 17.15), 1: (13.35, 15.1), 0: (11.3, 13.05)}   # 上面の SW 帯 (x)
A_VBUS_LANE = (8.0, 11.0)
C_DY = 3.7                                           # 子基板 C (SOT-23): HS → LS の中心間


def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def build_daughter_a(route=True, key="A"):
    W, H = MW, AC_H
    b = Pcb(prj(f"daughter/PWR_{key}"), W, H, f"mPBCH32M030DS0 power board {key}", rev="0.4")
    hicur_daughter(b)
    b.widen, b.grow_extra = None, []
    B = "B"
    b.place("J1", PIN_X[0], PIN_Y0)
    b.place("J2", PIN_X[1], PIN_Y0)
    yc = MH + 2.39
    b.place("J3", PIN_X[0] + 2.54, yc + 12.7, rot=180)     # 180°: GND (7-12) が上 3 段, VIN (1-6) が下 3 段
    b.place("J4", PIN_X[1], yc + 17.78, rot=180)           # 180°: OUT3 が上, OUT0 が下 (SW 帯が交差しない順)
    # ---- レッグ (下面) ----
    for i in range(4 if key == "A" else 0):
        rb = 30 + 10 * i
        ly, hy = A_LSY[i], A_LSY[i] + A_DY
        b.place(f"Q{2 + 2 * i}", A_XC, ly, 0, B)           # LS: ピン (SRC, G 左上) 左, ドレイン (SW) 右
        b.place(f"Q{1 + 2 * i}", A_XC, hy, 180, B)         # HS: ドレイン (VBUS) 左, ピン (SW, G 右下) 右
        b.place(f"R{rb + 4}", 6.7, ly - 0.75, 180, B)      # シャント: SRC 右, ISH 左 (背骨)
        put_c(b, f"C{rb + 1}", 7.95, ly + 2.2, rot=-90, side=B)  # 10µF: 上 = SRC, 下 = VBUS
        put_c(b, f"C{rb}", 6.4, ly + 2.2, rot=-90, side=B)       # 0.1µF
        put_c(b, f"R{rb + 3}", 8.1, ly - 2.74, rot=180, side=B)  # GL-SRC 20k (ブロック上の隙間, SRC 左)
        # J2 の並び (HO / SW / LO) と MOSFET のゲート (LS 上 / HS 下) は上下が逆なので, 0805 のゲート抵抗を
        # SW ピンの高さに縦置きし, その電極間を SW と GL が通る (配線の交差を部品の下でかわす)
        ysw = PIN_Y0 + 2.54 * (5 + 3 * (3 - i))                   # J2 の SWi ピン
        put_c(b, f"R{rb}", 15.6, ysw, rot=90, side=B)            # HO 47R (上 = HO, 下 = GH)
        put_c(b, f"R{rb + 2}", 17.7, ysw, rot=-90, side=B)       # LO 47R (上 = GL, 下 = LO)
        put_c(b, f"R{rb + 1}", 14.1, hy, rot=-90, side=B)        # GH-SW 20k (上 = SW, 下 = GH)
    for i in range(4 if key == "C" else 0):   # C: SOT-23。HS (180°, 上: D 左 / G 右上 / S 右下) → LS (270°, 下: D 上 / S 左下 / G 右下)
        rb = 30 + 10 * i
        hy = A_LSY[i]
        ly = hy + C_DY
        b.place(f"Q{1 + 2 * i}", A_XC, hy, 180, B)
        b.place(f"Q{2 + 2 * i}", A_XC, ly, 270, B)
        b.place(f"R{rb + 4}", 6.7, ly + 1.3, 180, B)               # シャント: SRC 右, ISH 左
        put_c(b, f"C{rb + 1}", 8.3, hy + 1.85, rot=90, side=B)     # 10µF: 上 = VBUS, 下 = SRC
        put_c(b, f"C{rb}", 6.6, hy + 2.2, rot=90, side=B)          # 0.1µF (VBUS / SRC のベタの境目をまたぐ)
        put_c(b, f"R{rb + 3}", 11.25, ly + 2.5, rot=180, side=B)   # GL-SRC 20k (LS の下, SRC 左)
        put_c(b, f"R{rb}", 14.5, hy - 0.9, rot=90, side=B)         # HO 47R
        put_c(b, f"R{rb + 1}", 15.6, hy - 0.1, rot=90, side=B)     # GH-SW 20k (GH と SW の配線の間)
        put_c(b, f"R{rb + 2}", 14.5, ly + 0.9, rot=90, side=B)     # LO 47R
    # ---- USB-PD 経路 (下面, レッグより上) と バルク容量 (上面, レッグより上) ----
    put(b, "F3", 5.4, 0.6, rot=0, side=B)
    put(b, "Q10", b.bbox("F3")[2] + 0.25, 0.6, rot=0, side=B)
    put(b, "C3", b.bbox("Q10")[2] + 0.2, 0.6, rot=90, side=B)
    put(b, "C4", b.bbox("C3")[0], b.bbox("C3")[3] + 0.15, rot=90, side=B)
    put(b, "U5", 6.1, 4.75, rot=0, side=B)                   # EN (3 番) が J1 の 3 番 (PD_PWR_EN) の真横
    put_c(b, "C6", 8.2, 8.95, rot=0, side=B)                 # VCAP2 (U5 の 1 番) ↔ USB_VBUS_P (6 番) を U5 の真下で
    put_c(b, "R6", 5.2, 5.7, rot=90, side=B)                # PD_PWR_EN の 100k (U5 の左)
    put(b, "U2", b.bbox("U5")[2] + 0.75, 4.65, rot=0, side=B)          # U5 との間に Q10 ゲートのビア          # 78L05: +5V は上面の J1 横の通り道で 7 番へ
    put_c(b, "C7", (4.45 + 15.35) / 2, 4.72, rot=180)
    # ---- 電源入力 (上面, J3 と J4 の間) ----
    put_c(b, "Q9", 9.2, 56.6, rot=90)                      # ドレイン (VBUS) 上
    put_c(b, "F1", 9.2, 63.1, rot=90)                      # 上 = VIN_F, 下 = VIN
    put_c(b, "TH1", 6.1, 46.6, rot=90)                      # NTC は上面 (レッグ 0 の下, GND ベタの中)
    # 電流チャネル選択 (はんだジャンパ) は上面の J1 の横。SRC / ISH は下面のベタからビアで上げる
    put_c(b, "JP7", 6.0, A_LSY[0] + 2.4, rot=-90)   # 1 (SRC0) が上
    put_c(b, "JP5", 6.0, (A_LSY[1] + A_LSY[2]) / 2 + 0.3, rot=90)    # 1 (SRC1) が下 (レッグ 1 側)
    # ---- 下面の下部 (レッグ 0 の下, 部品置き場 x 6.2〜11.0) ----
    put_c(b, "R70", 4.75, 49.0, rot=90, side=B)            # ISH (上) → GND (下)
    if key == "A":                                           # VBUS 分圧 (横置き, 相電圧分圧の列の上)
        put_c(b, "R11", 9.3, 46.45, rot=0, side=B)           # 左 = VBUS
        put_c(b, "R12", 11.3, 46.45, rot=0, side=B)          # 右 = GND
    else:                                                    # C: LS の下の 20k と重ならないよう縦置き
        put_c(b, "R11", 9.0, 47.9, rot=90, side=B)           # 上 = VBUS
        put_c(b, "R12", 10.3, 47.9, rot=90, side=B)
    y = b.pack(["R72", "C71", "R75", "C72", "R78", "C73"], 6.3, 47.1, 8.5,
               rot=90, side=B, gap=0.1, row_gap=0.2)
    put(b, "U4", 6.3, 56.5, side=B)                         # 理想ダイオード IC (Q9 のゲートの真下の裏)
    put_c(b, "C5", 7.9, 60.75, rot=0, side=B)               # VCAP1 (U4 の 1 番) ↔ VIN_F
    y = b.pack(["D1"], 6.3, b.bbox("C5")[3] + 0.3, 10.9, rot=90, side=B)
    b.pack(["C1"], 6.3, y + 0.3, 12.2, side=B)
    # 相電圧分圧の 20k は SW の帯の縁 (SW0: 下面の帯 / SW1・SW2: 上面の帯からのビア) に置く
    dyb = 0.0 if key == "A" else 1.8                        # C: VBUS 分圧 (縦置き) の下を BEMF が通る
    put_c(b, "R71", 12.2, 47.6 + dyb, rot=180, side=B)      # 右 = SW0 (上面の SW0 帯からビア)
    put_c(b, "R74", 14.2, 48.7 + dyb, rot=180, side=B)      # 右 = SW1
    put_c(b, "R77", 16.3, 49.8 + dyb, rot=180, side=B)      # 右 = SW2 (3 本の BEMF は段違いで左へ)
    # ---- 電源の銅箔 (配線より先に置く。自動配線はこれを障害物として避ける) ----
    zs = []
    LANE_DY = -1.2 if key == "A" else 0.45

    def Z(net, layer, *r):
        zs.append((net, layer, rect(*r)))

    for i in range(4 if key == "C" else 0):
        hy = A_LSY[i]
        ly = hy + C_DY
        Z("VBUS", "B.Cu", 6.0, hy - 1.1, 11.15, hy + 2.2)               # HS D + 10µF/0.1µF の上
        Z(f"SRC{i}", "B.Cu", 6.0, hy + 2.6, 10.7, ly + 2.2)             # 10µF/0.1µF の下 + シャント + LS S
        Z(f"SRC{i}", "B.Cu", 9.5, ly + 1.6, 11.05, ly + 2.95)           # GL-SRC 20k の SRC 側
        Z(f"SW{i}", "B.Cu", 11.4, hy + 0.45, 13.9, ly - 0.15)           # HS S → LS D (+ ビア)
        Z(f"SW{i}", "B.Cu", 10.95, hy + 2.5, 13.9, ly - 0.15)
        Z(f"SW{i}", "B.Cu", 13.8, hy + 0.1, 15.95, hy + 0.95)            # GH-SW 20k の SW 側
        x0, x1 = A_SW_LANE[i]
        Z(f"SW{i}", "F.Cu", 11.3, hy + 0.45, x1, ly - 0.15)
    for i in range(4 if key == "A" else 0):
        ly, hy = A_LSY[i], A_LSY[i] + A_DY
        Z(f"SRC{i}", "B.Cu", 6.0, ly - 1.55, 9.0, ly + 1.9)             # シャント SRC 側 + 10µF/0.1µF の上
        Z(f"SRC{i}", "B.Cu", 9.0, ly - 0.55, 10.4, ly + 1.9)            # LS ピン 1-3 (G は避ける)
        Z(f"SRC{i}", "B.Cu", 6.0, ly - 3.2, 7.9, ly - 1.55)             # GL-SRC 20k の SRC 側
        Z("VBUS", "B.Cu", 6.0, ly + 2.3, 11.65, hy + 1.2)               # 10µF/0.1µF の下 + HS ドレイン
        Z(f"SW{i}", "B.Cu", 10.95, ly - 1.2, 13.7, ly + 1.2)            # LS ドレイン
        Z(f"SW{i}", "B.Cu", 12.1, ly + 1.2, 13.7, hy + 0.55)            # → HS ピン 1-3
        Z(f"SW{i}", "B.Cu", 11.9, ly + 1.2, 13.7, ly + 2.05)            # HS ピンの上のビア置き場
        Z(f"SW{i}", "B.Cu", 13.6, hy - 0.85, 14.4, hy - 0.1)            # GH-SW 20k の SW 側
        x0, x1 = A_SW_LANE[i]
        Z(f"SW{i}", "F.Cu", 11.3, ly - 1.2, x1, ly + 1.2)               # 上面: ビアから自分の帯へ
        Z(f"SW{i}", "F.Cu", 11.3, ly + 1.2, 13.05, hy + 0.55)           # HS 側のビアの上 (上面の帯へ逃がす)
    Z("ISH", "B.Cu", 3.5, 7.4, 5.9, 48.1)                               # ISH の背骨 (下面)
    Z("ISH", "F.Cu", 4.5, 5.0, 5.6, 8.4)                                # C7 (−) → 背骨 (J1 1-3 番の下面を空ける)
    Z("ISH", "B.Cu", 1.6, 43.6, 3.6, 45.3)                              # → J1 18 番 (ISH)
    Z("GND", "B.Cu", 3.5, 49.8, 6.1, 61.9)                              # R70 → J3 GND
    Z("GND", "B.Cu", 1.2, 54.6, 6.1, 61.9)
    Z("GND", "B.Cu", 1.6, 51.2, 3.6, 53.0)                              # → J1 21 番 (GND, USB の帰路)
    Z("VBUS", "F.Cu", A_VBUS_LANE[0], 6.2, A_VBUS_LANE[1], 57.0)        # 上面 VBUS 帯 (C7 → 全レッグ → Q9)
    Z("VBUS", "F.Cu", 9.3, 0.9, 15.95, 6.6)                             # C7 (+) と USB 経路の出口 (Q10 ドレイン)
    Z("VBUS", "F.Cu", 9.0, 6.6, 15.5, 10.4)                             # → VBUS 帯 (Q10 ゲート配線の脇を回る)
    Z("VBUS", "F.Cu", 7.4, 54.4, 11.0, 57.0)
    Z("VIN_F", "F.Cu", 7.4, 57.5, 9.85, 62.3)                           # Q9 ソース → F1
    Z("VIN", "F.Cu", 1.2, 62.4, 6.4, 69.6)                              # J3 VIN → F1
    Z("VIN", "F.Cu", 1.2, 62.4, 11.0, 67.3)
    # SW の帯 (上面) と J4 への取り付き
    Z("SW3", "F.Cu", 17.45, A_LSY[3] + LANE_DY, 19.2, 54.3)
    Z("SW3", "F.Cu", 16.9, 54.3, 21.86, 59.4)
    Z("SW2", "F.Cu", 15.4, A_LSY[2] + LANE_DY, 17.15, 53.9)
    Z("SW2", "F.Cu", 15.0, 53.6, 16.6, 59.7)
    Z("SW2", "F.Cu", 15.0, 59.7, 21.86, 64.5)
    Z("SW1", "F.Cu", 13.35, A_LSY[1] + LANE_DY, 15.1, 53.6)
    Z("SW1", "F.Cu", 11.3, 53.6, 14.7, 64.8)
    Z("SW1", "F.Cu", 11.3, 64.8, 21.86, 69.6)
    Z("SW0", "F.Cu", 11.3, A_LSY[0] + LANE_DY, 13.05, 53.0)
    Z("SW0", "B.Cu", 11.3, 51.3, 13.3, 53.4)                            # SW0 は下面で J4 の下段へ
    Z("SW0", "B.Cu", 12.6, 51.3, 15.2, 73.9)
    Z("SW0", "B.Cu", 11.3, 69.7, 21.86, 73.9)
    fixed_zones(b, zs)
    # 大電流のベタはレジストを開けてはんだを盛る (ハンダレベラー)。下面の MOSFET の範囲 (ヒートシンク) も開けるが,
    # そこは盛りを 0.3〜0.5mm 以下に抑える (MOSFET の高さ 1.0mm + 放熱シートより低く)
    b.solder_nets = {"VBUS", "ISH", "VIN", "VIN_F", "GND"} | {f"SW{i}" for i in range(4)} | {f"SRC{i}" for i in range(4)}
    # 自動配線に空ける縁の帯 (同ネットが外から取り付く所)。ISH の背骨と上面の SW 帯は外から来る同ネットが無いので 0
    b.ko_band = lambda net, layer: 0.0 if (net == "ISH" and layer == "B.Cu") or (net.startswith("SW") and layer == "F.Cu") else 0.3
    # ビア (上下の銅箔をつなぐ。0.6/0.3)
    vias = []
    for i in range(4 if key == "C" else 0):
        hy = A_LSY[i]
        vias += [("VBUS", x, hy + dy) for x in (8.0, 8.8, 9.6, 10.4) for dy in (-0.75,)]
        vias += [("VBUS", x, hy + 0.95) for x in (9.6, 10.4)]
        vias += [(f"SW{i}", x, hy + dy) for x in (12.15, 12.95) for dy in (1.75, 2.55)]
    for i in range(4 if key == "A" else 0):
        ly, hy = A_LSY[i], A_LSY[i] + A_DY
        vias += [("VBUS", x, hy + dy) for x in (9.75, 10.55) for dy in (-0.8, 0, 0.8)]      # HS ドレイン
        vias += [(f"SW{i}", x, ly + dy) for x in (11.75, 12.6) for dy in (-0.8, 0, 0.8)]   # LS ドレイン
        vias += [(f"SW{i}", x, ly + 1.62) for x in (12.15, 12.75)]                          # HS ソース側
    vias += [("SW0", x, y) for x in (11.75, 12.6) for y in (51.8, 52.5)]
    dyb = 0.0 if key == "A" else 1.8
    vias += [("SW0", 12.68, 46.75 + dyb), ("SW1", 14.68, 47.85 + dyb), ("SW2", 16.78, 48.95 + dyb)]   # 相電圧分圧のタップ
    vias += [("Q9_G", 10.85, 58.3)]                                                         # Q9 ゲート → U4 (裏)
    vias += [("VBUS", 10.6, 56.55)]                                                        # U4 の VBUS (4 番)
    # 電流チャネル選択 (上面 JP5/JP7) へ SRC0/1/2・ISH を上げるビア
    jy7, jy5 = b.pad_xy("JP7", "1")[1], b.pad_xy("JP5", "1")[1]
    src_y = {0: A_LSY[0] + (0.9 if key == "A" else 5.2), 1: A_LSY[1] + (0.9 if key == "A" else 5.2),
             2: A_LSY[2] + (0.9 if key == "A" else 5.2)}
    vias += [("SRC0", 6.9, src_y[0]), ("SRC1", 6.9, src_y[1]), ("SRC2", 6.9, src_y[2]), ("ISH", 4.7, A_LSY[0] + 4.3)]
    vias += [("ISH", 5.05, 7.85)]                                                          # C7 (−) → ISH の背骨
    vias += [("VBUS", x, y) for x in (14.9, 15.7) for y in (1.8, 2.9)]                   # Q10 ドレイン → VBUS
    vias += [("VBUS", 8.79, 45.7) if key == "A" else ("VBUS", 9.0, 46.3)]                # VBUS 分圧 R11
    vias += [("VIN_F", 9.45, 60.7)]                                                        # U4 (裏) の VIN_F
    for net, x, y in vias:
        b.via(net, x, y).SetLocked(True)
    def track(net, layer, pts, w=0.2):
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            if abs(x1 - x2) + abs(y1 - y2) < 1e-6:
                continue
            t = pcblib.pcbnew.PCB_TRACK(b.b)
            t.SetLocked(True)
            t.SetStart(pcblib.P(x1, y1))
            t.SetEnd(pcblib.P(x2, y2))
            t.SetWidth(pcblib.MM(w))
            t.SetLayer(pcblib.pcbnew.B_Cu if layer == "B" else pcblib.pcbnew.F_Cu)
            t.SetNet(b.net(net))
            b.b.Add(t)
    # Q10 のゲート (1 列の端 = 基板の縁側) へは U5 → ビア → 上面 → ビア で回る (USB_VBUS_P を横切らない)
    pg, p5g = b.pad_xy("Q10", "4"), b.pad_xy("U5", "5")
    b.via("Q10_G", 10.55, p5g[1]).SetLocked(True)
    b.via("Q10_G", 11.75, 1.3).SetLocked(True)
    track("Q10_G", "B", [p5g, (10.55, p5g[1])], w=0.2)
    track("Q10_G", "F", [(10.55, p5g[1]), (10.55, 1.3), (11.75, 1.3)], w=0.2)
    track("Q10_G", "B", [(11.75, 1.3), (pg[0] - 0.3, pg[1]), pg], w=0.2)
    # J1 9 番 (VBUS, モジュールの電源) は VBUS 帯から上面で (+5V の右を通る)
    track("VBUS", "F", [(A_VBUS_LANE[0] + 0.3, 12.6), (4.8, 12.6), (4.8, 21.0), (PIN_X[0], 21.59)], w=0.3)
    # GND: USB 経路の島 (J2 1 番) と下側 (J2 21 番) を, 基板右端 (J2 の外側) の上面でつなぐ
    track("GND", "F", [(PIN_X[1], PIN_Y0), (21.85, PIN_Y0 + 1.0), (21.85, PIN_Y0 + 50.0), (PIN_X[1], PIN_Y0 + 50.8)], w=0.4)
    # 78L05 の入力 (VBUS) は Q10 のドレインへ裏で直結
    p3, pd = b.pad_xy("U2", "3"), b.pad_xy("Q10", "5")
    track("VBUS", "B", [p3, (p3[0] + 0.6, 4.35), (pd[0] - 0.6, 4.35), (pd[0] - 0.6, 3.3)], w=0.4)
    # +5V: 78L05 (裏, USB 経路の列) → C6 の下 → ビア → 上面の J1 横の通り道 → J1 7 番
    p5 = b.pad_xy("U2", "1")
    b.via("+5V", 6.45, 9.62).SetLocked(True)
    track("+5V", "B", [p5, (p5[0], 9.62), (6.45, 9.62)])
    track("+5V", "F", [(6.45, 9.62), (4.0, 12.07), (4.0, 16.51), (PIN_X[0], 16.51)])
    if key == "C":    # J2 の SW ピン → GH-SW 20k の右 → SW ベタ
        for i in range(4):
            hy = A_LSY[i]
            ysw = PIN_Y0 + 2.54 * (5 + 3 * (3 - i))
            track(f"SW{i}", "B", [(PIN_X[1], ysw), (17.0, ysw), (17.0, hy + 0.5), (15.7, hy + 0.5)], w=0.15)
    if key == "A":    # J2 の SW ピン → ゲート抵抗 (0805) の電極間 → SW ベタ (自動配線が抜けない所を先に引く)
        for i in range(4):
            ly, hy = A_LSY[i], A_LSY[i] + A_DY
            ysw = PIN_Y0 + 2.54 * (5 + 3 * (3 - i))
            yt = ysw + 0.19
            yz = max(yt, ly - 0.9)
            pts = [(PIN_X[1], ysw), (19.0, yt), (14.3, yt), (14.3, yz), (13.4, yz)]
            for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
                if abs(x1 - x2) + abs(y1 - y2) > 1e-6:
                    t = pcblib.pcbnew.PCB_TRACK(b.b)
                    t.SetStart(pcblib.P(x1, y1))
                    t.SetEnd(pcblib.P(x2, y2))
                    t.SetWidth(pcblib.MM(0.15))
                    t.SetLayer(pcblib.pcbnew.B_Cu)
                    t.SetNet(b.net(f"SW{i}"))
                    b.b.Add(t)
    b.zones_pre = True
    for ref, txt, dx in (("J3", "VIN/GND", 0), ("J4", "OUT3..0", 0)):
        l, t, r, bt = b.bbox(ref)
        b.text(txt, (l + r) / 2 + dx, bt + 0.6, 0.6)
    return finish(b, route, silk=[(f"mPB PWR-{key}", W / 2, H - 1.4, 0.7)],
                  outside_ok={"J4", "J1", "J2", "J3"}, fr_opts=FR_OPTS)


def tight_courtyard(b, ref, margin=0.05, body=False):
    """courtyard を実物に合わせて詰める (密に並べた TO-263 など)。body=False: パッドごとの矩形 + margin,
    body=True: 部品図 (Fab) の外形 + margin."""
    pn = pcblib.pcbnew
    fp = b.b.FindFootprintByReference(ref)
    crt = pn.B_CrtYd if fp.IsFlipped() else pn.F_CrtYd
    fab = pn.B_Fab if fp.IsFlipped() else pn.F_Fab
    for g in list(fp.GraphicalItems()):
        if g.GetLayer() == crt:
            fp.Remove(g)
    if body:
        bbs = [g.GetBoundingBox() for g in fp.GraphicalItems() if g.GetLayer() == fab]
        boxes = [(min(q.GetLeft() for q in bbs), min(q.GetTop() for q in bbs),
                  max(q.GetRight() for q in bbs), max(q.GetBottom() for q in bbs))]
    else:
        boxes = [(q.GetLeft(), q.GetTop(), q.GetRight(), q.GetBottom()) for q in (pd.GetBoundingBox() for pd in fp.Pads())]
    m = pcblib.MM(margin)
    ps = pn.SHAPE_POLY_SET()
    for l, t, r, bt in boxes:
        one = pn.SHAPE_POLY_SET()
        one.NewOutline()
        for x, y in ((l - m, t - m), (r + m, t - m), (r + m, bt + m), (l - m, bt + m)):
            one.Append(int(x), int(y))
        ps.BooleanAdd(one, pn.SHAPE_POLY_SET.PM_FAST)
    for i in range(ps.OutlineCount()):
        ch = ps.Outline(i)
        pts = [ch.CPoint(k) for k in range(ch.PointCount())]
        for a, c in zip(pts, pts[1:] + pts[:1]):
            sh = pn.PCB_SHAPE(fp)
            sh.SetShape(pn.SHAPE_T_SEGMENT)
            sh.SetStart(pn.VECTOR2I(a.x, a.y))
            sh.SetEnd(pn.VECTOR2I(c.x, c.y))
            sh.SetLayer(crt)
            sh.SetWidth(pcblib.MM(0.05))
            fp.Add(sh)


def fixed_zones(b, zs, priority=3):
    """(ネット, 層, 多角形) の並びを, ネット・層ごとに 1 つの多角形へ合成してベタにする
    (長方形を別々のベタにすると, パッドの無い帯が孤立島として消されるため)."""
    pn = pcblib.pcbnew
    groups = {}
    b.fixed_rects = getattr(b, "fixed_rects", [])
    for net, layer, pts in zs:
        groups.setdefault((net, layer), []).append(pts)
        xs, ys = [x for x, _ in pts], [y for _, y in pts]
        b.fixed_rects.append((net, layer, (min(xs), min(ys), max(xs), max(ys))))
    for (net, layer), polys in groups.items():
        ps = pn.SHAPE_POLY_SET()
        for pts in polys:
            one = pn.SHAPE_POLY_SET()
            one.NewOutline()
            for x, y in pts:
                one.Append(pcblib.MM(x), pcblib.MM(y))
            ps.BooleanAdd(one, pn.SHAPE_POLY_SET.PM_FAST)
        ps.Simplify(pn.SHAPE_POLY_SET.PM_STRICTLY_SIMPLE)
        for k in range(ps.OutlineCount()):
            ch = ps.Outline(k)
            pts = [pcblib.to_mm(ch.CPoint(j)) for j in range(ch.PointCount())]
            z = b.zone(net, layer, pts, priority=priority, name=f"{net}_{layer}_fixed{k}")
            z.SetPadConnection(pn.ZONE_CONNECTION_FULL)


BW, BH = 44.6, 99.5   # 子基板 B (面付け 100 × 100mm に収まる最大)。モジュールは左右中央
BOFF = (BW - MW) / 2
B_LEG_X = tuple(5.65 + 11.1 * i for i in range(4))   # レッグ i (HS/LS の縦の列) の中心 x
B_SH_Y, B_LS_Y, B_HS_Y, B_T_Y = 54.925, 66.85, 83.3, 94.4   # シャント中心 / LS・HS の原点 / 出力端子の中心


def build_daughter_b(route=True):
    """子基板 B (TO-263 ×8, 丸端子)。モジュールの下に 4 レッグを横に並べ (1 枚のヒートシンクで覆える),
    各レッグは上から シャント → LS (ピン上向き) → HS (ピン上向き, タブ = VBUS が下) → 出力端子 (M3 丸端子)。
    HS のタブは下面で 1 本の VBUS 帯になり, 上面の SW 帯が LS のタブから端子へ下る。
    シャントの ISH は上面の ISH 帯 (y 53〜57) で左列のバスシャント R70 → GND 端子へ。
    電源入力 (VIN 端子 → F1 → Q9) は右列, GND 端子と R70 は左列。モジュールの真下は信号の部品だけ."""
    W, H = BW, BH
    b = Pcb(prj("daughter/PWR_B"), W, H, "mPBCH32M030DS0 power board B", rev="0.4")
    hicur_daughter(b)
    b.widen, b.grow_extra = None, []
    B = "B"
    b.place("J1", BOFF + PIN_X[0], PIN_Y0)
    b.place("J2", BOFF + PIN_X[1], PIN_Y0)
    # ---- レッグ (下面) と出力端子 (上面) ----
    for i, cx in enumerate(B_LEG_X):
        rb = 30 + 10 * i
        b.place(f"Q{2 + 2 * i}", cx, B_LS_Y, 90, B)          # LS: ピン上 (G 左 / S 右), タブ (SW) 下
        b.place(f"Q{1 + 2 * i}", cx, B_HS_Y, 90, B)          # HS: ピン上 (S → LS タブ), タブ (VBUS) 下
        b.place(f"R{rb + 4}", cx + 2.54 - 2.965, B_SH_Y, 180, B)   # シャント: 1 (SRC) 右 = LS ソースの真上, 2 (ISH) 左
        b.place(f"J4{i}", cx, B_T_Y, 0)                       # 出力端子 OUTi
        if i < 3:
            put_c(b, f"C{rb + 1}", cx + 3.35, 64.0, rot=180)  # 10µF: 左 = SRC, 右 = VBUS (上面, LS ソースの下)
            put_c(b, f"C{rb}", cx + 3.75, 62.35, rot=180)      # 0.1µF
        else:                                                 # レッグ 3: VBUS の入口 (右列 → HS 列) を細らせないよう上に寄せる
            put_c(b, f"C{rb + 1}", cx + 3.35, 58.3, rot=180)
            put_c(b, f"C{rb}", cx + 2.95, 59.95, rot=180)
    for k, i in enumerate((0, 1, 2)):                         # バルク容量: 上 = ISH 帯, 下 = VBUS 帯
        put_c(b, f"C{7 + k}", B_LEG_X[i] + 4.6, 57.85, rot=90)
    # ---- 左列: GND 端子, バスシャント, ヒートシンク穴 ----
    b.place("J5", 6.26, 5.9)
    b.place("H1", 4.0, 43.0)
    put_c(b, "R70", 9.6, 50.4, rot=90)                        # 下 = ISH (帯へ), 上 = GND
    # ---- 右列: VIN 端子 → F1 → Q9 → VBUS 帯, ヒートシンク穴 ----
    b.place("J3", 38.35, 5.9)
    b.place("F1", 41.5, 15.2, 270)                            # 上 = VIN, 下 = VIN_F
    b.place("Q9", 41.5, 22.0, 270)                            # ピン (S, G) 上, ドレイン下
    put_c(b, "U4", 37.6, 22.0, rot=0, side=B)
    put_c(b, "C5", 37.6, 18.9, rot=0, side=B)
    b.place("H2", 36.6, 43.0)
    put_c(b, "D1", 40.1, 55.2, rot=180)                       # 右 = VBUS (K), 左 = ISH
    put_c(b, "C1", 40.2, 51.9, rot=180)
    # ---- モジュールの真下 (信号の部品。上面は低背品のみ) ----
    y = b.pack(["F3", "Q10", "D9"], 15.4, 0.6, 29.6, gap=0.4)          # USB_VBUS (J1 1/2 番) → F3 → Q10 (ドレイン = VBUS)
    b.pack(["R6", "U5", "C6", "U2", "C3", "C4"], 15.4, y + 0.4, 29.6, gap=0.4)   # U5 (LM74700), 78L05 → J1 7 番
    put_c(b, "JP7", 17.2, 42.6, rot=90)
    put_c(b, "JP5", 17.2, 37.4, rot=90)
    put_c(b, "TH1", 11.3, 45.8, rot=90, side=B)               # NTC: 下面, 左列 (レッグ 0 の上, J1 10 番から J1 の左を下る)
    put_c(b, "R63", 39.35, 60.3, rot=0, side=B)                # LS3 の G-S 10k は LS3 の足元 (SRC3 への道がモジュール側に無い)
    b.pack([f"R{30 + 10 * i + k}" for i in (3, 2, 1, 0) for k in (0, 2, 1, 3) if (i, k) != (3, 3)], 20.4, 9.5, 27.3,
           rot=90, side=B, gap=0.9, row_gap=1.6)             # ゲート抵抗・プルダウン (J2 の HO/LO の横)
    b.pack(["R71", "R72", "C71", "R74", "R75", "C72", "R77", "R78", "C73", "R11", "R12"], 15.0, 22.0, 20.0,
           rot=90, side=B, gap=0.25, row_gap=0.6)
    # 密に並べた部品の courtyard を実物に合わせる (MOSFET のパッド間は 0.3mm, 部品本体は干渉しない)
    for ref in [f"Q{k}" for k in range(1, 9)] + ["R34", "R44", "R54", "R64", "R63", "R70", "C1", "D1"] + \
               [f"C{30 + 10 * i + k}" for i in range(4) for k in (0, 1)]:
        tight_courtyard(b, ref)
    for ref in ("J1", "J2"):
        tight_courtyard(b, ref, margin=0.25, body=True)
    for ref in ("C7", "C8", "C9"):
        tight_courtyard(b, ref, margin=0.1, body=True)
    # ---- 電源の銅箔 (配線より先に置く。基板端からは 1.0mm 離す = 面付けのタブ・レジスト開口と揃える) ----
    zs = []
    e = pcblib.ZONE_EDGE

    def Z(net, layer, x0, y0, x1, y1):
        zs.append((net, layer, rect(max(x0, e), max(y0, e), min(x1, W - e), min(y1, H - e))))

    for i, cx in enumerate(B_LEG_X):
        Z(f"SRC{i}", "B.Cu", cx + 1.7, 53.25, cx + 3.8, 61.55)          # シャント 1 → LS ソース
        Z(f"SW{i}", "B.Cu", cx - 5.4, 63.6, cx + 5.4, 73.1)             # LS タブ
        Z(f"SW{i}", "B.Cu", cx - 0.6, 73.1, cx + 5.4, 78.1)             # → HS ソース (左は HS ゲートのビア用に空ける)
        if i:
            Z("ISH", "B.Cu", cx - 7.0, 53.25, cx - 2.55, 56.6)          # シャント 2 (ISH) + 上面へのビア
        xr = W - 0.25 if i == 3 else cx + 5.4
        if i < 3:
            Z(f"SRC{i}", "F.Cu", cx + 1.3, 57.3, cx + 3.55, 65.2)       # 上面: レッグの C (SRC 側)
            Z("VBUS", "F.Cu", cx + 3.85, 57.3, xr, 65.5)                # 上面: レッグの C (VBUS 側) とバルク容量
        else:
            Z(f"SRC{i}", "F.Cu", cx + 1.3, 57.3, cx + 2.75, 60.6)       # 上面: C の SRC 側は短く
            Z("VBUS", "F.Cu", cx + 3.05, 57.3, xr, 60.9)
            Z("VBUS", "F.Cu", cx + 1.3, 60.9, xr, 65.5)
        Z("VBUS", "F.Cu", cx + 1.3, 65.5, xr, 89.2)                     # 上面: HS タブ (VBUS) からのビアの帯
        Z(f"SW{i}", "F.Cu", cx - 3.8, 63.4, cx + 1.0, 89.6)             # 上面: SW 帯 → 出力端子
        Z(f"SW{i}", "F.Cu", cx - 4.9, 89.55, cx + 4.9, H - 0.3)
    Z("ISH", "B.Cu", 0.25, 47.9, B_LEG_X[0] - 2.7, 56.6)                # レッグ 0 の ISH (左列へ逃がす)
    Z("VBUS", "B.Cu", 0.25, 79.9, W - 0.25, 89.55)                      # HS タブを 1 本の VBUS 帯に
    Z("ISH", "F.Cu", 0.25, 53.25, 39.95, 57.0)                          # ISH 帯 (上面): 各シャント → R70
    Z("ISH", "F.Cu", 0.25, 47.9, B_LEG_X[0] - 2.7, 53.25)
    Z("ISH", "F.Cu", 7.6, 52.5, 11.6, 53.25)                            # R70 の ISH 側
    Z("ISH", "F.Cu", 36.5, 50.4, 39.95, 53.25)                          # C1 の ISH 側
    Z("GND", "F.Cu", 7.6, 1.0, 12.25, 48.3)                             # GND 端子 J5 → R70
    Z("GND", "F.Cu", 10.8, 48.3, 13.6, 52.9)                            # → J1 21 番 (モジュールの GND)
    Z("VIN", "F.Cu", 33.6, 1.0, 43.2, 13.7)                             # VIN 端子 J3 → F1
    Z("VIN_F", "F.Cu", 40.9, 16.7, 43.2, 21.1)                          # F1 → Q9 ソース
    Z("VBUS", "F.Cu", 40.4, 21.45, W - 0.25, 57.3)                      # Q9 ドレイン → レッグ 3 の帯
    Z("VBUS", "B.Cu", 40.0, 23.8, W, 52.7)                              # 同じ帯の裏 (ビアで並列にする)
    Z("VBUS", "B.Cu", 42.4, 52.7, W, 63.1)                              # → レッグ 3 の C の横 (上面が細い所) を裏で抜ける
    Z("GND", "B.Cu", 8.4, 1.0, 30.6, 1.9)                               # 上端: J5 (GND) → J2 1 番 (USB の帰路)
    Z("VBUS", "F.Cu", B_LEG_X[1] + 3.85, 57.5, 28.8, 60.4)              # USB 経路の VBUS の受け口
    fixed_zones(b, zs)
    b.solder_nets = {"VBUS", "ISH", "VIN", "VIN_F", "GND"} | {f"SW{i}" for i in range(4)} | {f"SRC{i}" for i in range(4)}
    b.ko_band = lambda net, layer: 0.3
    b.grow_skip = {"VBUS"}          # VBUS の主経路は固定のベタ。モジュール真下の細い VBUS は太らせない (塗りが割れるため)
    vias = []
    for i, cx in enumerate(B_LEG_X):
        vias += [(f"SW{i}", cx + dx, y, 0.8, 0.4) for dx in (-3.2, -2.05, -0.9, 0.25) for y in (64.5, 65.8, 67.1, 68.4, 69.7, 71.0, 72.3)]
        vias += [("VBUS", cx + dx, y, 0.8, 0.4) for dx in (1.9, 3.1, 4.3) for y in (80.9, 82.2, 83.5, 84.8, 86.1, 87.4, 88.7)]
        vias += ([(f"SRC{i}", cx + 3.2, y, 0.6, 0.3) for y in (57.9, 59.1, 60.3)] if i < 3 else
                 [(f"SRC{i}", cx + 2.2, y, 0.6, 0.3) for y in (59.35, 60.25)])
        if i:
            vias += [("ISH", cx + dx, y, 0.8, 0.4) for dx in (-6.4, -5.25) for y in (53.95, 54.93, 55.9)]
    vias += [("ISH", x, y, 0.8, 0.4) for x in (1.45, 2.45) for y in (48.6, 49.8, 51.0, 52.2)]
    vias += [("VBUS", x, 25.0 + 2.45 * k, 0.8, 0.4) for x in (41.1, 42.6) for k in range(11)]
    vias += [("VBUS", 43.0, y, 0.8, 0.4) for y in (61.5, 62.5)]
    for net, x, y, d, dr in vias:
        b.via(net, x, y, dia=d, drill=dr).SetLocked(True)

    def track(net, layer, pts, w=0.2):
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            if abs(x1 - x2) + abs(y1 - y2) < 1e-6:
                continue
            t = pcblib.pcbnew.PCB_TRACK(b.b)
            t.SetLocked(True)
            t.SetStart(pcblib.P(x1, y1))
            t.SetEnd(pcblib.P(x2, y2))
            t.SetWidth(pcblib.MM(w))
            t.SetLayer(pcblib.pcbnew.B_Cu if layer == "B" else pcblib.pcbnew.F_Cu)
            t.SetNet(b.net(net))
            b.b.Add(t)
    # USB 経路の VBUS (Q10 ドレイン, モジュールの真下) → 裏面を x 28.4 で下る → シャント 2 の下 → ビア → 上面の受け口
    pd = b.pad_xy("Q10", "5")
    pd = (pd[0], pd[1] + 0.68)          # パッド (y 1.23〜3.62) の下寄り: 上端の GND 帯 (J2 1 番) を空ける
    xl = 28.5
    b.via("VBUS", pd[0], pd[1], dia=0.8, drill=0.4).SetLocked(True)
    b.via("VBUS", xl, 59.0, dia=0.8, drill=0.4).SetLocked(True)
    track("VBUS", "B", [pd, (xl, pd[1] + (xl - pd[0]) if xl > pd[0] else pd[1]), (xl, 59.0)], w=1.2)
    # 信号の先付け: モジュールの真下 → MOSFET 列へ抜ける所は決まった道しかないので, 交差しない順で先に引く。
    #  - レッグ 1/2 のシャントの下 (x 15.3〜17.3 / 26.3〜27.6) を裏で下り, LS のピンとタブの間の帯 (y 61.85〜62.9) を横へ
    #  - HS のゲートは, LS ゲートの左 (y 59.5) のビア → 上面の SW 帯の左の溝 → ビア (y 75.5) → HS ゲート
    #  - 外側レッグ (0/3) の SW と SRC0 はソケットの端子の間 (19-20 / 20-21 番) を裏で
    ya, yb = PIN_Y0 + 2.54 * 19.5, PIN_Y0 + 2.54 * 18.5       # 20-21 番の間 / 19-20 番の間
    ra, rb_, rc, rd = 61.85, 62.2, 62.55, 62.9
    yv, yh = 59.5, 75.5
    vd, vr = 0.5, 0.25

    def top(xs, dx):                     # 束の上端: 左へ逃がして SW2 のビアの場所を空ける (右は USB の VBUS 線)
        return [(xs + dx, 50.0), (xs + dx, 51.0), (xs, 52.6)] if dx else [(xs, 50.0)]

    def gate_hs(i, row, xs, dx=0.0):
        cx = B_LEG_X[i]
        xv = 1.0 if i == 0 else cx - 4.7
        track(f"GH{i}", "B", top(xs, dx) + [(xs, row), (xv, row), (xv, yv)], w=0.15)
        b.via(f"GH{i}", xv, yv, dia=vd, drill=vr).SetLocked(True)
        track(f"GH{i}", "F", [(xv, yv), (xv, yh)], w=0.15)
        b.via(f"GH{i}", xv, yh, dia=vd, drill=vr).SetLocked(True)
        track(f"GH{i}", "B", [(xv, yh), (cx - 2.54, yh)], w=0.15)

    def gate_ls(i, row, xs, dx=0.0):
        cx = B_LEG_X[i]
        track(f"GL{i}", "B", top(xs, dx) + [(xs, row), (cx - 2.54, row), (cx - 2.54, 61.3)], w=0.15)

    gate_ls(1, ra, 15.3); gate_hs(1, rb_, 15.7); gate_ls(0, rc, 16.1); gate_hs(0, rd, 16.5)
    track("SW1", "B", [(16.9, 50.0), (16.9, 64.2)], w=0.15)
    track("SRC1", "B", [(20.0, 54.2), (20.2, 53.6), (20.2, 50.0)], w=0.15)             # SRC1 のベタの右肩から上へ
    gate_ls(2, ra, 26.3, -0.9); gate_hs(2, rb_, 26.65, -0.9)
    track("SW2", "B", [(26.5, 50.9), (26.5, 51.7), (27.0, 52.6), (27.0, 64.2)], w=0.15)   # 上端はビアで上面へ
    b.via("SW2", 26.5, 50.9, dia=vd, drill=vr).SetLocked(True)
    gate_ls(3, rd, 27.3); gate_hs(3, rc, 27.6)
    x0, x3 = B_LEG_X[0] - 0.2, B_LEG_X[3] - 0.2
    for net, xx in (("SW0", x0), ("SW3", x3)):                   # SW 帯 (上面) → ビア (ゲートの帯より上) → 裏
        track(net, "F", [(xx, 63.9), (xx, 57.8)], w=0.15)
        b.via(net, xx, 57.8, dia=vd, drill=vr).SetLocked(True)
    track("SW0", "B", [(x0, 57.8), (x0, yb), (14.55, yb)], w=0.15)
    track("SRC0", "B", [(B_LEG_X[0] + 2.75, 53.5), (B_LEG_X[0] + 2.75, ya), (14.95, ya)], w=0.15)
    track("SW3", "B", [(x3, 57.8), (x3, ya), (29.9, ya)], w=0.15)
    track("SRC2", "B", [(29.85, 53.6), (29.7, 53.3), (29.7, 52.3)], w=0.15)
    b.via("SRC2", 29.7, 52.3, dia=vd, drill=vr).SetLocked(True)
    gl, sr = b.pad_xy("R63", "1"), b.pad_xy("R63", "2")        # 1 = GL3 (左), 2 = SRC3 (右)
    assert gl[0] < sr[0], (gl, sr)
    track("GL3", "B", [(B_LEG_X[3] - 2.54, gl[1]), gl], w=0.2)
    track("SRC3", "B", [sr, (B_LEG_X[3] + 1.95, sr[1])], w=0.2)
    pj = b.pad_xy("JP7", "3")
    track("ISH", "F", [(21.6, 53.6), (21.6, pj[1] + 1.2), (20.4, pj[1]), pj], w=0.3)  # ISH 帯 → JP7 3 番
    p18 = b.pad_xy("J1", "18")
    track("ISH", "F", [p18, (14.7, p18[1] + 0.75), (14.7, 53.6)], w=0.3)             # J1 18 番 (ISH) → ISH 帯
    p19, p5 = b.pad_xy("J1", "19"), b.pad_xy("JP5", "2")                             # ISB_SEL: 裏 → ビア → JP5 2 番
    b.via("ISB_SEL", 15.9, p5[1]).SetLocked(True)
    track("ISB_SEL", "B", [p19, (15.9, p19[1]), (15.9, p5[1])])
    track("ISB_SEL", "F", [(15.9, p5[1]), p5])
    b.zones_pre = True
    for ref, txt in (("J3", "VIN"), ("J5", "GND"), ("J40", "OUT0"), ("J41", "OUT1"), ("J42", "OUT2"), ("J43", "OUT3")):
        l, t, r, bt = b.bbox(ref)
        b.text(txt, (l + r) / 2, (t + bt) / 2 + (6.2 if ref in ("J3", "J5") else -6.3), 1.0, bold=True)
    for ref in ("H1", "H2"):
        l, t, r, bt = b.bbox(ref)
        b.text("HS M3", (l + r) / 2, bt + 0.8, 0.7)
    return finish(b, route, silk=[("mPB PWR-B", W / 2, 50.2, 0.8)], outside_ok={"J1", "J2", "Q1", "Q2", "Q7", "Q8", "C61"},
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
        if getattr(b, "fixed_rects", None) and os.environ.get("MPB_TWO_PHASE"):
            t, v = b.autoroute_fixed(opts=fr_opts)
        else:
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
        early = b.repair_unrouted(skip_nets=("GND",), ripup=bool(os.environ.get("MPB_RIPUP")))
        if early:
            print(f"[{b.name}] repaired before pours: {early}")
        if getattr(b, "widen", None):     # 大電流ネットの配線を, 間隙の許す限り太くする
            nw = b.widen_tracks(b.widen)
            print(f"[{b.name}] widened power tracks: {nw}")
        g = b.grow_zones([n for n in list(b.assign_hicur()) + list(getattr(b, "grow_extra", []))
                          if n not in getattr(b, "grow_skip", ())])
        print(f"[{b.name}] grown power zones: {g}")
    for ref in getattr(b, "flip_after_route", ()):      # 下面へ裏返す (180° 回して 1 番ピンを上端のまま, 穴の位置は不変)
        fp = b.fps[ref]
        before = {p.GetNumber(): pcblib.to_mm(p.GetPosition()) for p in fp.Pads()}
        fp.SetOrientationDegrees(fp.GetOrientationDegrees() + 180)
        fp.Flip(fp.GetPosition(), False)
        after = {p.GetNumber(): pcblib.to_mm(p.GetPosition()) for p in fp.Pads()}
        assert all(abs(before[k][0] - after[k][0]) + abs(before[k][1] - after[k][1]) < 1e-3 for k in before), ref
    for net, layer, pts in zones_hicur:
        b.zone(net, layer, pts, priority=2)
    e = pcblib.ZONE_EDGE
    ol = [(e, e), (b.W - e, e), (b.W - e, b.H - e), (e, b.H - e)]
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
    if getattr(b, "solder_nets", None):     # 電源のベタのレジストを開けてはんだで厚くする
        ns = b.solder_openings(b.solder_nets, exclude_b=getattr(b, "solder_exclude_b", None))
        print(f"[{b.name}] solder-mask openings on power copper: {ns}")
    pcblib.set_custom_models(b.b, b.dir)
    path = b.save()
    kinds, unconn, rpt = b.drc()
    print(f"[{b.name}] DRC: {kinds} unconnected={unconn} ({os.path.relpath(rpt, pcblib.HERE)})")
    render(path, b)
    return b


def render(path, b):
    """TOP / BOTTOM の図を docs/pcb/ に出力 (kicad-cli svg → Chromium で PNG)."""
    out = os.path.join(pcblib.HERE, "..", "docs", "pcb", VAR)
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


BOARDS = ((VAR or ".", "mPBCH32M030DS0"), (VAR + "daughter/PWR_A", "mPBCH32M030DS0_PWR_A"),
          (VAR + "daughter/PWR_B", "mPBCH32M030DS0_PWR_B"), (VAR + "daughter/PWR_C", "mPBCH32M030DS0_PWR_C"))


def fab():
    """製造データ: hardware/fab/<基板名>/ にガーバー・ドリル・部品座標 (両面) を出力し zip にまとめる."""
    import shutil
    for d, name in BOARDS:
        pcb = os.path.join(pcblib.HERE, d, name + ".kicad_pcb")
        out = os.path.join(pcblib.HERE, "fab", VAR, name)
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


def zone_edge():
    """配線済みの基板のベタだけを基板端から ZONE_EDGE (既定 1.0mm) 離して塗り直す (配線はそのまま)。
    塗り直しでできた浮島・不要な孤立片・宙に浮いたビアを除き, DRC と図を更新する."""
    for d, name in BOARDS:
        path = os.path.join(pcblib.HERE, d, name + ".kicad_pcb")
        b = Pcb.__new__(Pcb)
        b.dir, b.name = os.path.join(pcblib.HERE, d), name
        b.b = pcblib.pcbnew.LoadBoard(path)
        eb = b.b.GetBoardEdgesBoundingBox()
        b.W, b.H = (round(pcblib.pcbnew.ToMM(v) - 0.05, 2) for v in (eb.GetRight(), eb.GetBottom()))   # 原点 = 左上, 外形線幅 0.1mm
        e, F = pcblib.ZONE_EDGE, pcblib.MM
        for z in b.b.Zones():
            ol = z.Outline()
            for i in range(ol.OutlineCount()):
                ch = ol.Outline(i)
                for k in range(ch.PointCount()):
                    x, y = (pcblib.pcbnew.ToMM(v) for v in (ch.CPoint(k).x, ch.CPoint(k).y))
                    ch.SetPoint(k, pcblib.pcbnew.VECTOR2I(F(min(max(x, e), b.W - e)), F(min(max(y, e), b.H - e))))
        pcblib.pcbnew.ZONE_FILLER(b.b).Fill(b.b.Zones())
        nd, npr, ndv = b.drop_floating_islands(), b.prune_isolated_pieces(), b.remove_dangling_vias()
        assert pcblib.pcbnew.SaveBoard(path, b.b)
        kinds, unconn, rpt = b.drc()
        print(f"[{name}] zone edge {e}mm: islands {nd}, pieces {npr}, dangling vias {ndv}; DRC: {kinds} unconnected={unconn}")
        render(path, b)


def models():
    """確定済みの基板に自作 3D モデルのパスを設定する (配線などは変えない)."""
    for d, name in BOARDS:
        path = os.path.join(pcblib.HERE, d, name + ".kicad_pcb")
        b = pcblib.pcbnew.LoadBoard(path)
        n = pcblib.set_custom_models(b, os.path.dirname(path))
        assert pcblib.pcbnew.SaveBoard(path, b)
        print(f"[{name}] custom 3D models: {n}")


def nopour():
    """手直し用: 仕上げた MCU モジュールからベタ (GND・大電流の太らせ) を全部外した版を nopour/ に作る。
    配線とビアは残し, ベタへ落とすだけのビア (スティッチング) は外す。"""
    import glob
    import shutil
    src = os.path.join(pcblib.HERE, VAR or ".")
    dst = os.path.join(pcblib.HERE, (VAR.rstrip("/") + "_" if VAR else "") + "nopour")
    os.makedirs(dst, exist_ok=True)
    for f in glob.glob(os.path.join(src, "*.kicad_sch")) + [os.path.join(src, n) for n in (
            "mPBCH32M030DS0.kicad_pro", "parts.json", "expected_nets.txt", "bom.csv", "fp-lib-table", "sym-lib-table")]:
        if os.path.exists(f):
            shutil.copy(f, dst)
    if not VAR:   # nopour/ は 1 段深いのでライブラリの相対パスを直す
        for n in ("fp-lib-table", "sym-lib-table"):
            t = open(os.path.join(dst, n), encoding="utf-8").read().replace("${KIPRJMOD}/", "${KIPRJMOD}/../")
            open(os.path.join(dst, n), "w", encoding="utf-8").write(t)
    b = pcblib.pcbnew.LoadBoard(os.path.join(src, "mPBCH32M030DS0.kicad_pcb"))
    nz = 0
    for z in list(b.Zones()):
        if not z.GetIsRuleArea():
            b.RemoveNative(z)      # Remove() は SWIG の所有権処理で以降の GetTracks() が壊れることがある
            nz += 1
    ends = [pcblib.to_mm(p) for t in b.GetTracks() if t.GetClass() != "PCB_VIA" for p in (t.GetStart(), t.GetEnd())]
    nv = 0
    for v in list(b.GetTracks()):
        if v.GetClass() == "PCB_VIA":
            c, r = pcblib.to_mm(v.GetPosition()), pcblib.pcbnew.ToMM(v.GetWidth()) / 2
            if not any(math.hypot(c[0] - x, c[1] - y) <= r for x, y in ends):
                b.RemoveNative(v)
                nv += 1
    path = os.path.join(dst, "mPBCH32M030DS0.kicad_pcb")
    assert pcblib.pcbnew.SaveBoard(path, b)
    shutil.copy(os.path.join(src, "mPBCH32M030DS0.kicad_pro"), dst)   # SaveBoard が書き換えたネットクラス設定を戻す
    print(f"nopour: removed zones {nz}, stitching vias {nv} -> {os.path.relpath(path, pcblib.HERE)}")
    rpt = os.path.join(dst, "build", "mPBCH32M030DS0_drc.rpt")
    os.makedirs(os.path.dirname(rpt), exist_ok=True)
    subprocess.run(["kicad-cli", "pcb", "drc", "--units", "mm", "--severity-all", "-o", rpt, path], capture_output=True)
    out = os.path.join(pcblib.HERE, "..", "docs", "pcb", os.path.basename(dst))
    os.makedirs(out, exist_ok=True)
    for side, layers in (("top", "F.Cu,F.SilkS,F.Mask,Edge.Cuts"), ("bottom", "B.Cu,B.SilkS,B.Mask,Edge.Cuts")):
        cmd = ["kicad-cli", "pcb", "export", "svg", "--layers", layers, "--exclude-drawing-sheet",
               "--page-size-mode", "2", "-o", os.path.join(out, f"mPBCH32M030DS0_{side}.svg"), path]
        if side == "bottom":
            cmd.insert(4, "--mirror")
        subprocess.run(cmd, check=True, capture_output=True)
    return path


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
    out = os.path.join(pcblib.HERE, "..", "docs", "pcb", VAR, "drc_summary.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("# DRC 結果 (KiCad 8 pcbnew, gen_pcb.py 実行時に自動生成)\n\n"
                "ルール: 2 層 / 最小線幅・間隙 0.127mm / ビア 0.6mm (穴 0.3mm, 大電流 0.8mm, QFN サーマルビア 0.2mm) / 基板端 0.25mm (ベタは 1.0mm)。" + "\n"
                "「lib_footprint_issues」(ライブラリ照合) はスクリプト生成のため対象外。\n\n"
                "| 基板 | 電気的エラー (配線・間隙・未接続など) | 警告 (シルク等, 製造時にクリップされるもの) |\n|---|---|---|\n")
        f.write("\n".join(rows) + "\n")
    return out


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "main"
    if what in ("fab", "summary", "nopour", "zone_edge", "models"):
        {"fab": fab, "summary": lambda: print(summarize()), "nopour": nopour, "zone_edge": zone_edge,
         "models": models}[what]()
        sys.exit(0)
    route = "--no-route" not in sys.argv
    REUSE = "--reroute" not in sys.argv   # 配置が変わっていなければ前回の配線結果 (build/*.ses) を使う
    if what in ("main", "all"):
        build_main(route)
    for k in ("A", "B", "C"):
        if what in (k, "all"):
            build_daughter(k, route)
    print(summarize())
