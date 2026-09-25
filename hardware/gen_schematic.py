#!/usr/bin/env python3
"""
CH32M030 ユニバーサル・モータードライバ基板 回路図ジェネレータ (KiCad 7 形式)

  python3 gen_schematic.py   -> 主基板 (hardware/) と子基板 (hardware/daughter/PWR_A〜D/) の
                               *.kicad_sch / *.kicad_pro / bom.csv / expected_nets.txt / parts.json を生成
                               (parts.json は gen_pcb.py が基板を作るときの部品・ネット表)

外部ライブラリに依存しないよう、使用シンボルはすべてこのスクリプト内で定義し
回路図ファイルへ埋め込む。各ピンは短いワイヤ + ネットラベルで接続する
(複数シートにまたがるネットはグローバルラベル、それ以外はローカルラベル)。
回路の「正」はこのファイルの部品表(ネット割当)であり、配置は見やすさのためのもの。
"""
import csv
import math
import os
import uuid

OUT = os.path.dirname(os.path.abspath(__file__))
NS = uuid.UUID("6b1f3c2e-8d5a-4f0e-9c1a-2a7d3e4b5c60")
REV = "0.3"
DATE = "2026-09-25"
CUR = None  # 出力中の Project


def U(key):
    return str(uuid.uuid5(NS, key))


# ---------------------------------------------------------------------------
# シンボル定義 (lib 座標は y 上向き)
#   pin: (number, name, x, y, angle, length, hidden)
#   angle: ピンが接続点から本体へ伸びる向き (0=右, 90=上, 180=左, 270=下)
# ---------------------------------------------------------------------------
def _pl(pts, w=0.254, fill="none"):
    p = " ".join(f"(xy {x:g} {y:g})" for x, y in pts)
    return f"(polyline (pts {p}) (stroke (width {w}) (type default)) (fill (type {fill})))"


def _rect(x0, y0, x1, y1, w=0.254, fill="none"):
    return (f"(rectangle (start {x0:g} {y0:g}) (end {x1:g} {y1:g}) "
            f"(stroke (width {w}) (type default)) (fill (type {fill})))")


def _circ(x, y, r, w=0.254, fill="none"):
    return (f"(circle (center {x:g} {y:g}) (radius {r:g}) "
            f"(stroke (width {w}) (type default)) (fill (type {fill})))")


def _text(s, x, y, size=1.27):
    return f'(text "{s}" (at {x:g} {y:g} 0) (effects (font (size {size} {size}))))'


SYMS = {}


def defsym(name, prefix, pins, gfx, show_pin_names=False, show_pin_numbers=False,
           ref_at=(2.54, 1.27), val_at=(2.54, -1.27)):
    SYMS[name] = dict(prefix=prefix, pins=pins, gfx=gfx, spn=show_pin_names,
                      spnum=show_pin_numbers, ref_at=ref_at, val_at=val_at)


# 2 端子 (縦置き基準: pin1 上, pin2 下)
defsym("R", "R", [("1", "~", 0, 3.81, 270, 1.27, False), ("2", "~", 0, -3.81, 90, 1.27, False)],
       [_rect(-1.016, -2.54, 1.016, 2.54)])
defsym("C", "C", [("1", "~", 0, 3.81, 270, 3.048, False), ("2", "~", 0, -3.81, 90, 3.048, False)],
       [_pl([(-2.032, 0.762), (2.032, 0.762)], 0.508), _pl([(-2.032, -0.762), (2.032, -0.762)], 0.508)])
defsym("CP", "C", [("1", "~", 0, 3.81, 270, 2.794, False), ("2", "~", 0, -3.81, 90, 2.794, False)],
       [_rect(-2.286, 0.508, 2.286, 1.016), _rect(-2.286, -1.016, 2.286, -0.508, fill="outline"),
        _text("+", -1.524, 2.032)])
defsym("FUSE", "F", [("1", "~", 0, 3.81, 270, 1.27, False), ("2", "~", 0, -3.81, 90, 1.27, False)],
       [_rect(-0.762, -2.54, 0.762, 2.54), _pl([(0, 2.54), (0, -2.54)])])
defsym("NTC", "TH", [("1", "~", 0, 3.81, 270, 1.27, False), ("2", "~", 0, -3.81, 90, 1.27, False)],
       [_rect(-1.016, -2.54, 1.016, 2.54), _pl([(-1.905, -2.032), (-1.905, -1.27), (1.905, 2.032)])])
# ダイオード類 (横置き基準: pin1=K 左, pin2=A 右)
_dtri = _pl([(1.27, 1.27), (1.27, -1.27), (-1.27, 0), (1.27, 1.27)])
defsym("D_TVS", "D", [("1", "K", -3.81, 0, 0, 2.54, False), ("2", "A", 3.81, 0, 180, 2.54, False)],
       [_dtri, _pl([(-1.778, 1.778), (-1.27, 1.27), (-1.27, -1.27), (-0.762, -1.778)])])
defsym("D_ZENER", "D", [("1", "K", -3.81, 0, 0, 2.54, False), ("2", "A", 3.81, 0, 180, 2.54, False)],
       [_dtri, _pl([(-1.778, 1.27), (-1.27, 1.27), (-1.27, -1.27), (-0.762, -1.27)])])
defsym("LED", "D", [("1", "K", -3.81, 0, 0, 2.54, False), ("2", "A", 3.81, 0, 180, 2.54, False)],
       [_dtri, _pl([(-1.27, 1.27), (-1.27, -1.27)]),
        _pl([(-0.508, 1.778), (0.508, 2.794)]), _pl([(0.508, 1.778), (1.524, 2.794)])])
# N-ch MOSFET (TSON Advance / PowerPAK1212-8 互換ランド: 1-3=S, 4=G, 5=D 大パッド)
_mos = [
    _pl([(-2.54, -1.905), (-2.54, 1.905)]),
    _pl([(-1.778, 1.27), (-1.778, 2.286)]), _pl([(-1.778, -0.508), (-1.778, 0.508)]),
    _pl([(-1.778, -2.286), (-1.778, -1.27)]),
    _pl([(-1.778, 1.778), (0, 1.778), (0, 2.54)]), _pl([(-1.778, -1.778), (0, -1.778), (0, -2.54)]),
    _pl([(-1.778, 0), (0, 0), (0, -1.778)]),
    _pl([(-1.778, 0), (-1.016, 0.508), (-1.016, -0.508), (-1.778, 0)], fill="outline"),
    _pl([(0, 1.778), (1.524, 1.778), (1.524, -1.778), (0, -1.778)]),
    _pl([(0.889, -0.381), (2.159, -0.381), (1.524, 0.508), (0.889, -0.381)], fill="outline"),
    _pl([(0.889, 0.508), (2.159, 0.508)]),
]
defsym("NMOS", "Q",
       [("1", "S", 0, -5.08, 90, 2.54, False), ("2", "S", 0, -5.08, 90, 2.54, True),
        ("3", "S", 0, -5.08, 90, 2.54, True), ("4", "G", -5.08, 0, 0, 2.54, False),
        ("5", "D", 0, 5.08, 270, 2.54, False)],
       _mos, ref_at=(3.81, 1.27), val_at=(3.81, -1.27))
for _nm, (_g, _d, _s) in {"NMOS_SOT23": ("1", "3", "2"), "NMOS_TO263": ("1", "2", "3")}.items():
    defsym(_nm, "Q", [(_s, "S", 0, -5.08, 90, 2.54, False), (_g, "G", -5.08, 0, 0, 2.54, False),
                      (_d, "D", 0, 5.08, 270, 2.54, False)], _mos, ref_at=(3.81, 1.27), val_at=(3.81, -1.27))
# 取付穴 (電気的接続なし)
defsym("MH", "H", [], [_circ(0, 0, 1.27), _circ(0, 0, 0.635)], ref_at=(2.54, 0.635), val_at=(2.54, -1.27))
defsym("SW", "SW", [("1", "~", -5.08, 0, 0, 2.54, False), ("2", "~", 5.08, 0, 180, 2.54, False)],
       [_circ(-2.032, 0, 0.508), _circ(2.032, 0, 0.508), _pl([(-2.032, 1.27), (2.032, 1.27)]),
        _pl([(0, 1.27), (0, 2.54)])], ref_at=(0, 3.81), val_at=(0, -2.54))
defsym("SJ2", "JP", [("1", "~", -3.81, 0, 0, 2.54, False), ("2", "~", 3.81, 0, 180, 2.54, False)],
       [_rect(-1.27, -1.016, -0.254, 1.016, fill="outline"), _rect(0.254, -1.016, 1.27, 1.016, fill="outline")],
       ref_at=(0, 2.54), val_at=(0, -2.54))
defsym("TP", "TP", [("1", "~", 0, -2.54, 90, 1.27, False)], [_circ(0, 0, 1.27)],
       ref_at=(1.905, 1.27), val_at=(1.905, -1.27))
defsym("REG3", "U",
       [("3", "IN", -7.62, 0, 0, 2.54, False), ("1", "OUT", 7.62, 0, 180, 2.54, False),
        ("2", "GND", 0, -5.08, 90, 2.54, False)],
       [_rect(-5.08, 2.54, 5.08, -2.54, fill="background")], show_pin_names=True,
       ref_at=(-5.08, 3.81), val_at=(0, 3.81))


def conn_sym(n, prefix="J"):
    pins = [(str(i + 1), f"P{i + 1}", -5.08, -2.54 * i, 0, 3.81, False) for i in range(n)]
    gfx = [_rect(-1.27, 1.27, 1.27, -2.54 * (n - 1) - 1.27, fill="background")]
    for i in range(n):
        gfx.append(_rect(-1.27, -2.54 * i + 0.127, -0.508, -2.54 * i - 0.127))
    defsym(f"CONN{n}", prefix, pins, gfx, show_pin_numbers=True, ref_at=(0, 2.54), val_at=(0, 5.08))


for _n in (2, 3, 4, 5, 8):
    conn_sym(_n)


def conn2_sym(rows, prefix="J"):
    """2 列ピンヘッダ (KiCad 2xNN と同じ番号: 奇数=左列, 偶数=右列)."""
    pins = []
    for r in range(rows):
        pins.append((str(2 * r + 1), f"P{2 * r + 1}", -7.62, -2.54 * r, 0, 3.81, False))
        pins.append((str(2 * r + 2), f"P{2 * r + 2}", 7.62, -2.54 * r, 180, 3.81, False))
    gfx = [_rect(-3.81, 1.27, 3.81, -2.54 * (rows - 1) - 1.27, fill="background")]
    defsym(f"CONN2x{rows}", prefix, pins, gfx, show_pin_numbers=True, ref_at=(0, 3.81), val_at=(0, 6.35))


for _n in (4, 5, 11):
    conn2_sym(_n)

# CH32M030C8U7 (QFN48 5x5mm / 0.35mm ピッチ) — データシート V1.2 表 2-1 の QFN48 列。
# 裏面パッド (DS ではピン番号 0) は KiCad の慣例に合わせて "49" とする。機能別に左右へ配置。
MCU_L = [("34", "VHV"), ("26", "VDD8"), ("33", "VDD33"), ("49", "GND(EP)"),
         ("37", "PA2/CC3/A15 (SWCLK)"), ("38", "PA3/SWDIO/CC4/A16"),
         ("35", "PA0/CC1R/A13"), ("36", "PA1/CC2R/A14"), ("39", "PB0/UDP/A11"), ("40", "PB1/UDM/A12"),
         ("8", "PB5/XI/A3"), ("9", "PB6/XO/A4"), ("27", "PC0/RST/T1C4"),
         ("28", "PC1/UART_TX"), ("29", "PC2/UART_RX_1"), ("30", "PC3"),
         ("31", "PC4/T1C2_3/SPI_MISO"), ("32", "PC5/HVIO"),
         ("3", "PA14/I2C_SDA_2/A9"), ("4", "PA15/I2C_SCL_2/A10"), ("2", "PA13/T1BKIN_1/A18"),
         ("43", "PA6/CM3N1/T2C2/ISINK1"), ("7", "PB4/V_DET(OVP)/A17"), ("6", "PB3/CM3P3/A1"),
         ("5", "PB2/CM3N3/A0")]
