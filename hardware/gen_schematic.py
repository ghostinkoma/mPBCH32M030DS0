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
REV = "0.4"
DATE = "2026-09-26"
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
# 3 端子はんだジャンパ (1-2 が出荷時ブリッジ, 2 が共通)
defsym("SJ3", "JP", [("1", "~", -5.08, 0, 0, 2.54, False), ("2", "~", 0, -3.81, 90, 2.54, False),
                     ("3", "~", 5.08, 0, 180, 2.54, False)],
       [_rect(-2.286, -1.016, -1.27, 1.016, fill="outline"), _rect(-0.508, -1.016, 0.508, 1.016, fill="outline"),
        _rect(1.27, -1.016, 2.286, 1.016, fill="outline"), _pl([(-1.27, 0), (-0.508, 0)], 0.508)],
       ref_at=(0, 2.54), val_at=(0, 4.2))
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


for _n in (2, 3, 4, 5, 8, 21):
    conn_sym(_n)


def conn2_sym(rows, prefix="J"):
    """2 列ピンヘッダ (KiCad 2xNN と同じ番号: 奇数=左列, 偶数=右列)."""
    pins = []
    for r in range(rows):
        pins.append((str(2 * r + 1), f"P{2 * r + 1}", -7.62, -2.54 * r, 0, 3.81, False))
        pins.append((str(2 * r + 2), f"P{2 * r + 2}", 7.62, -2.54 * r, 180, 3.81, False))
    gfx = [_rect(-3.81, 1.27, 3.81, -2.54 * (rows - 1) - 1.27, fill="background")]
    defsym(f"CONN2x{rows}", prefix, pins, gfx, show_pin_numbers=True, ref_at=(0, 3.81), val_at=(0, 6.35))


for _n in (4, 5, 6, 8, 11):
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
    "HDR1x21": "Connector_PinHeader_2.54mm:PinHeader_1x21_P2.54mm_Vertical",
    "SOCK1x21": "Connector_PinSocket_2.54mm:PinSocket_1x21_P2.54mm_Vertical",
    "HDR2x6": "Connector_PinHeader_2.54mm:PinHeader_2x06_P2.54mm_Vertical",
    "HDR2x8": "Connector_PinHeader_2.54mm:PinHeader_2x08_P2.54mm_Vertical",
    "SJ3": "Jumper:SolderJumper-3_P1.3mm_Bridged12_RoundedPad1.0x1.5mm_NumberLabels",
    "LED1005": "LED_SMD:LED_0402_1005Metric",
    "C1206": "Capacitor_SMD:C_1206_3216Metric",
    "CPE8x6": "Capacitor_SMD:CP_Elec_8x6.2",
    "CPE6x6": "Capacitor_SMD:CP_Elec_6.3x5.9",
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
# 部品定数 (コンデンサは耐圧・DC バイアス・入手性から現実的なサイズを選ぶ)
#   1005: 0.1uF/50V, 1uF/25V, 10nF・1nF (X7R), 30pF・1nF・2.2nF (C0G) — いずれも大量流通品
#   1608: 1uF/50V, 2.2uF/25V, 4.7uF/16V, 4.7nF/100V
#   2012: 10uF/25V (VDD8 10V 時の実効容量確保)   1206: 10uF/50V (VHV・VBUS)
# ---------------------------------------------------------------------------
C_100N = ("0.1uF/50V", "C1005", "Murata GRM155R71H104KE14D (X7R 1005)")
C_1U25 = ("1uF/25V", "C1005", "Murata GRM155R61E105KA12D (X5R 1005)")
C_1U50 = ("1uF/50V", "C1608", "Murata GRM188R61H105KAALD (X5R 1608)")
C_2U2 = ("2.2uF/25V", "C1608", "Murata GRM188R61E225KA12D (X5R 1608)")
C_4U7 = ("4.7uF/16V", "C1608", "Samsung CL10A475KO8NNNC (X5R 1608)")
C_10U25 = ("10uF/25V", "C2012", "Murata GRM21BR61E106KA73L (X5R 2012)")
C_10U50 = ("10uF/50V", "C1206", "Murata GRM31CR61H106KA12L (X5R 1206)")
C_10N = ("10nF/50V", "C1005", "Murata GRM155R71H103KA88D (X7R 1005)")
C_1N = ("1nF/50V", "C1005", "Murata GRM155R71H102KA01D (X7R 1005)")
C_1N_C0G = ("1nF C0G", "C1005", "Murata GRM1555C1H102JA01D (C0G 1005)")
C_2N2_C0G = ("2.2nF C0G", "C1005", "Murata GRM1555C1H222JA01D (C0G 1005)")
C_30P = ("30pF C0G", "C1005", "Murata GRM1555C1H300JA01D (C0G 1005)")
C_4N7_100 = ("4.7nF/100V", "C1608", "Samsung CL10B472KC8NNNC (X7R 100V 1608)")


