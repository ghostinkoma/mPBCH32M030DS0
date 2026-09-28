# 電流容量・ノイズのチェック

銅箔 (配線・ベタ・ビア, 両面) を 0.05mm 格子の抵抗網にして電流分布を解き, IPC-2221 (外層 1oz, ΔT 20°C) と比べる。

```sh
# 1) 形状の書き出し (KiCad 8 の Python)
python3 extract.py ../../daughter/PWR_A/mPBCH32M030DS0_PWR_A.kicad_pcb VIN,VIN_F,VBUS,SW0,SW1,SW2,SW3,SRC0,SRC1,SRC2,SRC3,GND,ISH,USB_VBUS,USB_VBUS_P A.json
# 2) 解く (numpy / scipy / pyamg / pillow)
python3 solve.py A.json "$(python3 cases.py A)" > res_A.jsonl
# 3) 経路ごとの許容電流
python3 rate.py A
```

- 経路 (cases.py): 電源入力 J3→F1→Q9→各ハイサイド、相出力 FET→J4、ローサイド→シャント→R70→J3、USB-PD J1→F3→Q10。
- コネクタのピンは接触抵抗 10mΩ で外部ノードへつなぐ (ピンごとの電流が出る)。部品のパッドは等電位。
- 許容電流は, パッドの口元 0.5mm を除いた最大電流密度から求めた等価幅で判定する。
- `noise.py`: モジュールの 3.3V 系・アナログ系の配線が, スイッチング系 (SW/VB/HO/LO) と同一層で近接する長さと,
  下に GND の無い長さを出す (`extract_all.py` の出力を使う)。