MCU_R = [("46", "ISP1"), ("45", "PA8/ISN1/A7"), ("47", "PA10/ISP2"), ("48", "PA11/ISN2/A8"),
         ("41", "PA4/ISOURCE1/A5"), ("42", "PA5/CM3N0/T2C1/ISRC2/A6"), ("44", "PA7/CM3N2/T2C3/ISINK2/A2"),
         ("1", "PA12/QII1(OPA1)/A19"),
         ("13", "PB9/T1C1/HO0"), ("12", "VB0"), ("11", "VS0"), ("10", "PB8/T1C1N/LO0"),
         ("17", "PB11/T1C2/HO1"), ("16", "VB1"), ("15", "VS1"), ("14", "PB10/T1C2N/LO1"),
         ("21", "PB13/T1C3/T2C1_2/HO2"), ("20", "VB2"), ("19", "VS2"), ("18", "PB12/T1C3N/T2C1N_2/LO2"),
         ("25", "PB15/T2C2_2/HO3"), ("24", "VB3"), ("23", "VS3"), ("22", "PB14/T2C2N_2/LO3")]
assert len(MCU_L) == 25 and len(MCU_R) == 24
assert sorted(int(n) for n, _ in MCU_L + MCU_R) == list(range(1, 50))
_mh = 2.54 * 24
_mcu_pins = [(n, nm, -30.48, _mh / 2 - 2.54 * i, 0, 5.08, False) for i, (n, nm) in enumerate(MCU_L)]
_mcu_pins += [(n, nm, 30.48, _mh / 2 - 2.54 * i, 180, 5.08, False) for i, (n, nm) in enumerate(MCU_R)]
defsym("CH32M030C8U7", "U", _mcu_pins,
       [_rect(-25.4, _mh / 2 + 2.54, 25.4, -_mh / 2 - 2.54, fill="background")],
       show_pin_names=True, show_pin_numbers=True, ref_at=(-25.4, _mh / 2 + 6.35),
       val_at=(-25.4, _mh / 2 + 3.81))

# USB Type-C レセプタクル (USB2.0 16P)。同名ピンは同位置に重ね、片方を隠しピンにする。
_usb = []
for i, (nums, nm) in enumerate([(("A4", "A9", "B4", "B9"), "VBUS"), (("A5",), "CC1"), (("B5",), "CC2"),
                                (("A6", "B6"), "D+"), (("A7", "B7"), "D-"), (("A8",), "SBU1"),
                                (("B8",), "SBU2"), (("A1", "A12", "B1", "B12"), "GND"), (("S1",), "SHIELD")]):
    for k, n in enumerate(nums):
        _usb.append((n, nm, 10.16, 10.16 - 2.54 * i, 180, 2.54, k > 0))
defsym("USBC16", "J", _usb, [_rect(-7.62, 12.7, 7.62, -12.7, fill="background")],
       show_pin_names=True, show_pin_numbers=True, ref_at=(-7.62, 15.24), val_at=(-7.62, 13.97))
defsym("USBLC6", "U",
       [("1", "IO1", -10.16, 2.54, 0, 2.54, False), ("2", "GND", -10.16, 0, 0, 2.54, False),
        ("3", "IO2", -10.16, -2.54, 0, 2.54, False), ("6", "IO1", 10.16, 2.54, 180, 2.54, False),
        ("5", "VBUS", 10.16, 0, 180, 2.54, False), ("4", "IO2", 10.16, -2.54, 180, 2.54, False)],
       [_rect(-7.62, 5.08, 7.62, -5.08, fill="background")], show_pin_names=True,
       show_pin_numbers=True, ref_at=(-7.62, 7.62), val_at=(-7.62, 6.35))
# 理想ダイオードコントローラ LM74700-Q1 (SOT-23-6, KiCad 公式シンボルと同じピン番号)
defsym("LM74700", "U",
       [("6", "ANODE", -10.16, 2.54, 0, 2.54, False), ("3", "EN", -10.16, 0, 0, 2.54, False),
        ("1", "VCAP", -10.16, -2.54, 0, 2.54, False), ("4", "CATHODE", 10.16, 2.54, 180, 2.54, False),
        ("5", "GATE", 10.16, 0, 180, 2.54, False), ("2", "GND", 0, -7.62, 90, 2.54, False)],
       [_rect(-7.62, 5.08, 7.62, -5.08, fill="background")], show_pin_names=True,
       show_pin_numbers=True, ref_at=(-7.62, 9.4), val_at=(-7.62, 6.6))
# 4 端子水晶 (1-3 が振動子, 2-4 がケース GND)
defsym("XTAL4", "Y",
       [("1", "1", -5.08, 0, 0, 2.54, False), ("3", "3", 5.08, 0, 180, 2.54, False),
        ("2", "GND", 0, -5.08, 90, 3.048, False), ("4", "GND", 0, -5.08, 90, 3.048, True)],
       [_rect(-1.016, -1.778, 1.016, 1.778), _pl([(-2.032, -1.27), (-2.032, 1.27)]),
        _pl([(2.032, -1.27), (2.032, 1.27)]), _pl([(-2.54, 0), (-2.032, 0)]), _pl([(2.54, 0), (2.032, 0)])],
       ref_at=(0, 3.81), val_at=(0, -3.81))
defsym("D_SCH", "D", [("1", "K", -3.81, 0, 0, 2.54, False), ("2", "A", 3.81, 0, 180, 2.54, False)],
       [_pl([(1.27, 1.27), (1.27, -1.27), (-1.27, 0), (1.27, 1.27)]),
        _pl([(-1.778, 0.762), (-1.778, 1.27), (-1.27, 1.27), (-1.27, -1.27), (-0.762, -1.27), (-0.762, -0.762)])])


def lib_symbols_sexpr(used):
    out = ["(lib_symbols"]
    for name in sorted(used):
        s = SYMS[name]
        pn = "" if s["spn"] else "(pin_names hide) "
        pnum = "" if s["spnum"] else "(pin_numbers hide) "
        if s["spn"]:
            pn = "(pin_names (offset 0.508)) "
        out.append(f'(symbol "mdrv:{name}" {pnum}{pn}(in_bom yes) (on_board yes)')
        out.append(f'(property "Reference" "{s["prefix"]}" (at 0 0 0) (effects (font (size 1.27 1.27))))')
        out.append(f'(property "Value" "{name}" (at 0 0 0) (effects (font (size 1.27 1.27))))')
        out.append('(property "Footprint" "" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))')
        out.append('(property "Datasheet" "~" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))')
        out.append(f'(symbol "{name}_0_1" ' + " ".join(s["gfx"]) + ")")
        pins = []
        for num, nm, x, y, a, ln, hid in s["pins"]:
            h = " hide" if hid else ""
            pins.append(f'(pin passive line (at {x:g} {y:g} {a}) (length {ln:g}){h} '
                        f'(name "{nm}" (effects (font (size 1.016 1.016)))) '
                        f'(number "{num}" (effects (font (size 1.016 1.016)))))')
        out.append(f'(symbol "{name}_1_1" ' + " ".join(pins) + ")")
        out.append(")")
    out.append(")")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# 部品・シート
# ---------------------------------------------------------------------------
FP = {
    # 受動部品: 1005 / 1608 を基本とし, 耐圧・電流の都合で必要なものだけ大きくする (docs/design.md 表)
    "R1005": "Resistor_SMD:R_0402_1005Metric",
    "R1608": "Resistor_SMD:R_0603_1608Metric",
    "R1206": "Resistor_SMD:R_1206_3216Metric",
    "R2512": "Resistor_SMD:R_2512_6332Metric",
    "C1005": "Capacitor_SMD:C_0402_1005Metric",
    "C1608": "Capacitor_SMD:C_0603_1608Metric",
    "C2012": "Capacitor_SMD:C_0805_2012Metric",
    "CP6": "Capacitor_THT:CP_Radial_D6.3mm_P2.50mm",
    "CP8": "Capacitor_THT:CP_Radial_D8.0mm_P3.50mm",
    "TSON": "Package_SO:Vishay_PowerPAK_1212-8_Single",
    "TO263": "Package_TO_SOT_SMD:TO-263-2",
    "SOT23": "Package_TO_SOT_SMD:SOT-23",
    "QFN48": "CH32M030DS0_QFN48:CH32M030DS0_QFN48",
    "USBC": "Connector_USB:USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal",
    "SOT236": "Package_TO_SOT_SMD:SOT-23-6",
    "SOT89": "Package_TO_SOT_SMD:SOT-89-3",
    "SMA": "Diode_SMD:D_SMA",
    "SMB": "Diode_SMD:D_SMB",
    "SOD123": "Diode_SMD:D_SOD-123",
    "LED1608": "LED_SMD:LED_0603_1608Metric",
    "NANO2": "mPB:Fuse_Littelfuse_NANO2_2410",
    "FUSE1812": "Fuse:Fuse_1812_4532Metric",
    "PTC1206": "Fuse:Fuse_1206_3216Metric",
    "XTAL3225": "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm",
    "SW": "Button_Switch_SMD:SW_SPST_B3U-1000P",
    "HDR2": "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
    "HDR3": "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical",
    "HDR4": "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical",
    "HDR5": "Connector_PinHeader_2.54mm:PinHeader_1x05_P2.54mm_Vertical",
    "HDR8": "Connector_PinHeader_2.54mm:PinHeader_1x08_P2.54mm_Vertical",
    "HDR2x4": "Connector_PinHeader_2.54mm:PinHeader_2x04_P2.54mm_Vertical",
    "HDR2x5": "Connector_PinHeader_2.54mm:PinHeader_2x05_P2.54mm_Vertical",
    "HDR2x11": "Connector_PinHeader_2.54mm:PinHeader_2x11_P2.54mm_Vertical",
    "SOCK2x5": "Connector_PinSocket_2.54mm:PinSocket_2x05_P2.54mm_Vertical",
    "SOCK2x11": "Connector_PinSocket_2.54mm:PinSocket_2x11_P2.54mm_Vertical",
    "MH": "MountingHole:MountingHole_2.2mm_M2",
}


class Sheet:
    def __init__(self, key, title, page):
        self.key, self.title, self.page = key, title, page
        self.parts, self.texts, self.boxes = [], [], []
        self.wires, self.junctions, self.labels = [], [], []

    def add(self, sym, ref, value, x, y, rot=0, nets=None, fp="", dnp=False, mpn="", wired=()):
        """wired: 手配線するピン番号 (スタブ/ラベルを自動生成しない)。"""
        nets = nets or {}
        pins = {p[0] for p in SYMS[sym]["pins"] if not p[6]}
        assert set(nets) == pins, f"{ref}: pins {sorted(pins)} vs nets {sorted(nets)}"
        assert fp in FP or ":" in fp or not pins, f"{ref}: unknown footprint {fp}"
        self.parts.append(dict(sym=sym, ref=ref, value=value, x=x, y=y, rot=rot, nets=nets,
                               fp=FP.get(fp, fp), dnp=dnp, mpn=mpn, wired=set(wired)))
        return self.parts[-1]

    def pin(self, part, num):
        """部品ピンの回路図座標."""
        q = next(q for q in SYMS[part["sym"]]["pins"] if q[0] == num)
        return xform(part["x"], part["y"], part["rot"], q[2], q[3])

    def wire(self, *pts):
        for a, b in zip(pts, pts[1:]):
            self.wires.append((a, b))

    def junction(self, x, y):
        self.junctions.append((x, y))

    def label(self, net, x, y, ang):
        """(x, y) から ang 方向へ 2.54mm のスタブを引き、その先にラベルを置く."""
        d = {0: (2.54, 0), 180: (-2.54, 0), 90: (0, -2.54), 270: (0, 2.54)}[ang]
        e = (x + d[0], y + d[1])
        self.wires.append(((x, y), e))
        self.labels.append((net, e[0], e[1], ang))

    def text(self, s, x, y, size=1.8):
        self.texts.append((s, x, y, size))

    def box(self, x0, y0, x1, y1, title):
        self.boxes.append((x0, y0, x1, y1, title))


