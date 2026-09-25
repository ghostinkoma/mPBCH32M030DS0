#!/usr/bin/env python3
"""
mPBCH32M030DS0 の基板 (2 層) を生成する。

  export KICAD7_FOOTPRINT_DIR=<kicad-footprints 7.0.x のチェックアウト>
  python3 gen_schematic.py          # 先に parts.json を作る
  python3 gen_pcb.py [main|A|B|C|D|all] [--no-route] [--reroute]
  python3 gen_pcb.py fab        # 製造データ (hardware/fab/*.zip)
  python3 gen_pcb.py summary    # docs/pcb/drc_summary.md を更新

主基板と子基板は裏面同士を向かい合わせて重ねる (基板間 約5mm)。
  主基板 (上から見た座標 = 世界座標) : TOP 面が上。基板間コネクタ J9/J10 は BOTTOM 面。
  子基板 (自分の TOP 面から見た座標)  : 世界座標を左右反転したもの x_d = W - x_world。
                                     ソケット J1/J3 は子基板の BOTTOM 面 (主基板側)。
配置: 主基板 = 右: MCU / USB-C / GPIO・I2C 等, 左上: 電源, 左下: 基板間コネクタ (+ 真下に子基板のパワー段)。
"""
import os
import subprocess
import sys

import pcblib
from pcblib import Pcb

REUSE = True

W, H = 60.0, 42.0            # 主基板・子基板 A/C/D の外形
MH = [(2.8, 24.6), (57.4, 2.6), (32.4, 31.6)]   # M2 取付穴 (世界座標, 両基板共通)
J9_AT = (0.6, 28.4)          # 基板間コネクタ (世界座標, 主基板 BOTTOM 面, courtyard 左上)
J10_AT = (0.6, 35.3)
HICUR_MAIN = ["VIN", "VIN_F", "VBUS", "USB_VBUS", "USB_VBUS_P"]
POWER_MAIN = ["+5V", "VHV_IN", "USB_VBUS_F"]   # QFN (0.35mm ピッチ) に入るネットは既定幅のまま


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


