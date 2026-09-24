#!/usr/bin/env python3
"""
部品配置図 (フロアプラン) を SVG で生成する。  python3 gen_placement.py -> ../docs/placement.svg

寸法は mm。PCB レイアウト前の「どこに何を置くか」の指針で、実寸フットプリントではない
(端子台・コネクタ・主要部品はおおよその実寸)。
"""
import os

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "placement.svg")
BW, BH = 90, 64          # 基板外形 [mm]
S = 10                   # px / mm
MX, MY = 40, 70          # 図の余白 [px]
LEGEND_W = 330

COL = {
    "pwr": ("#fde2e1", "#c0392b"),    # 電源入力・保護
    "brg": ("#fdebd0", "#d35400"),    # パワー段
    "mcu": ("#d6eaf8", "#1f618d"),    # MCU・クロック
    "ana": ("#e8daef", "#7d3c98"),    # アナログ (電流/電圧検出)
    "con": ("#d5f5e3", "#1e8449"),    # コネクタ・端子台
    "ui":  ("#fcf3cf", "#9a7d0a"),    # LED・スイッチ
}

# (x, y, w, h, 種別, ラベル, [小ラベル])
PARTS = [
    # --- 上辺: 信号系コネクタ / 操作 ---
    (2, 0, 9, 7.5, "con", "J8 USB-C", "上向き"),
    (12, 1, 4, 4, "mcu", "U3", "ESD"),
    (12, 5.5, 4, 2, "pwr", "F2", ""),
    (18, 1, 6, 6, "ui", "SW1", "RESET"),
    (25.5, 1, 6, 6, "ui", "SW2", "USER"),
    (33, 1, 2.5, 2.5, "ui", "D3", ""),
    (37, 0.5, 13, 3.5, "con", "J7 SWD", "5P"),
    (52, 0, 7, 5, "con", "J4 I2C", "SH4"),
    (61, 0, 13, 6, "con", "J5 UART", "XH4"),
    # --- 右辺: GPIO 引き出し ---
    (84.5, 8, 5, 21, "con", "J6", "GPIO 8P"),
    # --- MCU まわり ---
    (27, 16, 4, 3.5, "mcu", "Y1", "8MHz"),
    (36, 16, 6, 6, "mcu", "U1", "QFN48"),
    (21, 25, 7, 4.5, "pwr", "D5/D6", "R10 VHV"),
    (50, 22, 8, 3, "ana", "JP5", "ISEL"),
    (62, 21.5, 20, 4, "ana", "JP2-JP4", "HALL/BEMF 選択"),
    # --- 電源入力 (左辺・左下) ---
    (0, 44, 8, 11, "con", "J1", "PWR IN"),
    (1, 33, 6, 8, "ui", "D7 D2 D8", "電源LED"),
    (11, 33, 9, 7, "pwr", "U2 78L05", "+5V"),
    (10, 51, 11, 5, "pwr", "F1 15A", ""),
    (10, 44, 5, 5, "pwr", "Q9", "逆接"),
    (16, 44, 5, 5, "pwr", "D1", "TVS"),
    # --- バス電流 ---
    (38, 47, 6.5, 3.5, "ana", "R70", "バスシャント"),
    # --- モータ出力 / ホール (下辺) ---
    (50, 55, 22, 9, "con", "J2 MOTOR", "OUT0-3"),
    (74, 57, 14, 7, "con", "J3 HALL", "XH5"),
    (62, 51.5, 3, 2, "ana", "TH1", ""),
]
CAPS = [(27, 57.5, 5, "C1"), (37.5, 57.5, 5, "C2")]   # バルク電解 (中心, 半径)

# ハーフブリッジ列
HB_X0, HB_W, HB_Y0 = 47, 9, 29


def rect(x, y, w, h, fill, stroke, sw=1.2, rx=1.5, dash=None, op=1.0):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<rect x="{MX + x * S:.1f}" y="{MY + y * S:.1f}" width="{w * S:.1f}" height="{h * S:.1f}" '
            f'rx="{rx}" fill="{fill}" fill-opacity="{op}" stroke="{stroke}" stroke-width="{sw}"{d}/>')


def text(x, y, s, size=11, color="#222", anchor="middle", weight="normal"):
    return (f'<text x="{MX + x * S:.1f}" y="{MY + y * S:.1f}" font-size="{size}" fill="{color}" '
            f'text-anchor="{anchor}" font-weight="{weight}" dominant-baseline="middle">{s}</text>')