def xform(px, py, rot, lx, ly):
    """lib 座標 -> 回路図座標 (y 下向き, rot は画面上の反時計回り)."""
    x, y = lx, -ly
    r = math.radians(rot)
    c, s = round(math.cos(r)), round(math.sin(r))
    return px + x * c + y * s, py - x * s + y * c


OUTWARD = {0: (-1, 0), 180: (1, 0), 90: (0, -1), 270: (0, 1)}  # lib 座標での外向き




# ---------------------------------------------------------------------------
# 部品定数 (コンデンサは入手性を確認した量産品番。1005/1608 を基本とする)
# ---------------------------------------------------------------------------
C_100N = ("0.1uF/50V", "C1005", "Murata GRM155R71H104KE14D (X7R 1005)")
C_1U25 = ("1uF/25V", "C1005", "Murata GRM155R61E105KA12D (X5R 1005)")
C_1U50 = ("1uF/50V", "C1608", "Murata GRM188R61H105KAALD (X5R 1608)")
C_2U2 = ("2.2uF/25V", "C1608", "Murata GRM188R61E225KA12D (X5R 1608)")
C_4U7 = ("4.7uF/10V", "C1005", "Murata GRM155R61A475MEAAD (X5R 1005)")
C_10U25 = ("10uF/25V", "C1608", "Murata GRM188R61E106MA73D (X5R 1608)")
C_10U50 = ("10uF/50V", "C2012", "TDK C2012X5R1H106K125AC (X5R 2012) ※50V/10uF は 1608 の量産品なし")
C_10N = ("10nF/50V", "C1005", "Murata GRM155R71H103KA88D (X7R 1005)")
C_1N = ("1nF/50V", "C1005", "Murata GRM155R71H102KA01D (X7R 1005)")
C_1N_C0G = ("1nF C0G", "C1005", "Murata GRM1555C1H102JA01D (C0G 1005)")
C_2N2_C0G = ("2.2nF C0G", "C1005", "Murata GRM1555C1H222JA01D (C0G 1005)")
C_30P = ("30pF C0G", "C1005", "Murata GRM1555C1H300JA01D (C0G 1005)")
C_4N7_100 = ("4.7nF/100V", "C1005", "Murata GRM155R72A472KA01D (X7R 1005)")


def cap(sh, ref, spec, x, y, n1, n2, rot=90, **kw):
    val, fp, mpn = spec
    return sh.add("C", ref, val, x, y, rot=rot, nets={"1": n1, "2": n2}, fp=fp, mpn=mpn, **kw)


def res(sh, ref, val, x, y, n1, n2, rot=90, fp="R1005", **kw):
    return sh.add("R", ref, val, x, y, rot=rot, nets={"1": n1, "2": n2}, fp=fp, **kw)


# ---------------------------------------------------------------------------
# 基板間コネクタ (主基板の裏面ピンヘッダ ⇔ 子基板の裏面ピンソケット, 裏面同士を向かい合わせ)
#   子基板のソケットを 270° 回転して裏面に置くと, 裏返して重ねたときに同じ番号のピン同士が
#   嵌合する (gen_pcb.py の mate_socket() がパッド座標で検証)。よってピン割当は主基板と同一。
# ---------------------------------------------------------------------------
B2B_PWR = {str(n): ("VBUS" if n % 2 else "GND") for n in range(1, 11)}
B2B_SIG_ORDER = ["HO0", "SW0", "LO0", "GND", "HO1", "SW1", "LO1", "ISA_SEL",
                 "HO2", "SW2", "LO2", "GND", "HO3", "SW3", "LO3", "ISB_SEL",
                 "ISH", "GND", "BEMF_U", "BEMF_V", "BEMF_W", "NTC"]
B2B_SIG = {str(i + 1): n for i, n in enumerate(B2B_SIG_ORDER)}


def mated(pinmap):
    """主基板側ピン割当 → 背中合わせに重ねた子基板側ソケットのピン割当 (同一番号で嵌合)."""
    return dict(pinmap)


class Project:
    def __init__(self, name, subdir, title, notes):
        self.name, self.subdir, self.title, self.notes = name, subdir, title, notes
        self.sheets = []

    def sheet(self, key, title):
        sh = Sheet(key, title, len(self.sheets) + 2)
        self.sheets.append(sh)
        return sh


PROJECTS = []


