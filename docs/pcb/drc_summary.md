# DRC 結果 (KiCad 8 pcbnew, gen_pcb.py 実行時に自動生成)

ルール: 2 層 / 最小線幅・間隙 0.127mm / ビア 0.6mm (穴 0.3mm, 大電流 0.8mm, QFN サーマルビア 0.2mm) / 基板端 0.25mm (ベタは 1.0mm)。
「lib_footprint_issues」(ライブラリ照合) はスクリプト生成のため対象外。

| 基板 | 電気的エラー (配線・間隙・未接続など) | 警告 (シルク等, 製造時にクリップされるもの) |
|---|---|---|
| mPBCH32M030DS0 | なし | silk_edge_clearance 6, silk_over_copper 12, silk_overlap 26 |
| mPBCH32M030DS0_PWR_A | なし | silk_edge_clearance 2, silk_over_copper 69, silk_overlap 9 |
| mPBCH32M030DS0_PWR_B | なし | silk_edge_clearance 7, silk_over_copper 89, silk_overlap 7, track_dangling 4 |
| mPBCH32M030DS0_PWR_C | なし | silk_edge_clearance 2, silk_over_copper 57, silk_overlap 8, track_dangling 1 |