def main():
    W = MX * 2 + BW * S + LEGEND_W
    H = MY + BH * S + 150
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
         f'font-family="Noto Sans CJK JP, Noto Sans JP, Meiryo, sans-serif">',
         '<defs><marker id="ar" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">'
         '<path d="M0,0 L6,3 L0,6 z" fill="#c0392b"/></marker></defs>',
         f'<rect width="{W}" height="{H}" fill="#ffffff"/>',
         f'<text x="{MX}" y="30" font-size="20" font-weight="bold" fill="#222">'
         f'mPBCH32M030DS0 部品配置図 (Top view, {BW}×{BH} mm, 4層推奨)</text>',
         f'<text x="{MX}" y="52" font-size="12" fill="#555">上半分 = ロジック/信号 (静かな領域), '
         f'下半分 = パワー (大電流領域)。端子台はすべて基板端に置き, 電線は外向きに出す。</text>']
    # 基板外形とゾーン
    o.append(rect(0, 0, BW, BH, "#f7f9f9", "#2c3e50", sw=2.5, rx=4))
    o.append(rect(0.5, 28, BW - 1, BH - 28.5, "#fdecea", "#e6b0aa", sw=1, dash="6,4", op=0.5))
    o.append(text(1.5, 62.6, "パワー領域 (2oz 銅, 太パターン/ベタ)", 11, "#a93226", "start"))
    o.append(rect(0.5, 8.5, 60, 19, "#eaf2f8", "#a9cce3", sw=1, dash="6,4", op=0.5))
    o.append(text(1.5, 9.8, "ロジック/アナログ領域", 11, "#1f618d", "start"))
    # 部品
    for x, y, w, h, k, lab, sub in PARTS:
        f, st = COL[k]
        o.append(rect(x, y, w, h, f, st))
        cy = y + h / 2 - (0.9 if sub else 0)
        o.append(text(x + w / 2, cy, lab, 10 if w > 5 else 8, st, weight="bold"))
        if sub:
            o.append(text(x + w / 2, y + h / 2 + 1.1, sub, 8, st))
    for cx, cy, r, lab in CAPS:
        f, st = COL["pwr"]
        o.append(f'<circle cx="{MX + cx * S}" cy="{MY + cy * S}" r="{r * S}" fill="{f}" stroke="{st}" stroke-width="1.2"/>')
        o.append(text(cx, cy - 0.7, lab, 10, st, weight="bold"))
        o.append(text(cx, cy + 1.2, "470uF", 8, st))
    # ハーフブリッジ列
    for i in range(4):
        x = HB_X0 + i * HB_W
        f, st = COL["brg"]
        o.append(rect(x, HB_Y0, HB_W - 0.8, 21, "#fef5e7", st, sw=1.2))
        o.append(text(x + (HB_W - 0.8) / 2, HB_Y0 + 1.3, f"HB{i}", 10, st, weight="bold"))
        o.append(rect(x + 1, HB_Y0 + 2.6, 2.6, 1.4, *COL["ui"], sw=0.8, rx=0.5))
        o.append(rect(x + 4.4, HB_Y0 + 2.6, 2.6, 1.4, *COL["ui"], sw=0.8, rx=0.5))
        o.append(text(x + (HB_W - 0.8) / 2, HB_Y0 + 4.9, "LED H / L", 7, COL["ui"][1]))
        o.append(rect(x + 2.3, HB_Y0 + 6, 3.3, 3.3, f, st, rx=0.6))
        o.append(text(x + 3.95, HB_Y0 + 7.65, f"Q{1 + 2 * i}", 8, st))
        o.append(rect(x + 2.3, HB_Y0 + 10.5, 3.3, 3.3, f, st, rx=0.6))
        o.append(text(x + 3.95, HB_Y0 + 12.15, f"Q{2 + 2 * i}", 8, st))
        o.append(rect(x + 1.1, HB_Y0 + 15, 6.3, 3.2, *COL["ana"], rx=0.4))
        o.append(text(x + 4.25, HB_Y0 + 16.6, f"R{34 + 10 * i} 10mΩ", 7, COL["ana"][1]))
        o.append(text(x + 4.25, HB_Y0 + 19.5, "C 0.1u+10u", 7, st))
    # 大電流ループ (矢印)
    path = [(4, 46), (15, 53.5), (29, 50), (45, 50), (47, 38), (80, 38), (80, 47.5), (44.5, 48.7),
            (38, 48.7), (12.5, 49), (4, 52)]
    d = " ".join(("M" if i == 0 else "L") + f"{MX + x * S:.0f},{MY + y * S:.0f}" for i, (x, y) in enumerate(path))
    o.append(f'<path d="{d}" fill="none" stroke="#c0392b" stroke-width="2.5" stroke-dasharray="10,5" '
             f'marker-end="url(#ar)" opacity="0.8"/>')
    o.append(text(26, 43, "大電流ループ: J1→F1→C1/C2→VBUS→HB→シャント→R70→Q9→J1", 9, "#c0392b"))
    # スター GND / ケルビン
    o.append(f'<circle cx="{MX + 41 * S}" cy="{MY + 51.7 * S}" r="6" fill="#c0392b"/>')
    o.append(text(42.3, 51.9, "★GND スター点", 8, "#c0392b", "start"))
    o.append(f'<path d="M{MX + 51 * S},{MY + 44 * S} L{MX + 44 * S},{MY + 27 * S} L{MX + 41 * S},{MY + 22 * S}" '
             f'stroke="{COL["ana"][1]}" stroke-width="1.5" fill="none" stroke-dasharray="3,3"/>')
    o.append(text(47.5, 26.4, "ケルビン差動配線", 8, COL["ana"][1], "start"))
    # 凡例と要点
    lx = MX + BW * S + 25
    o.append(f'<text x="{lx}" y="{MY + 10}" font-size="14" font-weight="bold" fill="#222">凡例</text>')
    for j, (k, name) in enumerate([("pwr", "電源入力・保護"), ("brg", "パワー段 (FET)"), ("mcu", "MCU・クロック"),
                                   ("ana", "電流/電圧検出"), ("con", "コネクタ・端子台"), ("ui", "LED・スイッチ")]):
        y = MY + 30 + j * 24
        f, st = COL[k]
        o.append(f'<rect x="{lx}" y="{y - 8}" width="22" height="16" rx="2" fill="{f}" stroke="{st}"/>')
        o.append(f'<text x="{lx + 30}" y="{y + 4}" font-size="12" fill="#222">{name}</text>')
    notes = [
        "端子台の配置",
        "・J1 電源 (2P) は左辺, J2 モータ (4P) は下辺",
        "  → 別の辺に分けて誤接続を防ぐ",
        "・J2 と J3 ホールは隣接 → モータ線と",
        "  センサ線を同じ方向へまとめて出せる",
        "・F1/C1/C2 は J1 と HB 列の間の最短経路",
        "・端子台はネジ面を基板外側に向ける",
        "",
        "パワー段",
        "・HB0〜HB3 を一列に並べ, J2 へ最短",
        "・各レッグの 0.1u/10u は FET 直近",
        "・TSON 裏面パッドに放熱ビア ≥9 本",
        "・TH1 (NTC) は FET 列の直下",
        "",
        "ロジック",
        "・U1 は信号領域の中央, 水晶 Y1 は",
        "  XI/XO (PB5/PB6) 側に 5mm 以内",
        "・USB-C は上辺, D+/D- は 90Ω 差動",
        "・VB/VS ブート容量は U1 ピン直近",
        "・QFN 0.35mm ピッチ: 4層・0.1mm",
        "  ルール, 裏面パッドに GND ビア",
    ]
    for j, t in enumerate(notes):
        bold = ' font-weight="bold"' if t and not t.startswith(("・", " ")) else ""
        o.append(f'<text x="{lx}" y="{MY + 185 + j * 18}" font-size="12" fill="#333"{bold}>{t}</text>')
    # 寸法
    o.append(f'<text x="{MX + BW * S / 2}" y="{MY + BH * S + 25}" font-size="12" fill="#555" '
             f'text-anchor="middle">← {BW} mm →</text>')
    o.append(f'<text x="{MX - 12}" y="{MY + BH * S / 2}" font-size="12" fill="#555" text-anchor="middle" '
             f'transform="rotate(-90 {MX - 12} {MY + BH * S / 2})">← {BH} mm →</text>')
    o.append(f'<text x="{MX}" y="{MY + BH * S + 55}" font-size="12" fill="#555">'
             f'※ 概略配置 (寸法は目安)。実際のフットプリントと配線は KiCad PCB エディタで作成すること。</text>')
    o.append("</svg>")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(o))
    print("wrote", os.path.normpath(OUT))


if __name__ == "__main__":
    main()