# ===========================================================================
# 主基板 (MCU / USB / 電源 / I/O)。パワー段は子基板 (daughter/) に分離
# ===========================================================================
def build_main():
    prj = Project("mPBCH32M030DS0", ".", "mPBCH32M030DS0  CH32M030 Universal Motor Driver - Main board", [
        "mPBCH32M030DS0 Rev 0.3 主基板 — CH32M030C8U7 (QFN48) ユニバーサル・モータードライバ (3相 ・ DC x2 ・ ステッピング)",
        "",
        "・2 層基板 60 x 42mm。部品面 (TOP): 右 = MCU / USB-C / GPIO・I2C・UART・SDI・HALL, 左上 = 電源, 左下 = 基板間コネクタ",
        "・パワー段 (MOSFET x8, シャント, ゲート確認 LED, 相電圧分圧, NTC, バルク容量) は子基板へ分離し, 裏面同士を",
        "  向かい合わせて J9 (電源 2x5) / J10 (信号 2x11) で接続する (基板間 約5mm, 裏面部品は高さ 2mm 以下)。",
        "   子基板 A: TPN1R603PL (既存回路, 8〜16V)   B: TKR74F04PB (24V 系)   C: MTN2306AN3 (廉価, ≤3A)   D: MOSFET なし (ピン出し)",
        "・コネクタはすべて 2.54mm ピンヘッダ (USB-C を除く)。操作系 (RESET, USER/BOOT, センシング選択 JP2-4/JP8) は TOP 面",
        "・電源: J1 (2x4 ピン, 8〜16V / 24V 系は注記の部品に変更) と USB-C PD (9/12/15V) を理想ダイオード OR",
        "・PWM: HB0〜HB2 = TIM1, HB2/HB3 = TIM2 リマップ2。電流: OPA3/OPA4 → ADC, CMP3 or CMP2(+DAC) → TIM1 ブレーキ",
        "・3 相センシング PA5/PA6/PA7 (CMP3 + 仮想中性点 + TIM2) / ホール XOR, QII1 タコ入力, NTC (子基板の MOSFET 近傍)",
        "",
        "詳細は README.md, docs/design.md, docs/stacking.md, docs/advanced_features.md を参照。",
    ])

    # ===== 1. 電源 =====
    pw = prj.sheet("power", "電源入力・保護・補助電源・電源表示")
    pw.box(20, 25, 200, 150, "電源入力 (J1 2x4 ピン) / 理想ダイオード (逆接・逆流防止) / サージ保護")
    pw.add("CONN2x4", "J1", "PWR_IN", 40, 50,
           nets={str(n): ("VIN" if n % 2 else "GND") for n in range(1, 9)}, fp="HDR2x4",
           mpn="2.54mm 2x4 ピンヘッダ (奇数=VIN, 偶数=GND: 4 ピン並列で約 10A)")
    f1 = pw.add("FUSE", "F1", "10A", 70, 50, rot=90, nets={"1": "VIN", "2": "VIN_F"}, fp="NANO2",
                mpn="Littelfuse 0451010.MRL (NANO2 2410, 10A 速断)", wired=("2",))
    # J1 側 理想ダイオード: Q9 (S=入力, D=VBUS) + U4 LM74700 (ANODE=VIN_F, CATHODE=VBUS)
    pw.add("NMOS", "Q9", "TPN2R304PL", 95, 50, rot=270, nets={"1": "VIN_F", "4": "Q9_G", "5": "VBUS"},
           fp="TSON", mpn="Toshiba TPN2R304PL,L1Q (40V 2.3mΩ, J1 側 理想ダイオード)", wired=("1", "5"))
    pw.wire(pw.pin(f1, "2"), (89.92, 50))
    pw.junction(82, 50)
    pw.label("VIN_F", 82, 50, 90)
    pw.wire((100.08, 50), (195, 50))
    pw.label("VBUS", 195, 50, 0)
    pw.add("LM74700", "U4", "LM74700-Q1", 70, 105,
           nets={"6": "VIN_F", "3": "VIN_F", "1": "VCAP1", "4": "VBUS", "5": "Q9_G", "2": "GND"},
           fp="SOT236", mpn="TI LM74700QDBVRQ1")
    cap(pw, "C5", C_100N, 110, 105, "VCAP1", "VIN_F", rot=0)
    pw.wire((125, 75), (185, 75))
    pw.label("GND", 185, 75, 0)
    for x, (ref, sym, val, fp, mpn) in zip((125, 150), [
            ("D1", "D_TVS", "SMBJ16A", "SMB", "SMBJ16A (12V 系) / 24V 系は SMBJ24A に変更"),
            ("C1", "C", C_10U50[0], C_10U50[1], C_10U50[2])]):
        rot = 270 if sym == "D_TVS" else 0
        pw.add(sym, ref, val, x, 62.5, rot=rot, nets={"1": "VBUS", "2": "GND"}, fp=fp, mpn=mpn, wired=("1", "2"))
        pw.wire((x, 50), (x, 58.69))
        pw.wire((x, 66.31), (x, 75))
        pw.junction(x, 50)
        if x != 125:
            pw.junction(x, 75)
    pw.text("U4+Q9: 逆接続 (最大 -65V) と VBUS→J1 への逆流を阻止する理想ダイオード。Q9 は 40V 品 (24V 系と共通)。", 25, 123, 1.4)
    pw.text("J1 と USB-PD (下) は理想ダイオード OR。バルク容量は子基板の MOSFET 近傍に置く (C1 は局所バイパス)。", 25, 128, 1.4)
    pw.text("12V 系: D1=SMBJ16A, R11=110k (OVP 18V)。24V 系 (子基板 B): D1=SMBJ24A, R11=180k (OVP 28.5V)。", 25, 133, 1.4)
    pw.text("CH32M030 の VS 絶対最大 30V / VHV 動作 5〜28V → 24V 系は安定化電源専用 (回生・サージで 28V を超えないこと)。", 25, 138, 1.4)
    pw.text("J1 はピンヘッダ 4 ピン並列 (約 10A)。それ以上は J1 のランドへ線材を直接はんだ付けする。", 25, 143, 1.4)

    pw.box(20, 160, 250, 280, "USB-PD 給電パス (PD 契約後に MCU が許可, 最大 15V / 5A)")
    pw.add("FUSE", "F3", "5A", 50, 185, rot=90, nets={"1": "USB_VBUS", "2": "USB_VBUS_P"}, fp="FUSE1812",
           mpn="1812 5A 速断ヒューズ (例: Bourns SF-1812F500)")
    pw.add("D_TVS", "D9", "SMAJ20A", 75, 205, rot=270, nets={"1": "USB_VBUS_P", "2": "GND"}, fp="SMA",
           mpn="SMAJ20A (USB 側サージ)")
    pw.add("NMOS", "Q10", "TPN1R603PL", 125, 185, rot=270, nets={"1": "USB_VBUS_P", "4": "Q10_G", "5": "VBUS"},
           fp="TSON", mpn="Toshiba TPN1R603PL,L1Q (USB 側 理想ダイオード)")
    pw.add("LM74700", "U5", "LM74700-Q1", 125, 225,
           nets={"6": "USB_VBUS_P", "3": "PD_PWR_EN", "1": "VCAP2", "4": "VBUS", "5": "Q10_G", "2": "GND"},
           fp="SOT236", mpn="TI LM74700QDBVRQ1")
    cap(pw, "C6", C_100N, 165, 225, "VCAP2", "USB_VBUS_P", rot=0)
    res(pw, "R6", "100k", 190, 225, "PD_PWR_EN", "GND", rot=0)
    res(pw, "R7", "120k 1%", 215, 190, "USB_VBUS_P", "USB_VBUS_SNS", rot=0)
    res(pw, "R8", "10k 1%", 215, 237, "USB_VBUS_SNS", "GND", rot=0)
    cap(pw, "C7", C_10N, 237, 237, "USB_VBUS_SNS", "GND", rot=0)
    pw.text("PD_PWR_EN (PC3) = Low/リセット中は OFF (R6)。FW は PS_RDY 受信 + USB_VBUS_SNS (PA2) で電圧確認後に ON。", 23, 255, 1.3)
    pw.text("PB4 の OVP リセットで MCU がリセットされると EN も Low → USB 給電も自動遮断。", 23, 260, 1.3)
    pw.text("USB_VBUS_SNS = USB VBUS / 13 (20V → 1.54V)。", 23, 265, 1.3)
    pw.text("VBUS の突入: 子基板のバルク容量を PD 電源で充電するため FW は EN ON 後に電流を段階的に上げる。", 23, 270, 1.3)

    pw.box(210, 25, 405, 95, "5V 補助電源 (ホールセンサ用) / 電源表示 LED")
    pw.add("REG3", "U2", "78L05", 280, 50, nets={"3": "VBUS", "1": "+5V", "2": "GND"}, fp="SOT89",
           mpn="78L05 (SOT-89, Vin ≤30V)", wired=("3", "1", "2"))
    pw.wire((272.38, 50), (240, 50))
    pw.label("VBUS", 240, 50, 180)
    pw.wire((287.62, 50), (345, 50))
    pw.label("+5V", 345, 50, 0)
    pw.wire((250, 75), (335, 75))
    pw.label("GND", 250, 75, 180)
    pw.wire((280, 55.08), (280, 75))
    pw.junction(280, 75)
    for x, ref, spec, net in ((255, "C3", C_1U50, "VBUS"), (305, "C4", C_1U25, "+5V")):
        cap(pw, ref, spec, x, 62.5, net, "GND", rot=0, wired=("1", "2"))
        pw.wire((x, 50), (x, 58.69))
        pw.wire((x, 66.31), (x, 75))
        pw.junction(x, 50)
    pw.junction(305, 75)
    res(pw, "R3", "2.2k", 335, 58, "+5V", "LED5_A", rot=0, wired=("1", "2"))
    pw.wire((335, 50), (335, 54.19))
    pw.junction(335, 50)
    pw.add("LED", "D2", "GREEN 5V", 335, 67, rot=90, nets={"2": "LED5_A", "1": "GND"}, fp="LED1608",
           wired=("2", "1"))
    pw.wire((335, 61.81), (335, 63.19))
    pw.wire((335, 70.81), (335, 75))
    for x, ref_r, val_r, ref_d, val_d, net in ((362, "R4", "15k", "D7", "RED VBUS", "VBUS"),
                                                (385, "R5", "1.5k", "D8", "GREEN 3V3", "+3V3")):
        res(pw, ref_r, val_r, x, 50, net, f"LED_{ref_d}_A", rot=0, wired=("2",))
        pw.add("LED", ref_d, val_d, x, 62, rot=90, nets={"2": f"LED_{ref_d}_A", "1": "GND"}, fp="LED1608",
               wired=("2",))
        pw.wire((x, 53.81), (x, 58.19))
    pw.text("D7: モータ電源 (VBUS, 12V で 0.6mA / 24V で 1.5mA)  D2: +5V  D8: MCU 電源 (VDD33)", 213, 85, 1.4)
    pw.text("VDD33 の負荷上限は 20mA (DS 表3-4) → D8 は 1.5k で約 0.9mA に抑える。", 213, 90, 1.4)

    pw.box(210, 100, 405, 160, "MCU 電源 VHV (VBUS / USB 5V のダイオード OR + 27V クランプ)")
    pw.add("D_SCH", "D5", "B5819W", 250, 115, rot=180, nets={"1": "VHV_IN", "2": "VBUS"}, fp="SOD123",
           mpn="B5819W (40V 1A ショットキー)", wired=("1",))
    pw.add("D_SCH", "D6", "B5819W", 250, 128, rot=180, nets={"1": "VHV_IN", "2": "USB_VBUS_F"}, fp="SOD123",
           mpn="B5819W (40V 1A ショットキー)", wired=("1",))
    pw.wire((253.81, 115), (271.19, 115))
    pw.wire((253.81, 128), (265, 128), (265, 115))
    pw.junction(265, 115)
    res(pw, "R10", "47R", 275, 115, "VHV_IN", "VHV", fp="R1608", wired=("1",))
    pw.add("D_ZENER", "D4", "MMSZ5254B 27V", 300, 128, rot=90, nets={"1": "VHV", "2": "GND"}, fp="SOD123",
           mpn="MMSZ5254B (27V 500mW, VHV 絶対最大 30V の保護)")
    pw.text("USB のみ給電時 VHV ≈ 4.4V (≥ 4.0V で MCU 動作)。ゲート駆動は VBUS ≥ 8V を FW で確認してから許可。", 213, 145, 1.3)
    pw.text("R10 47Ω + D4 27V: 24V 系のサージで VHV が 30V を超えないようにする (MCU 消費 ≤35mA で降下 ≤1.7V)。", 213, 150, 1.3)
    pw.text("USB のみ給電では VHV < 5V となり PA0〜PA3 の出力 High が VDD33-1.7V に下がる (DS 注5)。", 213, 155, 1.3)

    # ===== 2. USB / 水晶 / リセット =====
    us = prj.sheet("usb", "USB Type-C / 水晶発振子 / リセット")
    us.box(20, 25, 250, 150, "USB Type-C (USB2.0 FS デバイス / PD シンク)")
    us.add("USBC16", "J8", "USB-C", 60, 80,
           nets={"A4": "USB_VBUS", "A5": "USB_CC1", "B5": "USB_CC2", "A6": "USB_DP", "A7": "USB_DN",
                 "A8": None, "B8": None, "A1": "GND", "S1": "USB_SHIELD"},
           fp="USBC", mpn="GCT USB4105-GF-A (USB-C 16P)")
    us.add("FUSE", "F2", "PTC 0.5A", 120, 50, rot=90, nets={"1": "USB_VBUS", "2": "USB_VBUS_F"}, fp="PTC1206",
           mpn="ポリスイッチ 0.5A 1206 (例: Bourns MF-NSMF050)")
    us.add("USBLC6", "U3", "USBLC6-2SC6", 175, 85,
           nets={"1": "USB_DP", "2": "GND", "3": "USB_DN", "6": "USB_DP", "5": "+3V3", "4": "USB_DN"},
           fp="SOT236", mpn="ST USBLC6-2SC6 (D+/D- ESD 保護, 基準は +3V3)")
    res(us, "R130", "1M", 120, 110, "USB_SHIELD", "GND")
    cap(us, "C130", C_4N7_100, 120, 122, "USB_SHIELD", "GND")
    us.text("CC1/CC2 = PA0/PA1 (CC1R/CC2R): C8U7 は Type-C 規定の Rd 5.1kΩ を内蔵 → 外付け Rd 不要。", 23, 135, 1.3)
    us.text("D+/D- = PB0/PB1 直結 (USBFS の D+ プルアップ内蔵)。USB_VBUS は F2→D6 で VHV, F3→U5/Q10 で VBUS へ。", 23, 140, 1.3)
    us.text("USB PD シンク: 9/12/15V を要求し U5/Q10 経由でモータ電源 VBUS に供給できる。", 23, 145, 1.3)

    us.box(260, 25, 405, 100, "水晶発振子 (HSE 8MHz)")
    us.add("XTAL4", "Y1", "8MHz CL=20pF", 330, 55, nets={"1": "XI", "3": "XO", "2": "GND"}, fp="XTAL3225",
           mpn="8MHz 3225 4pad, CL=20pF, ESR≤60Ω (例: Abracon ABM8-8.000MHZ-B2-T)")
    cap(us, "C131", C_30P, 300, 72, "XI", "GND", rot=0)
    cap(us, "C132", C_30P, 360, 72, "XO", "GND", rot=0)
    us.text("XI=PB5 / XO=PB6。帰還抵抗は内蔵。C = 2 x (CL - 浮遊容量 約5pF) = 30pF。", 263, 90, 1.3)
    us.text("HSE 8MHz x PLL18 = 144MHz → SYSCLK 72MHz / USB 48MHz。水晶の真下は GND ベタ, 配線は最短。", 263, 95, 1.3)

    us.box(260, 110, 405, 190, "リセット (RST = PC0)  ※ TOP 面")
    us.add("SW", "SW1", "RESET", 340, 140, nets={"1": "nRST", "2": "GND"}, fp="SW", mpn="Omron B3U-1000P (3x2.5mm SMD タクト, 上押し)")
    res(us, "R131", "10k", 290, 130, "+3V3", "nRST")
    cap(us, "C133", C_100N, 290, 150, "nRST", "GND")
    us.text("RST ピンはユーザオプションバイトで選択: RST_PIN_SEL=0 → PC0, RST_MODE で有効化", 263, 175, 1.3)
    us.text("(WCH-LinkUtility で設定, 出荷時は無効の可能性)。無効時は PC0 は通常 GPIO。", 263, 180, 1.3)

    us.box(20, 160, 250, 280, "メモ")
    for k, line in enumerate([
        "・USB は設定変更・ログ・FW 更新 (IAP) 用。IAP 起動判定は PC4 (USER/BOOT ボタン)",
        "・PA3 (SWIO) は 1 線デバッグ専用。PA2 (SWCLK/CC3) は USB VBUS 監視に転用",
        "・USB-C シールドは 1MΩ || 4.7nF で GND へ (ESD 逃がし)",
        "・USB-C は主基板の右辺 (MCU 近傍)。PD 給電パス F3/U5/Q10 は左上の電源エリアへ太パターンで接続",
    ]):
        us.text(line, 23, 175 + k * 7, 1.4)

    # ===== 3. MCU =====
    mc = prj.sheet("mcu", "CH32M030C8U7 (QFN48) / ゲートドライバ周辺")
    MCU_NETS = {
        "34": "VHV", "26": "VDD8", "33": "+3V3", "49": "GND",
        "37": "USB_VBUS_SNS", "38": "SWDIO", "35": "USB_CC1", "36": "USB_CC2", "39": "USB_DP", "40": "USB_DN",
        "8": "XI", "9": "XO", "27": "nRST", "28": "UART_TX", "29": "UART_RX",
        "30": "PD_PWR_EN", "31": "GPIO_PC4", "32": "GPIO_PC5",
        "3": "I2C_SDA", "4": "I2C_SCL", "2": "nFAULT", "43": "SENS_W", "7": "VBUS_SNS",
        "6": "IBUS_F", "5": "OCP_REF",
        "46": "IA_P", "45": "IA_N", "47": "IB_P", "48": "IB_N", "41": "NTC",
        "42": "SENS_U", "44": "SENS_V", "1": "QII_IN",
    }
    for i, pins in enumerate((("13", "12", "11", "10"), ("17", "16", "15", "14"),
                              ("21", "20", "19", "18"), ("25", "24", "23", "22"))):
        for pn, net in zip(pins, (f"HO{i}", f"VB{i}", f"SW{i}", f"LO{i}")):
            MCU_NETS[pn] = net
    mc.add("CH32M030C8U7", "U1", "CH32M030C8U7", 205, 125, nets=MCU_NETS, fp="QFN48",
           mpn="WCH CH32M030C8U7 (QFN48 5x5mm 0.35mm pitch)")

    mc.box(15, 20, 130, 95, "電源デカップリング (ピン直近, DS 図3-1-1)")
    for j, (ref, spec, n1) in enumerate([
        ("C10", C_10U50, "VHV"), ("C11", C_100N, "VHV"),
        ("C12", C_10U25, "VDD8"), ("C13", C_100N, "VDD8"),
        ("C14", C_4U7, "+3V3"), ("C15", C_100N, "+3V3"),
    ]):
        cap(mc, ref, spec, 45 + (j % 2) * 45, 35 + (j // 2) * 16, n1, "GND")
    mc.text("VHV 5〜28V (≥10uF)。VDD8 は FW で 5/8/9/10V 選択 (≥10uF)。VDD33 は 1〜10uF (DS 1.4.3)。", 18, 85, 1.3)
    mc.text("LDO 負荷上限: VDD8 35mA (ゲート駆動+VDD33 含む) / VDD33 20mA。QFN 裏面パッドが唯一の GND。", 18, 90, 1.3)

    mc.box(15, 100, 130, 205, "VBUS 監視・過電圧リセット / バス電流 / 過電流比較")
    for j, (ref, sym, val, n1, n2) in enumerate([
        ("R11", "R", "110k 1%", "VBUS", "VBUS_SNS"),
        ("R12", "R", "10k 1%", "VBUS_SNS", "GND"),
        ("C16", "C", C_10N, "VBUS_SNS", "GND"),
        ("R13", "R", "1k", "ISH", "IBUS_F"),
        ("C17", "C", C_1N_C0G, "IBUS_F", "GND"),
        ("R14", "R", "12k 1%", "+3V3", "OCP_REF"),
        ("R15", "R", "1k 1%", "OCP_REF", "GND"),
        ("C18", "C", C_100N, "OCP_REF", "GND"),
    ]):
        x, y = 45 + (j % 2) * 45, 115 + (j // 2) * 16
        if sym == "C":
            cap(mc, ref, val, x, y, n1, n2)
        else:
            res(mc, ref, val, x, y, n1, n2, mpn="24V 系は 180k 1%" if ref == "R11" else "")
    mc.text("PB4: VBUS/12 → ADC_IN17 + OVP リセット (1.5V → 18.0V)。24V 系は R11=180k (VBUS/19, 28.5V)。", 18, 182, 1.25)
    mc.text("PB3: バス電流 ADC_IN1 (10mΩ: 1A = 10mV) + CMP3_P3。PB2: 閾値 254mV (25.4A) = CMP3_N3 / ADC_IN0。", 18, 188, 1.25)
    mc.text("ISH / ISA_SEL / ISB_SEL は子基板のシャントから J10 経由で来る (ケルビン配線)。", 18, 194, 1.25)

    mc.box(280, 20, 405, 110, "電流アンプ入力 (OPA3=ISP1 / OPA4=ISP2 → ADC 内部接続)")
    for j, (ref, sym, val, n1, n2) in enumerate([
        ("R16", "R", "100R 1%", "ISA_SEL", "IA_P"),
        ("R17", "R", "100R 1%", "ISH", "IA_N"),
        ("C19", "C", C_2N2_C0G, "IA_P", "IA_N"),
        ("R18", "R", "100R 1%", "ISB_SEL", "IB_P"),
        ("R19", "R", "100R 1%", "ISH", "IB_N"),
        ("C20", "C", C_2N2_C0G, "IB_P", "IB_N"),
    ]):
        x, y = 310 + (j % 2) * 55, 35 + (j // 2) * 16
        if sym == "C":
            cap(mc, ref, val, x, y, n1, n2)
        else:
            res(mc, ref, val, x, y, n1, n2)
    mc.text("OPA3 出力 → ADC_IN9, OPA4 出力 → ADC_IN10 (チップ内部接続)。電流チャネル選択 JP5/JP7 は子基板。", 283, 90, 1.25)
    mc.text("ゲイン 4/8/16/55, バイアス 1.6V (10mΩ: G55=±2.9A, G16=±10A, G8=±20A)。", 283, 95, 1.25)
    mc.text("CMP2: P=OPA3 出力, N=内蔵 DAC (0.1〜3.1V/0.2V) → TIM1 BKIN。", 283, 100, 1.25)

    mc.box(280, 115, 405, 205, "ブートストラップ容量 (VBx-VSx, MCU ピン直近 = 主基板)")
    for i in range(4):
        cap(mc, f"C{21 + i}", C_2U2, 310 + (i % 2) * 55, 130 + (i // 2) * 18, f"VB{i}", f"SW{i}")
    mc.text("ブートストラップダイオード内蔵 (平均 7mA / ピーク 70mA まで)。DS 推奨 1〜10uF。", 283, 175, 1.25)
    mc.text("2.2uF (1608, DC バイアス後 ≈1.3uF): Qg 41nC (A) で降下 32mV, Qg ≈150nC (B) でも ≈0.12V。", 283, 180, 1.25)

    mc.box(20, 212, 290, 285, "ピン割当の要点 (QFN48 = CH32M030C8U7)")
    for k, line in enumerate([
        "PWM: HB0〜HB2 = TIM1 (相補+ブレーキ)。HB2/HB3 を TIM2 リマップ2 (PB12〜PB15) で駆動すれば 4 レッグ全て相補",
        "電流: IA = OPA3 (子基板 JP7: HB0 / バス) → ADC9, IB = OPA4 (子基板 JP5: HB1 / HB2) → ADC10, IBUS = PB3",
        "保護: CMP3 (PB3 vs PB2) または CMP2 (OPA3 出力 vs 内蔵 DAC) → TIM1 BKIN。PB4 OVP リセット",
        "3 相センシング PA5/PA6/PA7 = CMP3 N0/N1/N2 (仮想中性点 + TIM2 キャプチャ) = TIM2 CH1/2/3 (ホール XOR)",
        "QII1: PA12 → OPA1 (AV20/40) → CMP1 → TIM3 CH1 キャプチャ (JP8: タコ/VR 入力 or バス電流リップル)",
        "USB: CC1/CC2 = PA0/PA1 (PD0 シンク), D+/D- = PB0/PB1, USB VBUS 監視 = PA2, PD 給電許可 = PC3",
        "I2C: PA14/PA15 (リマップ2)。UART: PC1/PC2 (リマップ1)。RST: PC0。SDI 1 線: PA3。水晶: PB5/PB6",
        "J6 引き出し: PC4 (USER/BOOT + 状態 LED), PC5 (HV I/O), TACH_IN, nFAULT (PA13 = TIM1_BKIN_1)",
    ]):
        mc.text(line, 25, 224 + k * 7, 1.4)

    # ===== 4. 基板間コネクタ / センシング選択 =====
    bb = prj.sheet("b2b", "基板間コネクタ (子基板) / 3 相センシング選択")
    bb.box(15, 20, 200, 190, "子基板コネクタ (主基板 裏面に実装, 子基板の裏面ソケットと背中合わせ)")
    bb.add("CONN2x5", "J9", "B2B_PWR", 60, 45, nets=B2B_PWR, fp="HDR2x5",
           mpn="2.54mm 2x5 ピンヘッダ (裏面実装, 奇数=VBUS / 偶数=GND, 5 ピン並列 ≈10A)")
    bb.add("CONN2x11", "J10", "B2B_SIG", 60, 90, nets=B2B_SIG, fp="HDR2x11",
           mpn="2.54mm 2x11 ピンヘッダ (裏面実装)")
    bb.text("子基板側は同配列のピンソケット (低背, 嵌合高さ ≈5mm)。子基板のソケットは 270° 回転で裏面に置き,", 20, 160, 1.3)
    bb.text("同じ番号のピン同士が嵌合する (gen_pcb.py が座標で検証)。GND はゲート駆動の帰路を兼ねて J10 に 3 本。", 20, 166, 1.3)
    bb.text("SWx はブートストラップ容量の帰路 (VSx) と相電圧, HOx/LOx はゲート駆動 (ゲート抵抗は子基板)。", 20, 172, 1.3)
    bb.text("ISA_SEL / ISB_SEL / ISH は子基板シャントのケルビン検出。NTC は子基板の MOSFET 近傍に実装。", 20, 178, 1.3)
    for k, ref in enumerate(("H1", "H2", "H3")):
        bb.add("MH", ref, "M2", 30 + 20 * k, 200, nets={}, fp="MH", mpn="M2 取付穴 (子基板と共通位置, 5mm スペーサ)")
    bb.box(210, 20, 405, 120, "相電圧 (BEMF) / ホール 切替 → PA5/PA6/PA7 (CMP3 N0-N2 = TIM2 CH1-3)  ※ TOP 面")
    for k, ph in enumerate("UVW"):
        xb = 240 + k * 55
        bb.add("CONN3", f"JP{2 + k}", f"SEL_{ph}", xb, 50,
               nets={"1": f"BEMF_{ph}", "2": f"SENS_{ph}", "3": f"HALL_{'ABC'[k]}"}, fp="HDR3",
               mpn="2.54mm 3P + ジャンパ (1-2: 相電圧 / 2-3: HALL)")
    bb.text("BEMF_U/V/W は子基板で分圧済み (A/C: 3/23, B: 3.3/50.3)。", 213, 100, 1.3)
    bb.text("センサレス: CMP3 が各相を内部仮想中性点と比較し TIM2 でゼロクロス時刻を捕捉。", 213, 106, 1.3)
    bb.text("ホール: 同じ 3 ピンが TIM2 CH1-3 → ホールセンサ XOR モードでハード計時。", 213, 112, 1.3)

    # ===== 5. I/O =====
    io = prj.sheet("io", "インターフェース (ホール / 通信 / GPIO 引き出し / UI)")
    io.box(15, 20, 200, 120, "ホールセンサ入力 (J3 ピンヘッダ)")
    io.add("CONN5", "J3", "HALL", 40, 40,
           nets={"1": "+5V", "2": "GND", "3": "HALL_A_IN", "4": "HALL_B_IN", "5": "HALL_C_IN"}, fp="HDR5",
           mpn="2.54mm 1x5 ピンヘッダ")
    for k, h in enumerate("ABC"):
        yb = 40 + k * 22
        res(io, f"R{100 + 3 * k}", "4.7k", 100, yb, f"HALL_{h}_IN", "+3V3")
        res(io, f"R{101 + 3 * k}", "1k", 150, yb, f"HALL_{h}_IN", f"HALL_{h}")
        cap(io, f"C{100 + k}", C_1N, 150, yb + 9, f"HALL_{h}", "GND")
    io.text("プルアップは 3.3V (MCU 入力保護)。5V プッシュプル出力のホールは 1k 直列で電流制限 (注入 ≤4mA)。", 18, 112, 1.3)

    io.box(210, 20, 405, 120, "温度検出 (NTC は子基板) / USER・BOOT ボタン + 状態 LED (PC4 共用)")
    cap(io, "C103", C_100N, 235, 45, "NTC", "GND", rot=0)
    res(io, "R110", "10k", 260, 45, "+3V3", "NTC", rot=0, dnp=True)
    io.text("NTC は PA4 (ISOURCE1 内蔵電流源) → ADC_IN5。R110 (DNP) で分圧方式にも変更可。", 213, 65, 1.3)
    io.add("SW", "SW2", "USER/BOOT", 330, 45, nets={"1": "GPIO_PC4", "2": "GND"}, fp="SW",
           mpn="Omron B3U-1000P (3x2.5mm SMD タクト, 上押し)")
    res(io, "R111", "10k", 370, 45, "+3V3", "GPIO_PC4", rot=0)
    io.add("LED", "D3", "GREEN STAT", 250, 92, rot=180, nets={"2": "+3V3", "1": "LED_STAT_K"}, fp="LED1608")
    res(io, "R112", "1k", 290, 92, "LED_STAT_K", "GPIO_PC4")
    io.text("状態 LED = PC4 Low で点灯 (USER/BOOT ボタンと共用, ボタン押下中も点灯)。", 213, 110, 1.3)

    io.box(15, 130, 200, 280, "通信 (I2C / UART) / デバッグ (WCH-LinkE 1 線 SDI)")
    io.add("CONN4", "J4", "I2C", 40, 150, nets={"1": "GND", "2": "+3V3", "3": "I2C_SDA", "4": "I2C_SCL"},
           fp="HDR4", mpn="2.54mm 1x4 ピンヘッダ (Qwiic/STEMMA QT と同じ並び)")
    res(io, "R114", "4.7k", 120, 150, "+3V3", "I2C_SDA", dnp=True)
    res(io, "R115", "4.7k", 120, 162, "+3V3", "I2C_SCL", dnp=True)
    io.add("CONN4", "J5", "UART", 40, 195, nets={"1": "GND", "2": "+3V3", "3": "UART_TX", "4": "UART_RX"},
           fp="HDR4", mpn="2.54mm 1x4 ピンヘッダ")
    io.add("CONN4", "J7", "SDI", 40, 235,
           nets={"1": "+3V3", "2": "SWDIO", "3": "nRST", "4": "GND"}, fp="HDR4",
           mpn="2.54mm 1x4 ピンヘッダ (WCH-LinkE 1 線 SDI: 3V3/SWIO/RST/GND)")
    io.text("I2C プルアップはバスに 1 組。マスタ側に無い場合のみ R114/R115 を実装。", 18, 268, 1.3)
    io.text("J7 の 3V3 は電圧参照用。WCH-Link から 3.3V を供給しないこと (VDD33 ≤ VDD8 ≤ VHV の制約)。", 18, 274, 1.3)

    io.box(210, 130, 405, 248, "汎用 GPIO 引き出し (J6) / QII1 小信号入力 (タコ・VR センサ・電流リップル)")
    io.add("CONN8", "J6", "GPIO", 235, 150,
           nets={"1": "GND", "2": "+3V3", "3": "GPIO_PC4", "4": "GPIO_PC5", "5": "TACH_IN",
                 "6": "nFAULT_IN", "7": "+5V", "8": "GND"}, fp="HDR8", mpn="2.54mm 1x8 ピンヘッダ")
    res(io, "R120", "470R", 300, 170, "nFAULT_IN", "nFAULT")
    res(io, "R122", "10k", 360, 170, "+3V3", "nFAULT")
    res(io, "R123", "4.7k", 300, 185, "TACH_IN", "TACH_R")
    io.add("CONN3", "JP8", "QII_SRC", 345, 185, nets={"1": "TACH_R", "2": "QII_SRC", "3": "IBUS_F"}, fp="HDR3",
           mpn="2.54mm 3P + ジャンパ (1-2: TACH_IN / 2-3: バス電流リップル)")
    cap(io, "C105", C_100N, 385, 185, "QII_SRC", "QII_IN")
    for k, line in enumerate([
        "PC4: GPIO / TIM1_CH2_3 / SPI_MISO (USER/BOOT + 状態 LED 兼用, 例: DIR 入力)",
        "PC5: HV I/O (VHV 系, 入力耐圧 VHV+6V, 出力 ≈1mA) → 12V 系の EN / リミット入力に",
        "TACH_IN → R123 → JP8 1-2 → C105 → PA12: OPA1 (AV 20/40, 自己バイアス 1.23V) → CMP1 → TIM3 CH1",
        "  ファン FG, VR センサ, 小振幅パルスの周期計測。JP8 2-3 はバス電流の AC 成分 (ブラシ DC リップル計数)",
        "nFAULT (PA13 = TIM1_BKIN_1): Low で全ゲート OFF。10k プルアップ。3.3V 系 I/O は 5V 非耐性",
    ]):
        io.text(line, 213, 202 + k * 7, 1.3)
    return prj


PROJECTS.append(build_main())


# ===========================================================================
# 子基板 (パワー段)。裏面ソケットで主基板と背中合わせに接続
# ===========================================================================
DAUGHTERS = {
    "A": dict(fet="TPN1R603PL", sym="NMOS", fp="TSON", mpn="Toshiba TPN1R603PL,L1Q (30V 1.6mΩ Qg 41nC)",
              g="4", d="5", s="1", rg="47R", rpd="20k", shunt=("10mR 1% 2W", "R2512", "2512 2W (例: Bourns CRA2512-FZ-R010ELF)"),
              bulk=[("470uF/25V", "CP8", "低ESR 電解 8x11.5mm 470uF 25V")] * 2,
              bemf=("20k 1%", "3k 1%"), vin="8〜16V (公称 12V)", ipk="10A (ピンヘッダ律速)",
              title="子基板 A: TPN1R603PL (既存回路)"),
    "B": dict(fet="TKR74F04PB", sym="NMOS_TO263", fp="TO263", mpn="Toshiba TKR74F04PB,LQ (40V 0.74mΩ TO-220SM(W)) ※ランドは TO-263-2 で暫定",
              g="1", d="2", s="3", rg="22R", rpd="10k", shunt=("10mR 1% 3W", "R2512", "2512 3W (例: Bourns CRE2512-FZ-R010E-3)"),
              bulk=[("330uF/35V", "CP8", "低ESR 電解 8x11.5mm 330uF 35V")] * 2,
              bemf=("47k 1%", "3.3k 1%"), vin="12〜24V (最大 26V, 安定化電源)", ipk="10A (ピンヘッダ律速, 直付けで 20A 級)",
              title="子基板 B: TKR74F04PB (24V 系)"),
    "C": dict(fet="MTN2306AN3", sym="NMOS_SOT23", fp="SOT23", mpn="Cystech MTN2306AN3 (30V 5.5A 25mΩ SOT-23)",
              g="1", d="3", s="2", rg="47R", rpd="20k", shunt=("10mR 1% 0.5W", "R1206", "1206 0.5W (例: Yageo PE1206FRF7W0R01L)"),
              bulk=[("220uF/25V", "CP6", "低ESR 電解 6.3x11mm 220uF 25V")],
              bemf=("20k 1%", "3k 1%"), vin="8〜16V (公称 12V)", ipk="3A", title="子基板 C: MTN2306AN3 (廉価版)"),
}


def build_daughter(key):
    v = DAUGHTERS[key]
    name = f"mPBCH32M030DS0_PWR_{key}"
    prj = Project(name, f"daughter/PWR_{key}", f"mPBCH32M030DS0 Power daughter board {key} ({v['fet']})", [
        f"mPBCH32M030DS0 Rev 0.3 {v['title']}",
        "",
        f"・MOSFET: {v['fet']} x8 (4 ハーフブリッジ)   入力電圧: {v['vin']}   出力電流の目安: {v['ipk']}",
        "・主基板と裏面同士を向かい合わせ, J1 (電源 2x5) / J3 (信号 2x11) の裏面ピンソケットで接続 (基板間 約5mm)",
        "・TOP 面 (外側): MOSFET, シャント, ゲート確認 LED, 電流チャネル選択 JP5/JP7, モータ出力 J2/J4/J5/J6, バルク容量",
        "・BOTTOM 面 (主基板側): ピンソケットと高さ 2mm 以下の小型 CR のみ",
        "",
        "モータ出力 (各レッグ直近の 1x2 ピンヘッダ, 2 ピン並列): J2=OUT0 J4=OUT1 J5=OUT2 J6=OUT3",
        "  3相 = U/V/W (OUT0-2), DC x2 = OUT0-1 / OUT2-3, ステッピング = A+ A- B+ B-",
        "JP5 1-2: ISP2=HB1 / 2-3: HB2      JP7 1-2: ISP1=HB0 / 2-3: バス電流",
    ])
    br = prj.sheet("bridge", "パワー段 (4 ハーフブリッジ) / ゲート確認 LED / シャント / モータ出力")
    g, d, s = v["g"], v["d"], v["s"]
    for i in range(4):
        bx = 15 + i * 98
        cx, yH, yL = bx + 45.72, 50.8, 91.44
        xg, ys = cx - 8.89, (yH + yL) / 2
        br.box(bx, 20, bx + 94, 142, f"ハーフブリッジ HB{i}  (OUT{i})")
        rb = 30 + 10 * i
        br.add(v["sym"], f"Q{1 + 2 * i}", v["fet"], cx, yH, fp=v["fp"], mpn=v["mpn"],
               nets={g: f"GH{i}", d: "VBUS", s: f"SW{i}"}, wired=(g, d, s))
        br.label("VBUS", cx, yH - 5.08, 90)
        rgh = res(br, f"R{rb + 0}", v["rg"], cx - 17.78, yH, f"HO{i}", f"GH{i}", wired=("2",))
        br.wire(br.pin(rgh, "2"), (cx - 5.08, yH))
        res(br, f"R{rb + 1}", v["rpd"], xg, yH + 8.89, f"GH{i}", f"SW{i}", rot=0, wired=("1", "2"))
        br.wire((xg, yH), (xg, yH + 5.08))
        br.junction(xg, yH)
        br.label(f"GH{i}", xg, yH, 90)
        br.wire((xg, yH + 12.7), (xg, ys), (cx, ys))
        br.wire((cx, yH + 5.08), (cx, yL - 5.08))
        br.junction(cx, ys)
        br.wire((cx, ys), (cx + 10.16, ys))
        br.label(f"SW{i}", cx + 10.16, ys, 0)
        br.add(v["sym"], f"Q{2 + 2 * i}", v["fet"], cx, yL, fp=v["fp"], mpn=v["mpn"],
               nets={g: f"GL{i}", d: f"SW{i}", s: f"SRC{i}"}, wired=(g, d, s))
        rgl = res(br, f"R{rb + 2}", v["rg"], cx - 17.78, yL, f"LO{i}", f"GL{i}", wired=("2",))
        br.wire(br.pin(rgl, "2"), (cx - 5.08, yL))
        res(br, f"R{rb + 3}", v["rpd"], xg, yL + 8.89, f"GL{i}", f"SRC{i}", rot=0, wired=("1", "2"))
        br.wire((xg, yL), (xg, yL + 5.08))
        br.junction(xg, yL)
        br.label(f"GL{i}", xg, yL, 90)
        br.wire((xg, yL + 12.7), (cx, yL + 12.7))
        sv, sfp, smpn = v["shunt"]
        br.add("R", f"R{rb + 4}", sv, cx, yL + 22.86, fp=sfp, mpn=smpn,
               nets={"1": f"SRC{i}", "2": "ISH"}, wired=("1",))
        br.wire((cx, yL + 5.08), (cx, yL + 19.05))
        br.junction(cx, yL + 12.7)
        br.wire((cx, yL + 12.7), (cx + 10.16, yL + 12.7))
        br.label(f"SRC{i}", cx + 10.16, yL + 12.7, 0)
        cap(br, f"C{rb + 0}", C_100N, cx + 22.86, ys, "VBUS", f"SRC{i}", rot=0)
        cap(br, f"C{rb + 1}", C_10U50, cx + 35.56, ys, "VBUS", f"SRC{i}", rot=0)
        for k, (side, gn, sn, col) in enumerate(((f"H", f"GH{i}", f"SW{i}", "RED"),
                                                  ("L", f"GL{i}", f"SRC{i}", "GREEN"))):
            y = yL + 29 + k * 10
            r = res(br, f"R{rb + 5 + k}", "22k", cx + 18, y, gn, f"GLED{side}{i}", wired=("2",))
            br.add("LED", f"D{10 + 2 * i + k}", f"{col} G{side}{i}", cx + 30, y, rot=180, fp="LED1608",
                   nets={"2": f"GLED{side}{i}", "1": sn}, wired=("2",))
            br.wire(br.pin(r, "2"), (cx + 26.19, y))
    br.text(f"ゲート: {v['rg']} 直列 + {v['rpd']} G-S プルダウン。ゲート確認 LED は G-S 電圧で点灯 (H=赤, L=緑)。", 18, 138, 1.3)

    br.box(15, 150, 150, 285, "バスシャント / 電流チャネル選択 (TOP 面) / モータ出力")
    sv, sfp, smpn = v["shunt"]
    br.add("R", "R70", sv, 45, 170, rot=90, nets={"1": "ISH", "2": "GND"}, fp=sfp, mpn=smpn)
    br.add("CONN3", "JP5", "ISEL_B", 45, 195, nets={"1": "SRC1", "2": "ISB_SEL", "3": "SRC2"}, fp="HDR3",
           mpn="2.54mm 3P + ジャンパ (1-2: 3相 V / 2-3: HB2)")
    br.add("CONN3", "JP7", "ISEL_A", 45, 225, nets={"1": "SRC0", "2": "ISA_SEL", "3": "ISH"}, fp="HDR3",
           mpn="2.54mm 3P + ジャンパ (1-2: HB0 レッグ / 2-3: バス電流)")
    for k, ref in enumerate(("J2", "J4", "J5", "J6")):
        br.add("CONN2", ref, f"OUT{k}", 85 + 16 * k, 175, nets={"1": f"SW{k}", "2": f"SW{k}"}, fp="HDR2",
               mpn="2.54mm 1x2 ピンヘッダ (2 ピン並列, 各レッグ直近)")
    br.text("OUT0-3 (J2/J4/J5/J6): 3相=U/V/W | DC=OUT0-1 (+OUT2-3) | ステッピング=A+,A-,B+,B-", 20, 255, 1.4)
    br.text("JP5 1-2: ISP2=HB1(V相)  2-3: ISP2=HB2(コイルB / DC-B)", 20, 262, 1.4)
    br.text("JP7 1-2: ISP1=HB0 (差動)  2-3: ISP1=バス (ISH)", 20, 248, 1.4)
    br.text("R70 は全レッグ共通の帰路 (ISH→GND)。ISH/ISA_SEL/ISB_SEL はシャント端からケルビン配線で J3 へ。", 20, 269, 1.4)

    br.box(155, 150, 405, 200, "相電圧 (BEMF) 分圧 → 主基板 JP2-4 → PA5/PA6/PA7")
    r1, r2 = v["bemf"]
    for k, ph in enumerate("UVW"):
        xb = 185 + k * 75
        res(br, f"R{71 + 3 * k}", r1, xb, 165, f"SW{k}", f"BEMF_{ph}")
        res(br, f"R{72 + 3 * k}", r2, xb, 177, f"BEMF_{ph}", "GND")
        cap(br, f"C{71 + k}", C_1N, xb + 25, 171, f"BEMF_{ph}", "GND")
    br.text(f"分圧 {r2} / ({r1} + {r2})。入力電圧上限で ≤ 2.5V になるよう子基板ごとに定数を変える。", 160, 195, 1.3)

    br.box(155, 205, 405, 285, "基板間コネクタ (BOTTOM 面, 低背ピンソケット) / バルク容量 / 温度")
    br.add("CONN2x5", "J1", "B2B_PWR", 180, 222, nets=mated(B2B_PWR), fp="SOCK2x5",
           mpn="2.54mm 2x5 低背ピンソケット (裏面実装, 嵌合高さ ≈5mm)")
    br.add("CONN2x11", "J3", "B2B_SIG", 240, 222, nets=mated(B2B_SIG), fp="SOCK2x11",
           mpn="2.54mm 2x11 低背ピンソケット (裏面実装)")
    for k, (val, fp, mpn) in enumerate(v["bulk"]):
        br.add("CP", f"C{1 + k}", val, 300 + 20 * k, 225, nets={"1": "VBUS", "2": "GND"}, fp=fp, mpn=mpn)
    br.add("NTC", "TH1", "10k B3435", 350, 225, nets={"1": "NTC", "2": "GND"}, fp="R1005",
           mpn="NTC 10kΩ B3435 1005 (例: Murata NCP15XH103F03RC) — MOSFET 近傍")
    for k, ref in enumerate(("H1", "H2", "H3")):
        br.add("MH", ref, "M2", 300 + 15 * k, 248, nets={}, fp="MH", mpn="M2 取付穴 (主基板と共通位置)")
    br.text("J1/J3 は主基板 J9/J10 と同じピン番号で嵌合する (ソケットを 270° 回転して裏面実装, gen_pcb.py で座標検証)。", 158, 280, 1.2)
    return prj


def build_breakout():
    name = "mPBCH32M030DS0_PWR_D"
    prj = Project(name, "daughter/PWR_D", "mPBCH32M030DS0 daughter board D (no MOSFET, pin breakout)", [
        "mPBCH32M030DS0 Rev 0.3 子基板 D: MOSFET なし (ピン出し)",
        "",
        "・主基板の基板間コネクタ (J9/J10) の全信号を TOP 面のピンヘッダ J4 / J2 へそのまま引き出す",
        "・ユーザーが任意のパワー段 (外付け MOSFET, 既製ドライバ基板, 評価用抵抗負荷など) を配線して使う",
        "・J4 のピン番号・並びは主基板 J10 と同じ (シルクに信号名)。J2 は VBUS / GND (奇数 / 偶数)",
        "",
        "外付けパワー段の注意:",
        "  HOx/LOx はゲート直結 (CH32M030 内蔵プリドライバ 55mA/120mA)。ゲート抵抗・G-S プルダウンは外付け側で。",
        "  SWx はハイサイド MOSFET のソース (ブートストラップ帰路) へ最短で。BEMF_x は 2.5V 以下に分圧して入れる。",
        "  ISH / ISA_SEL / ISB_SEL はシャント両端からケルビン配線。NTC は 10kΩ B3435 を GND との間に。",
    ])
    br = prj.sheet("breakout", "ピン出し (MOSFET なし)")
    br.box(15, 20, 250, 150, "基板間コネクタ (BOTTOM 面ソケット) → TOP 面ピンヘッダ")
    br.add("CONN2x5", "J1", "B2B_PWR", 50, 45, nets=mated(B2B_PWR), fp="SOCK2x5",
           mpn="2.54mm 2x5 低背ピンソケット (裏面実装)")
    br.add("CONN2x11", "J3", "B2B_SIG", 50, 90, nets=mated(B2B_SIG), fp="SOCK2x11",
           mpn="2.54mm 2x11 低背ピンソケット (裏面実装)")
    br.add("CONN2x5", "J2", "PWR_OUT", 150, 45, nets=dict(B2B_PWR), fp="HDR2x5",
           mpn="2.54mm 2x5 ピンヘッダ (TOP 面, 奇数=VBUS / 偶数=GND)")
    br.add("CONN2x11", "J4", "GATE_SENSE", 150, 90, nets=dict(B2B_SIG), fp="HDR2x11",
           mpn="2.54mm 2x11 ピンヘッダ (TOP 面, 主基板 J10 と同じ並び)")
    br.add("CP", "C1", "220uF/25V", 210, 45, nets={"1": "VBUS", "2": "GND"}, fp="CP6", dnp=True,
           mpn="任意: 外付けパワー段が遠い場合のバルク容量")
    for k, ref in enumerate(("H1", "H2", "H3")):
        br.add("MH", ref, "M2", 40 + 20 * k, 140, nets={}, fp="MH", mpn="M2 取付穴 (主基板と共通位置)")
    return prj


for _k in DAUGHTERS:
    PROJECTS.append(build_daughter(_k))
PROJECTS.append(build_breakout())


# ---------------------------------------------------------------------------
# 出力
# ---------------------------------------------------------------------------
def fmt(v):
    return f"{round(v, 4):g}"


def title_block(sub):
    return (f'(title_block (title "{CUR.title}") (date "{DATE}") (rev "{REV}") '
            f'(company "ghostinkoma") (comment 1 "{sub}") '
            f'(comment 2 "個人利用可 (クレジット表示必須) / 商用利用は要連絡 / 無保証  -  LICENSE 参照"))')


def sheet_sexpr(sh, sheet_uuid):
    used = {p["sym"] for p in sh.parts}
    o = [f'(kicad_sch (version 20230121) (generator eeschema)',
         f'(uuid {U(CUR.name + ":file:" + sh.key)})', '(paper "A3")', title_block(sh.title),
         lib_symbols_sexpr(used)]
    c = 0

    def nid():
        nonlocal c
        c += 1
        return U(f"{CUR.name}:{sh.key}:{c}")

    for (x0, y0, x1, y1, t) in sh.boxes:
        o.append(f'(rectangle (start {fmt(x0)} {fmt(y0)}) (end {fmt(x1)} {fmt(y1)}) '
                 f'(stroke (width 0.2) (type dash)) (fill (type none)) (uuid {nid()}))')
        o.append(f'(text "{t}" (at {fmt(x0 + 2)} {fmt(y0 + 5)} 0) (effects (font (size 2 2) (thickness 0.3) bold) '
                 f'(justify left bottom)) (uuid {nid()}))')
    for (s, x, y, size) in sh.texts:
        o.append(f'(text "{s}" (at {fmt(x)} {fmt(y)} 0) (effects (font (size {size} {size})) '
                 f'(justify left bottom)) (uuid {nid()}))')

    for p in sh.parts:
        s = SYMS[p["sym"]]
        x, y, rot = p["x"], p["y"], p["rot"]
        rx, ry = xform(x, y, rot, *s["ref_at"])
        vx, vy = xform(x, y, rot, *s["val_at"])
        fang = 0
        if p["sym"] in ("R", "C", "CP", "FUSE", "NTC") and rot in (90, 270):
            rx, ry, vx, vy = x, y - 2.8, x, y + 3.6
            fang = 90
        if p["sym"] in ("D_TVS", "D_ZENER", "LED", "D_SCH") and rot in (90, 270):
            rx, ry, vx, vy = x + 2.5, y - 1, x + 2.5, y + 1.5
            fang = (360 - rot) % 360  # KiCad はフィールド角度にシンボル回転を加算して表示する
        if p["sym"] in ("D_TVS", "D_ZENER", "LED", "D_SCH") and rot in (0, 180):
            rx, ry, vx, vy = x, y - 3, x, y + 4
        just = "" if p["sym"] in ("R", "C", "CP", "FUSE", "NTC", "D_TVS", "D_ZENER", "LED") and (
            rot in (90, 270) and p["sym"] in ("R", "C", "CP", "FUSE", "NTC") or rot in (0, 180) and
            p["sym"] in ("D_TVS", "D_ZENER", "LED", "D_SCH")) else " (justify left)"
        su = nid()
        o.append(f'(symbol (lib_id "mdrv:{p["sym"]}") (at {fmt(x)} {fmt(y)} {rot}) (unit 1) '
                 f'(in_bom yes) (on_board yes) (dnp {"yes" if p["dnp"] else "no"}) (uuid {su})')
        o.append(f'(property "Reference" "{p["ref"]}" (at {fmt(rx)} {fmt(ry)} {fang}) '
                 f'(effects (font (size 1.27 1.27)){just}))')
        val = p["value"] + (" (DNP)" if p["dnp"] else "")
        o.append(f'(property "Value" "{val}" (at {fmt(vx)} {fmt(vy)} {fang}) '
                 f'(effects (font (size 1.27 1.27)){just}))')
        o.append(f'(property "Footprint" "{p["fp"]}" (at {fmt(x)} {fmt(y)} 0) '
                 f'(effects (font (size 1.27 1.27)) hide))')
        o.append(f'(property "Datasheet" "~" (at {fmt(x)} {fmt(y)} 0) (effects (font (size 1.27 1.27)) hide))')
        o.append(f'(property "MPN" "{p["mpn"]}" (at {fmt(x)} {fmt(y)} 0) (effects (font (size 1.27 1.27)) hide))')
        for pin in s["pins"]:
            o.append(f'(pin "{pin[0]}" (uuid {nid()}))')
        o.append(f'(instances (project "{CUR.name}" (path "/{CUR.root}/{sheet_uuid}" '
                 f'(reference "{p["ref"]}") (unit 1))))')
        o.append(")")
        # ピン -> スタブ -> ラベル
        for num, nm, lx, ly, a, ln, hid in s["pins"]:
            if hid or num in p["wired"]:
                continue
            net = p["nets"][num]
            px, py = xform(x, y, rot, lx, ly)
            ox, oy = OUTWARD[a]
            ex, ey = xform(x, y, rot, lx + ox * 2.54, ly + oy * 2.54)
            if net is None:
                o.append(f'(no_connect (at {fmt(px)} {fmt(py)}) (uuid {nid()}))')
                continue
            o.append(f'(wire (pts (xy {fmt(px)} {fmt(py)}) (xy {fmt(ex)} {fmt(ey)})) '
                     f'(stroke (width 0) (type default)) (uuid {nid()}))')
            dx, dy = round(ex - px, 3), round(ey - py, 3)
            ang = 0 if dx > 0 else 180 if dx < 0 else 90 if dy < 0 else 270
            o.append(label_sexpr(net, ex, ey, ang, nid()))
    for (a, b) in split_wires(sh.wires, sh.junctions):
        o.append(f'(wire (pts (xy {fmt(a[0])} {fmt(a[1])}) (xy {fmt(b[0])} {fmt(b[1])})) '
                 f'(stroke (width 0) (type default)) (uuid {nid()}))')
    for (x, y) in sh.junctions:
        o.append(f'(junction (at {fmt(x)} {fmt(y)}) (diameter 0) (color 0 0 0 0) (uuid {nid()}))')
    for (net, x, y, ang) in sh.labels:
        o.append(label_sexpr(net, x, y, ang, nid()))
    o.append(")")
    return "\n".join(o)


def split_wires(wires, junctions):
    """T 分岐点 (他ワイヤの端点/ジャンクション) でワイヤを分割する。
    KiCad は端点同士でしか接続を認識しないため。"""
    key = lambda pt: (round(pt[0], 4), round(pt[1], 4))
    pts = {key(p) for w in wires for p in w} | {key(j) for j in junctions}
    out = []
    for a, b in wires:
        a, b = key(a), key(b)
        inner = [p for p in pts if p not in (a, b) and
                 min(a[0], b[0]) <= p[0] <= max(a[0], b[0]) and
                 min(a[1], b[1]) <= p[1] <= max(a[1], b[1]) and
                 abs((b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])) < 1e-6]
        inner.sort(key=lambda p: (p[0] - a[0]) ** 2 + (p[1] - a[1]) ** 2)
        chain = [a] + inner + [b]
        out += list(zip(chain, chain[1:]))
    return out


def label_sexpr(net, ex, ey, ang, lid):
    """複数シートで使うネットはグローバルラベル, それ以外はローカルラベル."""
    if net in CUR.GLOBAL:
        j = "left" if ang in (0, 90) else "right"
        return (f'(global_label "{net}" (shape passive) (at {fmt(ex)} {fmt(ey)} {ang}) '
                f'(fields_autoplaced) (effects (font (size 1.27 1.27)) (justify {j})) (uuid {lid}) '
                f'(property "Intersheetrefs" "${{INTERSHEET_REFS}}" (at {fmt(ex)} {fmt(ey)} 0) '
                f'(effects (font (size 1.27 1.27)) hide)))')
    j = "left bottom" if ang in (0, 90) else "right bottom"
    return (f'(label "{net}" (at {fmt(ex)} {fmt(ey)} {ang}) (fields_autoplaced) '
            f'(effects (font (size 1.27 1.27)) (justify {j})) (uuid {lid}))')


def root_sexpr(sheet_uuids):
    o = ['(kicad_sch (version 20230121) (generator eeschema)', f'(uuid {CUR.root})', '(paper "A3")',
         title_block("トップシート / 仕様概要"), "(lib_symbols)"]
    for k, t in enumerate(CUR.notes):
        o.append(f'(text "{t}" (at 20 {fmt(30 + k * 7)} 0) (effects (font (size 2 2)) (justify left bottom)) '
                 f'(uuid {U(CUR.name + ":roottext:" + str(k))}))')
    for k, sh in enumerate(CUR.sheets):
        x, y = 20 + k * 78, 200
        su = sheet_uuids[sh.key]
        o.append(f'(sheet (at {x} {y}) (size 70 30) (fields_autoplaced) (stroke (width 0.1524) (type solid)) '
                 f'(fill (color 0 0 0 0.0000)) (uuid {su})')
        o.append(f'(property "Sheetname" "{sh.title}" (at {x} {fmt(y - 0.7)} 0) '
                 f'(effects (font (size 1.5 1.5)) (justify left bottom)))')
        o.append(f'(property "Sheetfile" "{sh.key}.kicad_sch" (at {x} {fmt(y + 30.6)} 0) '
                 f'(effects (font (size 1.27 1.27)) (justify left top)))')
        o.append(f'(instances (project "{CUR.name}" (path "/{CUR.root}" (page "{sh.page}"))))')
        o.append(")")
    o.append('(sheet_instances (path "/" (page "1")))')
    o.append(")")
    return "\n".join(o)


def refkey(r):
    a = r.rstrip("0123456789")
    return a, int(r[len(a):] or 0)


def emit(prj):
    global CUR
    CUR = prj
    d = os.path.join(OUT, prj.subdir)
    os.makedirs(d, exist_ok=True)
    prj.root = U(prj.name + ":root")
    net_sheets = {}
    for sh in prj.sheets:
        for p in sh.parts:
            for n in p["nets"].values():
                if n:
                    net_sheets.setdefault(n, set()).add(sh.key)
    prj.GLOBAL = {n for n, s in net_sheets.items() if len(s) > 1}
    refs = [p["ref"] for sh in prj.sheets for p in sh.parts]
    dup = {r for r in refs if refs.count(r) > 1}
    assert not dup, f"{prj.name}: duplicate refs: {dup}"
    sheet_uuids = {sh.key: U(prj.name + ":sheet:" + sh.key) for sh in prj.sheets}
    for sh in prj.sheets:
        with open(os.path.join(d, f"{sh.key}.kicad_sch"), "w", encoding="utf-8") as f:
            f.write(sheet_sexpr(sh, sheet_uuids[sh.key]))
    with open(os.path.join(d, f"{prj.name}.kicad_sch"), "w", encoding="utf-8") as f:
        f.write(root_sexpr(sheet_uuids))
    rel = os.path.relpath(OUT, d).replace(os.sep, "/")
    libdir = "${KIPRJMOD}" if rel == "." else "${KIPRJMOD}/" + rel
    with open(os.path.join(d, "sym-lib-table"), "w", encoding="utf-8") as f:
        f.write('(sym_lib_table\n  (version 7)\n  (lib (name "mdrv")(type "KiCad")'
                f'(uri "{libdir}/lib/mdrv.kicad_sym")(options "")(descr "mPBCH32M030DS0 symbols"))\n)\n')
    with open(os.path.join(d, "fp-lib-table"), "w", encoding="utf-8") as f:
        f.write('(fp_lib_table\n  (version 7)\n'
                f'  (lib (name "CH32M030DS0_QFN48")(type "KiCad")(uri "{libdir}/lib/CH32M030DS0_QFN48.pretty")(options "")(descr "CH32M030 QFN48"))\n'
                f'  (lib (name "mPB")(type "KiCad")(uri "{libdir}/lib/mPB.pretty")(options "")(descr "mPBCH32M030DS0 footprints"))\n)\n')
    pro = os.path.join(d, f"{prj.name}.kicad_pro")
    if not os.path.exists(pro):
        with open(pro, "w", encoding="utf-8") as f:
            f.write('{\n  "meta": {"filename": "%s.kicad_pro", "version": 1}\n}\n' % prj.name)
    groups = {}
    for sh in prj.sheets:
        for p in sh.parts:
            k = (p["value"], p["fp"], p["mpn"], p["dnp"])
            groups.setdefault(k, []).append(p["ref"])
    rows = sorted(groups.items(), key=lambda kv: refkey(sorted(kv[1], key=refkey)[0]))
    with open(os.path.join(d, "bom.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Qty", "References", "Value", "Footprint", "MPN / 備考", "DNP"])
        for (val, fp, mpn, dnp), rs in rows:
            rs = sorted(rs, key=refkey)
            w.writerow([len(rs), " ".join(rs), val, fp, mpn, "DNP" if dnp else ""])
    nets = {}
    for sh in prj.sheets:
        for p in sh.parts:
            s = SYMS[p["sym"]]
            for num, *_ in s["pins"]:
                n = p["nets"].get(num)
                if n is None and num in p["nets"]:
                    continue
                if n is None:  # 隠しスタックピン: 同名の可視ピンと同じネット
                    vis = next(q for q in s["pins"] if q[1] == next(r for r in s["pins"] if r[0] == num)[1]
                               and not q[6])
                    n = p["nets"][vis[0]]
                nets.setdefault(n, []).append(f"{p['ref']}.{num}")
    with open(os.path.join(d, "expected_nets.txt"), "w", encoding="utf-8") as f:
        for n in sorted(nets):
            f.write(f"{n}: {' '.join(sorted(nets[n]))}\n")
    # 部品表 (PCB 生成用): ref, footprint, value, pad -> net
    import json
    parts = [dict(ref=p["ref"], fp=p["fp"], value=p["value"], dnp=p["dnp"], nets={
        num: (p["nets"].get(num) if num in p["nets"] else None) for num, *_ in SYMS[p["sym"]]["pins"]})
        for sh in prj.sheets for p in sh.parts]
    for q in parts:  # 隠しピンは同名ピンのネット
        sp = next(p for sh in prj.sheets for p in sh.parts if p["ref"] == q["ref"])
        s = SYMS[sp["sym"]]
        for num, nm, *_rest in s["pins"]:
            if num not in sp["nets"]:
                vis = next(x for x in s["pins"] if x[1] == nm and not x[6])
                q["nets"][num] = sp["nets"][vis[0]]
    with open(os.path.join(d, "parts.json"), "w", encoding="utf-8") as f:
        json.dump(dict(name=prj.name, parts=parts), f, ensure_ascii=False, indent=1)
    print(f"{prj.name}: sheets={len(prj.sheets)} parts={len(refs)} nets={len(nets)} global={len(prj.GLOBAL)}")


def main():
    for prj in PROJECTS:
        emit(prj)
    lib = lib_symbols_sexpr(set(SYMS)).replace('(symbol "mdrv:', '(symbol "')
    lib = lib.replace("(lib_symbols", '(kicad_symbol_lib (version 20220914) (generator gen_schematic)', 1)
    with open(os.path.join(OUT, "lib", "mdrv.kicad_sym"), "w", encoding="utf-8") as f:
        f.write(lib + "\n")


if __name__ == "__main__":
    main()