# ---------------------------------------------------------------------------
def build_main(route=True):
    b = Pcb(".", W, H, "mPBCH32M030DS0 main board (CH32M030C8U7)")
    # 主基板の大電流ネットは 0.5mm で配線し, 配線後に周囲をベタで太らせる (grow_zones)
    b.classes["HiCur"].SetTrackWidth(pcblib.MM(0.5))
    b.classes["HiCur"].SetViaDiameter(pcblib.MM(0.8))
    b.classes["HiCur"].SetViaDrill(pcblib.MM(0.4))
    b.netclass("HiCur", HICUR_MAIN)
    b.netclass("Power", POWER_MAIN)
    dflt = b.b.GetDesignSettings().m_NetSettings.m_DefaultNetClass   # QFN 周りの引き出しのため 0.127mm (5mil) 規則
    dflt.SetTrackWidth(pcblib.MM(0.127))
    dflt.SetClearance(pcblib.MM(0.127))
    # ---- 左上: 電源 (J1 → F1 → Q9/U4 理想ダイオード → VBUS, USB-PD → F3 → Q10/U5 → VBUS) ----
    put(b, "J1", 0.6, 0.6, rot=90)                     # 2x4 (奇数 VIN / 偶数 GND)
    put(b, "F1", 12.3, 0.6)
    put(b, "Q9", 20.8, 0.6)
    put(b, "D1", 12.3, 4.5)
    put(b, "U4", 20.8, 4.5)
    put_c(b, "C5", 22.85, 5.25, side="B")              # VCAP (U4 1-6 ピン間) は U4 の真裏
    put(b, "C1", 22.9, 8.0)
    y = b.pack(["U2", "C3", "C4"], 0.6, 7.2, 11.8)
    b.pack(["R3", "D2", "R4", "D7", "R5", "D8"], 0.6, y + 0.3, 11.8, rot=90)
    put(b, "F3", 12.3, 9.8)
    put(b, "D9", 18.5, 9.6, rot=90)
    put(b, "Q10", 22.3, 10.2)
    put(b, "U5", 22.3, 14.0)
    b.pack(["C6", "R6", "R7", "R8", "C7"], 12.3, 14.0, 18.3)
    b.pack(["D5", "D6", "R10", "D4"], 0.6, 17.6, 22.0)
    # ---- 左下: 基板間コネクタ (BOTTOM) + センシング選択 (TOP) ----
    put(b, "J9", J9_AT[0], J9_AT[1], rot=90, side="B")
    put(b, "J10", J10_AT[0], J10_AT[1], rot=90, side="B")
    for k, ref in enumerate(("JP2", "JP3", "JP4", "JP8")):   # MCU 右側ピンの引き出しを妨げないよう左下に置く
        put(b, ref, 14.4 + k * 3.8, 24.8)
    # ---- 右: MCU / USB / I/O ----
    put_c(b, "U1", 36.5, 16.0, rot=180)
    put(b, "J5", 26.6, 0.4, rot=90)                    # UART (上辺)
    put(b, "J7", 38.2, 0.4, rot=90)                    # SDI (上辺)
    put(b, "J6", 52.3, 5.4)                            # GPIO 1x8 (右辺)
    put(b, "J8", W - 8.94, 27.2, rot=90)               # USB-C (右辺, 差込口は +x)
    put(b, "J3", 30.1, 38.3, rot=90)                   # HALL (下辺)
    put(b, "J4", 44.0, 38.3, rot=90)                   # I2C (下辺)
    # MCU のデカップリングとブートストラップは BOTTOM 面 (MCU 直下の周囲)。TOP 面は QFN の引き出し配線に空ける
    b.pack(["C21", "C22", "C23", "C24"], 30.4, 12.2, 33.8, rot=90, side="B")   # ブートストラップ (ゲートピン裏)
    b.pack(["C12", "C13", "C10", "C11", "C14", "C15"], 33.6, 19.0, 41.0, side="B")  # 電源 (下辺ピン裏)
    b.pack(["C133", "R131"], 41.4, 19.0, 45.0, side="B")
    b.pack(["Y1", "C131", "C132"], 30.4, 6.4, 37.2)                      # 水晶 (左上ピン側)
    b.pack(["R11", "R12", "C16", "R13", "C17", "R14", "R15", "C18"], 37.6, 4.6, 45.2, side="B")   # MCU 上辺ピンの裏
    b.pack(["R16", "R17", "C19", "R18", "R19", "C20", "C103", "R110"], 40.0, 11.6, 45.2, rot=90, side="B")  # 電流アンプ入力 (裏)
    b.pack(["SW1", "SW2", "D3", "R112", "R111"], 45.8, 6.0, 51.8)
    b.pack(["R122", "C105", "R114", "R115"], 45.8, 16.4, 50.2, side="B")
    put_c(b, "R123", 51.7, 17.36, side="B")             # J6 TACH_IN / nFAULT_IN の直列抵抗はピンの真横 (裏)
    put_c(b, "R120", 51.7, 19.9, side="B")
    b.pack(["U3", "F2", "R130", "C130"], 41.8, 24.0, 47.0)
    b.pack(["R100", "R101", "C100", "R103", "R104", "C101", "R106", "R107", "C102"], 35.2, 32.4, 41.6)
    # MCU の右側 (PA0-PA11 / USB / アナログ) の引き出しに余裕を持たせるため, 右側の部品を 4mm 右へ
    for ref, fp in b.fps.items():
        if b.bbox(ref)[0] >= 39.4 and ref != "J8":
            pos = fp.GetPosition()
            fp.SetPosition(pcblib.pcbnew.VECTOR2I(pos.x + pcblib.MM(4.0), pos.y))
    for k, (x, y) in enumerate(MH):
        put_c(b, f"H{k + 1}", x, y)
    return finish(b, route, fr_opts=tuple(os.environ.get("MPB_FR_OPTS", "-us hybrid -hr 1:1").split()), silk=[
        ("mPBCH32M030DS0 Rev0.3", 17.0, 22.4, 0.8),
        ("github.com/ghostinkoma/mPBCH32M030DS0", 46.0, 36.9, 0.6),
    ], zones_hicur=[
        
    ])