def cap(sh, ref, spec, x, y, n1, n2, rot=90, **kw):
    val, fp, mpn = spec
    return sh.add("C", ref, val, x, y, rot=rot, nets={"1": n1, "2": n2}, fp=fp, mpn=mpn, **kw)


def res(sh, ref, val, x, y, n1, n2, rot=90, fp="R1005", **kw):
    return sh.add("R", ref, val, x, y, rot=rot, nets={"1": n1, "2": n2}, fp=fp, **kw)


# ---------------------------------------------------------------------------
# モジュールの端子 (DIP 型: 2.54mm ピッチ 21 ピン x 2 列, 列間 15.24mm = 0.6")
#   ブレッドボードに直接挿せる / パワー段子基板のピンソケット (左右対称) に挿せる。
#   左列 J1 = 電源・アナログ・センサ, 右列 J2 = ゲート駆動・通信。子基板は同じ番号で受ける。
# ---------------------------------------------------------------------------
# 並びは QFN の各辺のピン順に合わせ, 引き出し配線が交差しないようにした (上辺の右側 → J2 上部,
# 上辺の左側 → J1 上部, 右辺のゲート → J2 中央, 下辺の右寄り → J2 下部, 左辺のアナログ → J1 下部)。
EDGE_L = ["USB_VBUS", "USB_VBUS", "PD_PWR_EN", "GPIO_PC4", "GPIO_PC5", "+3V3", "+5V", "SWDIO", "VBUS",
          "NTC", "BEMF_U", "BEMF_V", "BEMF_W", "HALL_A_IN", "HALL_B_IN", "HALL_C_IN",
          "ISA_SEL", "ISH", "ISB_SEL", "TACH_IN", "GND"]
EDGE_R = ["GND", "UART_RX", "UART_TX", "nRST",
          "HO3", "SW3", "LO3", "HO2", "SW2", "LO2", "HO1", "SW1", "LO1", "HO0", "SW0", "LO0",
          "VBUS_SNS", "I2C_SCL", "I2C_SDA", "nFAULT_IN", "GND"]
