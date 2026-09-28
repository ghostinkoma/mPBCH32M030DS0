"""モジュールの 3.3V 系・アナログ系の配線について, スイッチング系ネットとの近接 (同一層の並走) と
下の層の GND 有無 (帰路) を調べる."""
import json
import math
import sys

import numpy as np
from scipy import ndimage

sys.path.insert(0, ".")
from solve import H, raster_poly_xor, raster_seg  # noqa: E402

d = json.load(open("M_all.json"))
x0, y0 = -0.5, -0.5
nx, ny = int((d["W"] + 1) / H) + 1, int((d["H"] + 1) / H) + 1
shape = (ny, nx)

AGG = {f"{p}{i}" for p in ("SW", "VB", "HO", "LO") for i in range(4)}           # スイッチング (dv/dt 大)
AGG2 = {"VBUS", "USB_VBUS", "VHV", "VHV_IN", "VDD8"} | {f"GLED{s}{i}" for s in "HL" for i in range(4)}
HIGHZ = {"I2C_SCL": "4.7k 上げ", "I2C_SDA": "4.7k 上げ", "nFAULT": "10k 上げ", "nFAULT_IN": "10k+470Ω",
         "TACH_IN": "4.7k 直列", "TACH_R": "4.7k 直列", "UART_RX": "入力 (外部駆動)", "SWDIO": "内部上げ",
         "GPIO_PC5": "入力にもなる", "GPIO_PC4": "10k 上げ / ボタン", "XI": "水晶", "XO": "水晶",
         "SENS_U": "BEMF 分圧 2.6kΩ", "SENS_V": "BEMF 分圧 2.6kΩ", "SENS_W": "BEMF 分圧 2.6kΩ",
         "BEMF_U": "BEMF 分圧 2.6kΩ", "BEMF_V": "BEMF 分圧 2.6kΩ", "BEMF_W": "BEMF 分圧 2.6kΩ",
         "IA_P": "100Ω/2.2nF", "IA_N": "100Ω/2.2nF", "IB_P": "100Ω/2.2nF", "IB_N": "100Ω/2.2nF",
         "IBUS_F": "1k/1nF", "OCP_REF": "12k/1k, 0.1µF", "NTC": "10k, 0.1µF", "VBUS_SNS": "子基板分圧, 10nF",
         "USB_VBUS_SNS": "120k/10k, 10nF", "QII_IN": "0.1µF 結合", "HALL_A": "1k/1nF", "HALL_B": "1k/1nF",
         "HALL_C": "1k/1nF", "HALL_A_IN": "4.7k 上げ", "HALL_B_IN": "4.7k 上げ", "HALL_C_IN": "4.7k 上げ",
         "nRST": "10k/0.1µF", "UART_TX": "出力", "PD_PWR_EN": "出力", "USB_CC1": "PD PHY", "USB_CC2": "PD PHY",
         "USB_DP": "USB", "USB_DN": "USB", "ISA_SEL": "100Ω", "ISB_SEL": "100Ω", "ISH": "100Ω"}


def mask_of(names, L):
    m = np.zeros(shape, bool)
    for n, lay, xa, ya, xb, yb, w in d["segs"]:
        if n in names and lay == L:
            raster_seg(m, (xa, ya, xb, yb, w), x0, y0)
    for n, ref, num, ls, polys in d["pads"]:
        if n in names and L in ls:
            for p in polys:
                m |= raster_poly_xor(shape, p, x0, y0)
    for n, x, y, dia in d["vias"]:
        if n in names:
            raster_seg(m, (x, y, x, y, dia), x0, y0)
    return m


dist = {}
gnd = {}
for L in ("F", "B"):
    agg = mask_of(AGG, L)
    dist[L] = ndimage.distance_transform_edt(~agg) * H           # 最寄りのスイッチング系銅までの距離 (mm)
    dist[L + "2"] = ndimage.distance_transform_edt(~mask_of(AGG2, L)) * H
    g = np.zeros(shape, bool)
    for n, lay, polys in d["zones"]:
        if n == "GND" and lay == L:
            for p in polys:
                g |= raster_poly_xor(shape, p, x0, y0)
    gnd[L] = g | mask_of({"GND"}, L)

rows = []
for net in HIGHZ:
    tot = near03 = near06 = near2_03 = 0.0
    nog = 0.0
    worst = (9, None)
    for n, L, xa, ya, xb, yb, w in d["segs"]:
        if n != net:
            continue
        ln = math.hypot(xb - xa, yb - ya)
        k = max(int(ln / 0.05), 1)
        other = "B" if L == "F" else "F"
        for i in range(k + 1):
            x, y = xa + (xb - xa) * i / k, ya + (yb - ya) * i / k
            c, r = int((x - x0) / H), int((y - y0) / H)
            gap = dist[L][r, c] - w / 2
            gap2 = dist[L + "2"][r, c] - w / 2
            dl = ln / (k + 1)
            tot += dl
            if gap < 0.3:
                near03 += dl
            if gap < 0.6:
                near06 += dl
            if gap2 < 0.3:
                near2_03 += dl
            if gap < worst[0]:
                worst = (gap, (round(x, 2), round(y, 2), L))
            # 反対側の層 (±0.3mm) に GND が無い区間 = 帰路が遠い
            r0, r1, c0, c1 = max(r - 6, 0), r + 7, max(c - 6, 0), c + 7
            if not gnd[other][r0:r1, c0:c1].any() and not gnd[L][r0:r1, c0:c1].any():
                nog += dl
    rows.append((net, HIGHZ[net], tot, near03, near06, near2_03, nog, worst))
rows.sort(key=lambda r: -r[3])
print(f"{'net':14s} {'条件':18s} {'長さ':>5s} {'SW系<0.3':>8s} {'<0.6':>6s} {'VBUS系<0.3':>9s} {'GND無':>6s}  最接近")
for net, cond, tot, a, b, c, nog, worst in rows:
    print(f"{net:14s} {cond[:18]:18s} {tot:5.1f} {a:8.1f} {b:6.1f} {c:9.1f} {nog:6.1f}  {worst[0]:.2f}mm @{worst[1]}")