# ---------------------------------------------------------------------------
# 子基板
# ---------------------------------------------------------------------------
def main_b2b_pads():
    """主基板の J9/J10 のパッド世界座標 (主基板の配置と同じ手順で求める)."""
    m = Pcb(".", W, H, "tmp")
    put(m, "J9", J9_AT[0], J9_AT[1], rot=90, side="B")
    put(m, "J10", J10_AT[0], J10_AT[1], rot=90, side="B")
    return {ref: {p.GetNumber(): pcblib.to_mm(p.GetPosition()) for p in m.fps[ref].Pads()} for ref in ("J9", "J10")}


def mate_socket(b, ref, main_pads, XM, YOFF):
    """子基板ソケットを, 裏返して重ねたとき主基板ピンと同じ位置に来るように置く (位置で検証)."""
    mate = lambda n: n   # 同じ番号同士が嵌合する向きだけを採用する
    for rot in (90, 270, 0, 180):
        b.place(ref, 0, 0, rot, "B")
        pos = {p.GetNumber(): pcblib.to_mm(p.GetPosition()) for p in b.fps[ref].Pads()}
        tx, ty = main_pads["1"]
        tgt = (XM - tx, ty + YOFF)
        cur = pos[mate("1")]
        dx, dy = tgt[0] - cur[0], tgt[1] - cur[1]
        ok = all(abs(pos[mate(n)][0] + dx - (XM - x)) < 0.01 and abs(pos[mate(n)][1] + dy - (y + YOFF)) < 0.01
                 for n, (x, y) in main_pads.items())
        if ok:
            b.place(ref, dx, dy, rot, "B")
            return rot
    raise RuntimeError(f"{ref}: no orientation mates with the main board")


LEG = {  # 子基板ごとの配置パラメータ (子基板 TOP 面から見た座標)
    "A": dict(W=60.0, H=42.0, XM=60.0, YOFF=0.0, X0=5.4, pitch=12.4, y0=2.5),
    "C": dict(W=60.0, H=42.0, XM=60.0, YOFF=0.0, X0=5.4, pitch=12.4, y0=2.5),
    "B": dict(W=66.0, H=66.0, XM=66.0, YOFF=24.0, X0=0.8, pitch=15.2, y0=2.5),
}