assert len(EDGE_L) == 21 and len(EDGE_R) == 21
PINMAP_L = {str(i + 1): n for i, n in enumerate(EDGE_L)}
PINMAP_R = {str(i + 1): n for i, n in enumerate(EDGE_R)}


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
# MCU モジュール (ブレッドボード対応 DIP 型 20.32 x 53.34mm)
# ===========================================================================
def build_main():
    prj = Project("mPBCH32M030DS0", ".", "mPBCH32M030DS0  CH32M030 motor-driver MCU module (DIP-42)", [
        "mPBCH32M030DS0 Rev 0.4 MCU モジュール — CH32M030C8U7 (QFN48), ブレッドボード対応 DIP-42 (列間 0.6in)",
        "",
        "・2 層 20.32 x 53.34mm (2.54mm 格子で 8 x 21 マス)。左右 21 ピン x 2 列, 列間 15.24mm",
        "  ピンヘッダは裏から (ブレッドボード / 子基板用) でも表から (ジャンパワイヤ用) でも実装できる",
        "・左列 J1: USB VBUS / 電源 / SDI / センサ (相電圧・ホール・電流・NTC)。右列 J2: ゲート駆動 x12 / UART / I2C / GPIO",
        "・LED はすべてモジュール上 (子基板の部品面はヒートシンク側のため): 電源 x3, 状態, ゲート確認 x8",
        "・パワー段子基板 (A: TPN1R603PL / B: TKR74F04PB 24V / C: MTN2306AN3) は左右対称のピンソケットで受ける",
        "・電圧に依存する部品 (TVS, VBUS 分圧, バルク容量) は子基板側。モジュールは電圧に依存しない",
        "",
        "詳細は README.md, docs/stacking.md, docs/design.md を参照。",
    ])

    # ===== 1. 電源・表示 =====
    pw = prj.sheet("power", "MCU 電源 (VHV) / 電源表示 LED / USB VBUS 監視")
    pw.box(20, 25, 200, 110, "MCU 電源 VHV (VBUS ピン / USB 5V のダイオード OR + 27V クランプ)")
    pw.add("D_SCH", "D5", "B5819W", 50, 50, rot=180, nets={"1": "VHV_IN", "2": "VBUS"}, fp="SOD123",
           mpn="B5819W (40V 1A ショットキー)")
    pw.add("D_SCH", "D6", "B5819W", 50, 65, rot=180, nets={"1": "VHV_IN", "2": "USB_VBUS_F"}, fp="SOD123",
           mpn="B5819W (40V 1A ショットキー)")
    res(pw, "R10", "47R", 90, 55, "VHV_IN", "VHV", fp="R1608")
    pw.add("D_ZENER", "D4", "MMSZ5254B 27V", 125, 60, rot=90, nets={"1": "VHV", "2": "GND"}, fp="SOD123",
           mpn="MMSZ5254B (27V 500mW, VHV 絶対最大 30V の保護)")
    pw.text("VBUS ピン (子基板のモータ電源) か USB 5V のどちらかで MCU が動く。ブレッドボード単体は USB 給電のみで可。", 23, 95, 1.3)
    pw.text("R10 47Ω + D4 27V: 24V 系のサージで VHV が 30V を超えないようにする。", 23, 101, 1.3)

    pw.box(210, 25, 405, 110, "電源表示 LED (モジュール上面: 子基板を付けても見える)")
    for x, ref_r, val_r, ref_d, val_d, net in ((240, "R4", "15k", "D7", "RED VBUS", "VBUS"),
                                                (290, "R3", "2.2k", "D2", "GREEN 5V", "+5V"),
                                                (340, "R5", "1.5k", "D8", "GREEN 3V3", "+3V3")):
        res(pw, ref_r, val_r, x, 50, net, f"LED_{ref_d}_A")
        pw.add("LED", ref_d, val_d, x, 70, rot=90, nets={"2": f"LED_{ref_d}_A", "1": "GND"}, fp="LED1608",
               mpn="1608 チップ LED")
    pw.text("D7: モータ電源 VBUS  D2: +5V (子基板の 78L05)  D8: VDD33 (1.5k で約 0.9mA, VDD33 負荷 ≤20mA)", 213, 100, 1.3)

    pw.box(20, 120, 200, 200, "USB VBUS 監視 (PA2)")
    res(pw, "R7", "120k 1%", 60, 145, "USB_VBUS", "USB_VBUS_SNS")
    res(pw, "R8", "10k 1%", 60, 170, "USB_VBUS_SNS", "GND")
    cap(pw, "C7", C_10N, 90, 170, "USB_VBUS_SNS", "GND")
    pw.text("USB_VBUS / 13 → PA2 (20V → 1.54V)。PD 契約後の電圧確認に使う。", 23, 192, 1.3)

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
    us.text("CC1/CC2 = PA0/PA1 (Rd 5.1kΩ 内蔵)。D+/D- = PB0/PB1。USB_VBUS はモジュール端子 J1 の 1/2 番 (子基板の PD 給電経路) へ。", 23, 140, 1.3)
    us.text("注意: PD 契約後は USB_VBUS が 9〜15V になる。ブレッドボードでは USB_VBUS ピンに 5V 部品を直結しないこと。", 23, 145, 1.3)

    us.box(260, 25, 405, 100, "水晶発振子 (HSE 8MHz)")
    us.add("XTAL4", "Y1", "8MHz CL=20pF", 330, 55, nets={"1": "XI", "3": "XO", "2": "GND"}, fp="XTAL3225",
           mpn="8MHz 3225 4pad, CL=20pF, ESR≤60Ω (例: Abracon ABM8-8.000MHZ-B2-T)")
    cap(us, "C131", C_30P, 300, 72, "XI", "GND", rot=0)
    cap(us, "C132", C_30P, 360, 72, "XO", "GND", rot=0)
    us.text("XI=PB5 / XO=PB6。C = 2 x (CL - 浮遊容量 約5pF) = 30pF。", 263, 92, 1.3)

    us.box(260, 110, 405, 190, "リセット (RST = PC0)  ※ 上面")
    us.add("SW", "SW1", "RESET", 340, 140, nets={"1": "nRST", "2": "GND"}, fp="SW",
           mpn="Omron B3U-1000P (3x2.5mm SMD タクト, 上押し)")
    res(us, "R131", "10k", 290, 130, "+3V3", "nRST")
    cap(us, "C133", C_100N, 290, 150, "nRST", "GND")
    us.text("RST ピンはユーザオプションバイトで有効化 (RST_PIN_SEL=0 → PC0)。", 263, 180, 1.3)

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
    mc.box(15, 20, 130, 95, "電源デカップリング (ピン直近)")
    for j, (ref, spec, n1) in enumerate([
        ("C10", C_10U50, "VHV"), ("C11", C_100N, "VHV"),
        ("C12", C_10U25, "VDD8"), ("C13", C_100N, "VDD8"),
        ("C14", C_4U7, "+3V3"), ("C15", C_100N, "+3V3"),
    ]):
        cap(mc, ref, spec, 45 + (j % 2) * 45, 35 + (j // 2) * 16, n1, "GND")
    mc.text("VHV 5〜28V (≥10uF, 1206/50V)。VDD8 5/8/9/10V (≥10uF, 2012/25V)。VDD33 4.7uF (1608/16V)。", 18, 85, 1.3)
    mc.text("LDO 負荷上限: VDD8 35mA (ゲート駆動+VDD33 含む) / VDD33 20mA。QFN 裏面パッドが唯一の GND。", 18, 90, 1.3)

    mc.box(15, 100, 130, 205, "バス電流フィルタ / 過電流比較の閾値")
    for j, (ref, sym, val, n1, n2) in enumerate([
        ("R13", "R", "1k", "ISH", "IBUS_F"),
        ("C17", "C", C_1N_C0G, "IBUS_F", "GND"),
        ("R14", "R", "12k 1%", "+3V3", "OCP_REF"),
        ("R15", "R", "1k 1%", "OCP_REF", "GND"),
        ("C18", "C", C_100N, "OCP_REF", "GND"),
        ("C16", "C", C_10N, "VBUS_SNS", "GND"),
    ]):
        x, y = 45 + (j % 2) * 45, 115 + (j // 2) * 16
        if sym == "C":
            cap(mc, ref, val, x, y, n1, n2)
        else:
            res(mc, ref, val, x, y, n1, n2)
    mc.text("VBUS_SNS (PB4 = ADC17 + OVP リセット) の分圧抵抗は子基板側 (電圧系ごとに定数が違う)。C16 は MCU 直近の平滑。", 18, 182, 1.25)
    mc.text("PB3: バス電流 (10mΩ: 1A = 10mV) + CMP3_P3。PB2: 閾値 254mV (25.4A) = CMP3_N3。", 18, 188, 1.25)

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
    mc.text("OPA3 出力 → ADC_IN9, OPA4 出力 → ADC_IN10 (チップ内部接続)。ゲイン 4/8/16/55。", 283, 95, 1.25)

    mc.box(280, 115, 405, 205, "ブートストラップ容量 (VBx-VSx, MCU ピン直近)")
    for i in range(4):
        cap(mc, f"C{21 + i}", C_2U2, 310 + (i % 2) * 55, 130 + (i // 2) * 18, f"VB{i}", f"SW{i}")
    mc.text("2.2uF 1608 (DC バイアス後 ≈1.3uF): Qg 41nC で降下 32mV, Qg ≈150nC でも ≈0.12V。", 283, 180, 1.25)

    # ===== 4. 端子 / ゲート確認 LED / センシング選択 / I/O =====
    io = prj.sheet("io", "DIP 端子 J1/J2 / ゲート確認 LED / センシング選択 / I/O")
    io.box(15, 20, 150, 285, "DIP 端子 (2.54mm, 21 ピン x 2 列, 列間 15.24mm)")
    io.add("CONN21", "J1", "EDGE_L", 45, 40, nets=PINMAP_L, fp="HDR1x21",
           mpn="2.54mm 1x21 ピンヘッダ (裏 or 表から実装)")
    io.add("CONN21", "J2", "EDGE_R", 110, 40, nets=PINMAP_R, fp="HDR1x21",
           mpn="2.54mm 1x21 ピンヘッダ (裏 or 表から実装)")
    io.text("子基板は同じピン番号のソケット (左右対称) で受ける。", 18, 280, 1.3)

    io.box(160, 20, 405, 110, "ゲート確認 LED (モジュール上面に 8 個: 子基板の部品面はヒートシンク側で見えないため)")
    for i in range(4):
        for k, (side, a, kk, col) in enumerate((("H", f"HO{i}", f"SW{i}", "RED"), ("L", f"LO{i}", "GND", "GREEN"))):
            x = 180 + i * 55 + k * 25
            res(io, f"R{50 + 2 * i + k}", "22k", x, 45, a, f"GLED{side}{i}")
            io.add("LED", f"D{10 + 2 * i + k}", f"{col} G{side}{i}", x, 70, rot=90,
                   nets={"2": f"GLED{side}{i}", "1": kk}, fp="LED1005", mpn="1005 チップ LED (例: Kingbright APHHS1005)")
    io.text("H: HOx-SWx (ハイサイドのゲート電圧), L: LOx-GND。約 0.35mA @ VDD8=10V。PWM のデューティで明るさが変わる。", 163, 100, 1.3)

    io.box(160, 120, 405, 190, "3 相センシング選択 (はんだジャンパ, 出荷時 1-2 = 相電圧) / QII 入力選択")
    for k, ph in enumerate("UVW"):
        io.add("SJ3", f"JP{2 + k}", f"SEL_{ph}", 190 + k * 45, 145,
               nets={"1": f"BEMF_{ph}", "2": f"SENS_{ph}", "3": f"HALL_{'ABC'[k]}"}, fp="SJ3",
               mpn="はんだジャンパ 3 端子 (1-2 ブリッジ済み: 相電圧 / 2-3: ホール)")
    io.add("SJ3", "JP8", "QII_SRC", 340, 145, nets={"1": "TACH_R", "2": "QII_SRC", "3": "IBUS_F"}, fp="SJ3",
           mpn="はんだジャンパ 3 端子 (1-2 ブリッジ済み: TACH_IN / 2-3: バス電流リップル)")
    res(io, "R123", "4.7k", 330, 170, "TACH_IN", "TACH_R", rot=0)
    cap(io, "C105", C_100N, 375, 170, "QII_SRC", "QII_IN", rot=0)
    io.text("子基板を付けずブレッドボードで使うときも同じ: BEMF_x / HALL_x_IN ピンに信号を入れる。", 163, 185, 1.3)

    io.box(160, 195, 405, 285, "ホール入力 / USER・BOOT + 状態 LED / I2C / nFAULT / NTC")
    for k, h in enumerate("ABC"):
        yb = 215 + k * 22
        res(io, f"R{100 + 3 * k}", "4.7k", 180, yb, f"HALL_{h}_IN", "+3V3", rot=0)
        res(io, f"R{101 + 3 * k}", "1k", 210, yb, f"HALL_{h}_IN", f"HALL_{h}", rot=0)
        cap(io, f"C{100 + k}", C_1N, 240, yb, f"HALL_{h}", "GND")
    io.add("SW", "SW2", "USER/BOOT", 290, 215, nets={"1": "GPIO_PC4", "2": "GND"}, fp="SW",
           mpn="Omron B3U-1000P (3x2.5mm SMD タクト, 上押し)")
    res(io, "R111", "10k", 320, 215, "+3V3", "GPIO_PC4", rot=0)
    io.add("LED", "D3", "GREEN STAT", 290, 240, rot=180, nets={"2": "+3V3", "1": "LED_STAT_K"}, fp="LED1608",
           mpn="1608 チップ LED")
    res(io, "R112", "1k", 320, 240, "LED_STAT_K", "GPIO_PC4", rot=0)
    res(io, "R114", "4.7k", 350, 215, "+3V3", "I2C_SDA", rot=0, dnp=True)
    res(io, "R115", "4.7k", 380, 215, "+3V3", "I2C_SCL", rot=0, dnp=True)
    res(io, "R120", "470R", 350, 240, "nFAULT_IN", "nFAULT", rot=0)
    res(io, "R122", "10k", 380, 240, "+3V3", "nFAULT", rot=0)
    cap(io, "C103", C_100N, 350, 262, "NTC", "GND", rot=0)
    res(io, "R110", "10k", 380, 262, "+3V3", "NTC", rot=0, dnp=True)
    io.text("NTC 本体は子基板 (MOSFET 近傍)。PA4 の ISOURCE1 で駆動。I2C プルアップ R114/R115 は必要時のみ。", 163, 280, 1.2)
    return prj


PROJECTS.append(build_main())


# ===========================================================================
# パワー段子基板 (モジュールを上面のソケットで受け, MOSFET 等は下面 = ヒートシンク側)
# ===========================================================================
DAUGHTERS = {
    "A": dict(fet="TPN1R603PL", sym="NMOS", fp="TSON", mpn="Toshiba TPN1R603PL,L1Q (30V 1.6mΩ Qg 41nC)",
              g="4", d="5", s="1", rg="47R", rpd="20k", shunt=("10mR 1% 2W", "R2512", "2512 2W (例: Bourns CRA2512-FZ-R010ELF)"),
              bulk=[("100uF/25V", "CPE8x6", "Panasonic EEE-FK1E101P (8x6.2mm)")] * 2,
              bemf=("20k 1%", "3k 1%"), ovp=("110k 1%", "OVP 18V (VBUS/12)"),
              tvs=("SMBJ16A", "SMBJ16A (Vwm 16V)"), vin="8〜16V (公称 12V)", ipk="約 10A (ピンヘッダ律速)",
              title="子基板 A: TPN1R603PL (12V 系)"),
    "B": dict(fet="TKR74F04PB", sym="NMOS_TO263", fp="TO263", mpn="Toshiba TKR74F04PB,LQ (40V 0.74mΩ TO-220SM(W)) ※ランドは TO-263-2 で暫定",
              g="1", d="2", s="3", rg="22R", rpd="10k", shunt=("10mR 1% 3W", "R2512", "2512 3W (例: Bourns CRE2512-FZ-R010E-3)"),
              bulk=[("47uF/35V", "CPE6x6", "Panasonic EEE-FK1V470P (6.3x6.1mm)")] * 3,
              bemf=("47k 1%", "3.3k 1%"), ovp=("180k 1%", "OVP 28.5V (VBUS/19)"),
              tvs=("SMBJ24A", "SMBJ24A (Vwm 24V)"), vin="12〜24V (上限 26V, 安定化電源)", ipk="約 10A (ピンヘッダ律速)",
              title="子基板 B: TKR74F04PB (24V 系)"),
    "C": dict(fet="MTN2306AN3", sym="NMOS_SOT23", fp="SOT23", mpn="Cystech MTN2306AN3 (30V 5.5A 25mΩ SOT-23)",
              g="1", d="3", s="2", rg="47R", rpd="20k", shunt=("10mR 1% 0.5W", "R1206", "1206 0.5W (例: Yageo PE1206FRF7W0R01L)"),
              bulk=[("100uF/25V", "CPE8x6", "Panasonic EEE-FK1E101P (8x6.2mm)")],
              bemf=("20k 1%", "3k 1%"), ovp=("110k 1%", "OVP 18V (VBUS/12)"),
              tvs=("SMBJ16A", "SMBJ16A (Vwm 16V)"), vin="8〜16V (公称 12V)", ipk="約 3A", title="子基板 C: MTN2306AN3 (廉価版)"),
}


def build_daughter(key):
    v = DAUGHTERS[key]
    name = f"mPBCH32M030DS0_PWR_{key}"
    prj = Project(name, f"daughter/PWR_{key}", f"mPBCH32M030DS0 power board {key} ({v['fet']})", [
        f"mPBCH32M030DS0 Rev 0.4 {v['title']}",
        "",
        f"・MOSFET: {v['fet']} x8 (4 ハーフブリッジ)   入力電圧: {v['vin']}   出力電流の目安: {v['ipk']}",
        "・上面: MCU モジュールを挿す 1x21 ピンソケット x2 (左右対称, 列間 15.24mm), 電源入力 J3, モータ出力 J4, バルク容量",
        "・下面 (ヒートシンク側): MOSFET, シャント, ゲート抵抗, 理想ダイオード, TVS, 78L05 など。LED は置かない (モジュール側)",
        "・電圧系に依存する部品 (TVS, VBUS 分圧 = OVP, バルク容量, 相電圧分圧) はこの基板で決める",
        "",
        "J3 電源入力 (2x6): 1-6 = VIN, 7-12 = GND    J4 モータ出力 (2x8): 1-4 = OUT0, 5-8 = OUT1, 9-12 = OUT2, 13-16 = OUT3",
        "  3相 = U/V/W (OUT0-2), DC x2 = OUT0-1 / OUT2-3, ステッピング = A+ A- B+ B-",
        "JP5 (はんだ, 1-2 済): ISP2 = HB1 / 2-3: HB2      JP7 (はんだ, 1-2 済): ISP1 = HB0 / 2-3: バス電流",
    ])
    # ===== 電源入力 / PD 経路 / 5V =====
    pw = prj.sheet("power", "モジュール用ソケット / 電源入力・理想ダイオード / USB-PD 経路 / 5V")
    pw.box(15, 20, 140, 285, "モジュール用ソケット (上面, 左右対称)")
    pw.add("CONN21", "J1", "SOCK_L", 45, 40, nets=PINMAP_L, fp="SOCK1x21", mpn="2.54mm 1x21 ピンソケット (標準 8.5mm 高)")
    pw.add("CONN21", "J2", "SOCK_R", 110, 40, nets=PINMAP_R, fp="SOCK1x21", mpn="2.54mm 1x21 ピンソケット (標準 8.5mm 高)")

    pw.box(150, 20, 405, 120, "電源入力 J3 → F1 → 理想ダイオード (U4+Q9) → VBUS / TVS / バルク容量")
    pw.add("CONN2x6", "J3", "PWR_IN", 175, 45, nets={str(n): ("VIN" if n <= 6 else "GND") for n in range(1, 13)},
           fp="HDR2x6", mpn="2.54mm 2x6 ピンヘッダ (1-6 = VIN, 7-12 = GND, 各 6 本並列)")
    pw.add("FUSE", "F1", "10A", 215, 45, rot=90, nets={"1": "VIN", "2": "VIN_F"}, fp="NANO2",
           mpn="Littelfuse 0451010.MRL (NANO2 2410, 10A 速断)")
    pw.add("NMOS", "Q9", "TPN2R304PL", 250, 45, rot=270, nets={"1": "VIN_F", "4": "Q9_G", "5": "VBUS"},
           fp="TSON", mpn="Toshiba TPN2R304PL,L1Q (40V 2.3mΩ, 理想ダイオード)")
    pw.add("LM74700", "U4", "LM74700-Q1", 250, 85,
           nets={"6": "VIN_F", "3": "VIN_F", "1": "VCAP1", "4": "VBUS", "5": "Q9_G", "2": "GND"},
           fp="SOT236", mpn="TI LM74700QDBVRQ1")
    cap(pw, "C5", C_100N, 285, 85, "VCAP1", "VIN_F", rot=0)
    tv, tmpn = v["tvs"]
    pw.add("D_TVS", "D1", tv, 310, 60, rot=270, nets={"1": "VBUS", "2": "GND"}, fp="SMB", mpn=tmpn)
    cap(pw, "C1", C_10U50, 335, 60, "VBUS", "GND")
    for k, (val, fp, mpn) in enumerate(v["bulk"]):
        pw.add("CP", f"C{7 + k}", val, 360 + 15 * k, 60, nets={"1": "VBUS", "2": "GND"}, fp=fp, mpn=mpn)
    pw.text("バルク容量はモジュールの真下 (上面, 高さ ≤7mm)。ソケット高 8.5mm の下に収まる。", 153, 110, 1.3)

    pw.box(150, 125, 405, 205, "USB-PD 給電経路 (モジュールの USB_VBUS → VBUS, PD 契約後に PC3 で許可)")
    pw.add("FUSE", "F3", "5A", 175, 150, rot=90, nets={"1": "USB_VBUS", "2": "USB_VBUS_P"}, fp="FUSE1812",
           mpn="1812 5A 速断ヒューズ (例: Bourns SF-1812F500)")
    pw.add("D_TVS", "D9", "SMAJ20A", 200, 170, rot=270, nets={"1": "USB_VBUS_P", "2": "GND"}, fp="SMA",
           mpn="SMAJ20A (USB 側サージ)")
    pw.add("NMOS", "Q10", "TPN1R603PL", 250, 150, rot=270, nets={"1": "USB_VBUS_P", "4": "Q10_G", "5": "VBUS"},
           fp="TSON", mpn="Toshiba TPN1R603PL,L1Q (USB 側 理想ダイオード)")
    pw.add("LM74700", "U5", "LM74700-Q1", 250, 185,
           nets={"6": "USB_VBUS_P", "3": "PD_PWR_EN", "1": "VCAP2", "4": "VBUS", "5": "Q10_G", "2": "GND"},
           fp="SOT236", mpn="TI LM74700QDBVRQ1")
    cap(pw, "C6", C_100N, 290, 185, "VCAP2", "USB_VBUS_P", rot=0)
    res(pw, "R6", "100k", 320, 185, "PD_PWR_EN", "GND", rot=0)
    pw.text("PD_PWR_EN = Low (リセット中も R6 で Low) → OFF。FW が PS_RDY と USB_VBUS_SNS を確認してから ON。", 153, 200, 1.25)

    pw.box(150, 210, 405, 285, "VBUS 分圧 (OVP / ADC) / ホールセンサ用 5V")
    ov, ovn = v["ovp"]
    res(pw, "R11", ov, 180, 235, "VBUS", "VBUS_SNS")
    res(pw, "R12", "10k 1%", 180, 260, "VBUS_SNS", "GND")
    pw.text(f"VBUS_SNS → モジュール PB4 (ADC17 + 過電圧リセット 1.5V): {ovn}", 153, 280, 1.25)
    pw.add("REG3", "U2", "78L05", 280, 240, nets={"3": "VBUS", "1": "+5V", "2": "GND"}, fp="SOT89",
           mpn="78L05 (SOT-89, Vin ≤30V)")
    cap(pw, "C3", C_1U50, 255, 262, "VBUS", "GND")
    cap(pw, "C4", C_1U25, 310, 262, "+5V", "GND")

    # ===== パワー段 =====
    br = prj.sheet("bridge", "パワー段 (4 ハーフブリッジ) / シャント / 相電圧分圧 / モータ出力")
    g, d, s = v["g"], v["d"], v["s"]
    for i in range(4):
        bx = 15 + i * 98
        cx, yH, yL = bx + 45.72, 50.8, 91.44
        xg, ys = cx - 8.89, (yH + yL) / 2
        br.box(bx, 20, bx + 94, 130, f"ハーフブリッジ HB{i}  (OUT{i})")
        rb = 30 + 10 * i
        br.add(v["sym"], f"Q{1 + 2 * i}", v["fet"], cx, yH, fp=v["fp"], mpn=v["mpn"],
               nets={g: f"GH{i}", d: "VBUS", s: f"SW{i}"}, wired=(g, d, s))
        br.label("VBUS", cx, yH - 5.08, 90)
        rgh = res(br, f"R{rb + 0}", v["rg"], cx - 17.78, yH, f"HO{i}", f"GH{i}", wired=("2",))
        br.wire(br.pin(rgh, "2"), (cx - 5.08, yH))
        res(br, f"R{rb + 1}", v["rpd"], xg, yH + 8.89, f"GH{i}", f"SW{i}", rot=0, wired=("1", "2"))
        br.wire((xg, yH), (xg, yH + 5.08))
        br.junction(xg, yH)
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
    br.text(f"ゲート: {v['rg']} 直列 + {v['rpd']} G-S プルダウン。ゲート確認 LED はモジュール側 (HOx-SWx / LOx-GND)。", 18, 126, 1.3)

    br.box(15, 140, 200, 285, "バスシャント / 電流チャネル選択 (はんだジャンパ) / モータ出力 J4")
    sv, sfp, smpn = v["shunt"]
    br.add("R", "R70", sv, 45, 160, rot=90, nets={"1": "ISH", "2": "GND"}, fp=sfp, mpn=smpn)
    br.add("SJ3", "JP5", "ISEL_B", 45, 195, nets={"1": "SRC1", "2": "ISB_SEL", "3": "SRC2"}, fp="SJ3",
           mpn="はんだジャンパ 3 端子 (1-2 ブリッジ済み: HB1 / 2-3: HB2)")
    br.add("SJ3", "JP7", "ISEL_A", 45, 225, nets={"1": "SRC0", "2": "ISA_SEL", "3": "ISH"}, fp="SJ3",
           mpn="はんだジャンパ 3 端子 (1-2 ブリッジ済み: HB0 レッグ / 2-3: バス電流)")
    br.add("CONN2x8", "J4", "MOTOR", 130, 170, nets={str(n): f"SW{(n - 1) // 4}" for n in range(1, 17)}, fp="HDR2x8",
           mpn="2.54mm 2x8 ピンヘッダ (各出力 4 本並列)")
    br.text("J4: 1-4=OUT0 5-8=OUT1 9-12=OUT2 13-16=OUT3 (各 4 ピン並列)", 18, 260, 1.4)
    br.text("R70 は全レッグ共通の帰路 (ISH→GND)。ISH/ISA_SEL/ISB_SEL はシャント端からケルビン配線でソケットへ。", 18, 268, 1.25)

    br.box(210, 140, 405, 285, "相電圧 (BEMF) 分圧 / 温度 (NTC)")
    r1, r2 = v["bemf"]
    for k, ph in enumerate("UVW"):
        xb = 235 + k * 55
        res(br, f"R{71 + 3 * k}", r1, xb, 165, f"SW{k}", f"BEMF_{ph}")
        res(br, f"R{72 + 3 * k}", r2, xb, 190, f"BEMF_{ph}", "GND")
        cap(br, f"C{71 + k}", C_1N, xb + 20, 178, f"BEMF_{ph}", "GND")
    br.add("NTC", "TH1", "10k B3435", 250, 240, nets={"1": "NTC", "2": "GND"}, fp="R1005",
           mpn="NTC 10kΩ B3435 1005 (例: Murata NCP15XH103F03RC) — MOSFET 近傍")
    br.text(f"分圧 {r2} / ({r1} + {r2}): 入力電圧上限で ≤ 2.5V。", 213, 275, 1.3)
    return prj


for _k in DAUGHTERS:
    PROJECTS.append(build_daughter(_k))

# ---------------------------------------------------------------------------
# 出力
# ---------------------------------------------------------------------------
def to_v8(t):
    if os.environ.get("MPB_NO_V8"):
        return t
    """生成した KiCad 7 形式の S 式を KiCad 8 (20231120) の書式に揃える."""
    import re as _re
    t = t.replace("(version 20230121) (generator eeschema)",
                  '(version 20231120) (generator "eeschema") (generator_version "8.0")')
    t = t.replace("(kicad_symbol_lib (version 20220914) (generator gen_schematic)",
                  '(kicad_symbol_lib (version 20231120) (generator "kicad_symbol_editor") (generator_version "8.0")')
    t = _re.sub(r"\(uuid ([0-9a-f-]{36})\)", r'(uuid "\1")', t)
    t = t.replace("(fields_autoplaced)", "(fields_autoplaced yes)")
    t = _re.sub(r"(\(effects \(font \(size [\d.]+ [\d.]+\)(?: \(thickness [\d.]+\))?\)(?: \(justify [a-z ]+\))?) hide\)",
                r"\1 (hide yes))", t)
    t = t.replace(") bold)", ") (bold yes))")
    t = t.replace("(in_bom yes) (on_board yes)", "(exclude_from_sim no) (in_bom yes) (on_board yes)")
    # シート上の自由テキスト (行頭) だけ。シンボル図形内の text には付けない
    t = _re.sub(r'^\(text ("(?:[^"\\]|\\.)*") \(at', r"(text \1 (exclude_from_sim no) (at", t, flags=_re.M)
    return t


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
            f.write(to_v8(sheet_sexpr(sh, sheet_uuids[sh.key])))
    with open(os.path.join(d, f"{prj.name}.kicad_sch"), "w", encoding="utf-8") as f:
        f.write(to_v8(root_sexpr(sheet_uuids)))
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
        f.write(to_v8(lib) + "\n")


if __name__ == "__main__":
    main()