def build_daughter(key, route=True):
    L = LEG[key]
    Wd, Hd, XM, YOFF = L["W"], L["H"], L["XM"], L["YOFF"]
    b = Pcb(f"daughter/PWR_{key}", Wd, Hd, f"mPBCH32M030DS0 power daughter board {key}")
    # 大電流はベタで流す: SWx/SRCx はレッグ内の TOP ベタ (daughter_zones), GND は両面ベタ。
    # 配線幅を太くするのは J1 からレッグへ渡る VBUS とシャント共通の ISH だけ
    b.netclass("HiCur", ["VBUS", "ISH"])
    pads = main_b2b_pads()
    mate_socket(b, "J1", pads["J9"], XM, YOFF)
    mate_socket(b, "J3", pads["J10"], XM, YOFF)
    mh = [(XM - x, y + YOFF) for x, y in MH]
    for k, (x, y) in enumerate(mh):
        if key == "B" and y < 44:   # B は上方へ張り出すため H2 は主基板と位置合わせせず空き位置に置く
            x, y = 24.0, 50.5
        put_c(b, f"H{k + 1}", x, y)
    # ---- レッグ (上から: シャント → ローサイド → SW 行 → ハイサイド → VBUS 帯) ----
    X0, pitch, y0 = L["X0"], L["pitch"], L["y0"]
    ybot = 0
    for i in range(4):
        X = X0 + pitch * i
        rb = 30 + 10 * i
        qh, ql, rs = f"Q{1 + 2 * i}", f"Q{2 + 2 * i}", f"R{rb + 4}"
        gw = 3.7                                           # ゲート部品の列幅 (左)
        _, _, _, _ = b.bbox(rs)
        put(b, rs, X + gw, y0, rot=90)
        _, _, _, yb = b.bbox(rs)
        put(b, ql, X + gw, yb + 0.3, rot=270)              # ソース上 (シャント側), ドレイン下 (SW)
        _, _, _, yb = b.bbox(ql)
        ysw = yb + 0.9
        put(b, qh, X + gw, ysw, rot=270)                   # ソース上 (SW), ドレイン下 (VBUS 帯)
        l, t, r, yb = b.bbox(qh)
        ybot = max(ybot, yb)
        out = ("J2", "J4", "J5", "J6")[i]
        lo = [f"R{rb + 6}", f"D{11 + 2 * i}", f"R{rb + 2}", f"R{rb + 3}"]   # LED と直列抵抗は隣接
        hi = [f"R{rb + 5}", f"D{10 + 2 * i}", f"R{rb + 0}", f"R{rb + 1}"]
        caps = [f"C{rb + 1}", f"C{rb + 0}"]
        if key == "B":   # TO-263 はレッグ幅いっぱい → 出力ヘッダと CR は左のゲート列にまとめる
            ql_t = b.bbox(ql)[1]
            b.pack(lo, X, ql_t + 1.0, X + gw - 0.2, rot=90)
            put_c(b, out, X + gw / 2 - 0.1, ysw - 0.45)
            yh = b.pack(hi, X, b.bbox(out)[3] + 0.4, X + gw - 0.2, rot=90)
            b.pack(caps, X, yh + 0.4, X + gw - 0.2, rot=90)
        else:
            put_c(b, out, r + 2.0, ysw - 0.45)             # 出力ヘッダは SW 行の右
            b.pack(lo, X, y0 + 4.0, X + gw - 0.2, rot=90)  # ゲート部品: 上 = ローサイド, 下 = ハイサイド
            b.pack(hi, X, ysw + 0.5, X + gw - 0.2, rot=90)
            b.pack(caps, r + 0.3, ysw + 3.6, r + 4.2, rot=90)
    yv = ybot + 0.3                                         # VBUS 帯の上端
    # ---- バスシャント (ISH 帯の右端), バルク容量, NTC, 選択ジャンパ, BEMF 分圧 ----
    put(b, "R70", X0 + pitch * 4 + 0.1, y0, rot=90)
    xs = 0.6
    for ref in [r for r in ("C1", "C2") if r in b.fps]:
        put(b, ref, xs, yv + 3.2)
        xs = b.bbox(ref)[2] + 0.4
    put(b, "TH1", X0 + pitch * 2 - 1.2, yv + 2.4)
    jy = Hd - 9.2
    put(b, "JP7", 0.6, jy)
    put(b, "JP5", 4.6, jy)
    b.pack([f"R{71 + 3 * k}" for k in range(3)] + [f"R{72 + 3 * k}" for k in range(3)] +
           [f"C{71 + k}" for k in range(3)], 8.8, jy + 0.3, min(XM - 30.2, 21.0))
    return finish(b, route, silk=[
        (f"mPBCH32M030DS0 PWR-{key} Rev0.3", 30.0 if key != "B" else 38.5, yv + (5.0 if key != "B" else 5.2), 0.8),
    ], zones_hicur=daughter_zones(b, key, X0, pitch, y0, yv),
        fr_opts=("-us", "hybrid", "-hr", "1:1") if key == "C" else ())


def daughter_zones(b, key, X0, pitch, y0, yv):
    """大電流経路のベタ (TOP): ISH 帯・各レッグの SRC/SW・VBUS 帯と J1 への引き込み."""
    z = []
    xr = X0 + pitch * 4 + 4.2
    z.append(("ISH", "F.Cu", [(X0 - 0.2, 0.3), (xr, 0.3), (xr, y0 + 1.2), (X0 - 0.2, y0 + 1.2)]))
    for i in range(4):
        X = X0 + pitch * i + 3.7
        ql, qh = b.bbox(f"Q{2 + 2 * i}"), b.bbox(f"Q{1 + 2 * i}")
        rs = b.bbox(f"R{34 + 10 * i}")
        z.append((f"SRC{i}", "F.Cu", [(X - 0.1, rs[3] - 1.4), (ql[2] + 0.1, rs[3] - 1.4),
                                     (ql[2] + 0.1, ql[1] + 1.2), (X - 0.1, ql[1] + 1.2)]))
        out = b.bbox(("J2", "J4", "J5", "J6")[i])
        x0, x1 = min(X - 0.1, out[0]), max(ql[2] + 0.1, out[2])
        z.append((f"SW{i}", "F.Cu", [(x0, ql[3] - 1.2), (x1, ql[3] - 1.2), (x1, qh[1] + 1.4), (x0, qh[1] + 1.4)]))
    j1 = b.bbox("J1")
    z.append(("VBUS", "F.Cu", [(X0 - 0.2, yv - 1.3), (xr, yv - 1.3), (xr, yv + 1.6),
                               (j1[2], yv + 1.6), (j1[2], j1[3]), (j1[0], j1[3]), (j1[0], yv + 1.6),
                               (X0 - 0.2, yv + 1.6)]))
    return z


def build_breakout(route=True):
    b = Pcb("daughter/PWR_D", W, H, "mPBCH32M030DS0 daughter board D (pin breakout)")
    b.netclass("HiCur", ["VBUS"])
    pads = main_b2b_pads()
    mate_socket(b, "J1", pads["J9"], W, 0.0)
    mate_socket(b, "J3", pads["J10"], W, 0.0)
    for k, (x, y) in enumerate(MH):
        put_c(b, f"H{k + 1}", W - x, y)
    put(b, "J4", 12.0, 6.0, rot=90)
    put(b, "J2", 12.0, 16.0, rot=90)
    put(b, "C1", 30.0, 15.0)
    names = dict(__import__("gen_schematic").B2B_SIG)
    for n, (x, y) in {p.GetNumber(): pcblib.to_mm(p.GetPosition()) for p in b.fps["J4"].Pads()}.items():
        above = int(n) % 2 == 0
        b.text(names[n], x, y + (-2.1 if above else 2.1), 0.6, rot=90)
    for n, (x, y) in {p.GetNumber(): pcblib.to_mm(p.GetPosition()) for p in b.fps["J2"].Pads()}.items():
        b.text("VBUS" if int(n) % 2 else "GND", x, y + (2.1 if int(n) % 2 else -2.1), 0.6, rot=90)
    return finish(b, route, silk=[("mPBCH32M030DS0 PWR-D (no FET)  Rev0.3", 20.0, 2.0, 0.8)],
                  fr_opts=("-us", "hybrid", "-hr", "1:1"))


# ---------------------------------------------------------------------------
def finish(b, route, silk=(), zones_hicur=(), fr_opts=()):
    bad, missing, outside = b.check_overlaps()
    print(f"[{b.name}] overlaps={bad} missing={sorted(missing)} outside={outside}")
    b.outline()
    b.edge_keepout()
    for s, x, y, sz in silk:
        b.text(s, x, y, sz)
    if route:
        b.reload()   # ネットクラス (プロジェクトのパターン割当) を有効にしてから DSN を書き出す
        t, v = b.autoroute(reuse=REUSE, opts=fr_opts)
        print(f"[{b.name}] routed: tracks={t} vias={v}")
        g = b.grow_zones(list(b.assign_hicur()))
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
          ("daughter/PWR_B", "mPBCH32M030DS0_PWR_B"), ("daughter/PWR_C", "mPBCH32M030DS0_PWR_C"),
          ("daughter/PWR_D", "mPBCH32M030DS0_PWR_D"))


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
        f.write("# DRC 結果 (KiCad 7 pcbnew, gen_pcb.py 実行時に自動生成)\n\n"
                "ルール: 2 層 / 最小線幅・間隙 0.127mm / ビア 0.5mm (穴 0.3mm, QFN サーマルビア 0.2mm) / 基板端 0.25mm。\n"
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
    if what in ("D", "all"):
        build_breakout(route)
    print(summarize())
