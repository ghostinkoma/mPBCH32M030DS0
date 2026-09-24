# 内蔵機能の活用検討 (Rev 0.1 → Rev 0.2)

Rev 0.1 では CH32M030 の内蔵機能を「電流検出と過電流保護」中心にしか使っていませんでした。
Rev 0.2 では、残っていた次の 3 群について**どう適用できるか**を検討し、効果の大きいものを回路とファームウェアに取り込みました。

1. プログラマブル電流源 / シンク (ISOURCE ×2, ISINK ×2)
2. USB-PD / Type-C の高度な機能
3. OPA ×4 / CMP ×3 / DAC の全組み合わせ

数値の出典は CH32M030DS0 V1.2 (DS) と CH32M030RM V1.2 (RM) です。
**実機では未確認**です。推定を含む項目は【要実機確認】と書いています。

## 0. 結論サマリ

| 機能 | Rev 0.1 | Rev 0.2 | 判断 |
|---|---|---|---|
| ISOURCE1 (PA4) | NTC 駆動 | 同じ (工場校正値で温度換算する FW を追加) | 採用継続 |
| ISOURCE2 (PA5) | 未使用 | **モーター結線の自己診断** (パワー段を通電せずに U-V 間の導通を確認) | 採用 (FW のみ) |
| ISINK1/2 (PA6/PA7) | 未使用 | PD PHY の動作に必要な ISINKEN を有効化。ピンは 3 相センシングに割り当て | 一部採用。本来用途 (DC-DC の微調整) は Rev 0.3 案 |
| USB-PD | Rd 受電 (5V) のみ | **PD シンクで 9/12/15V を交渉し、モーター電源として給電** (理想ダイオード OR, 最大 15V/5A) | 採用 (回路 + FW) |
| CMP3 + 内部仮想中性点 + TIM2 捕捉 | 未使用 | **センサレス BLDC の BEMF ゼロクロスをハードウェアで検出** | 採用 (ピン再配置) |
| TIM2 ホール XOR | EXTI で処理 | **同じ PA5/PA6/PA7 でホールセンサインタフェースを使用** | 採用 |
| CMP2 + DAC | IA の第 2 保護 | **JP7 でバス電流に切り替えてサイクル毎の電流制限** (PD 契約電流やセンサレス時の保護) | 採用 |
| OPA1 + CMP1 (QII1) → TIM3 | 未使用 | **タコ / VR センサ入力、ブラシ DC の電流リップル計数** (エンコーダ無しで回転数・位置を推定) | 採用 (JP8) |
| OPA2 + CMP2 (QII2) | 未使用 | 見送り (CMP2 を保護に使うため。入力 PA13 は nFAULT) | 見送り |
| Q_DET (PA14/PA15 出力) | 未使用 | 見送り (I2C に使用。OPA 出力は ADC に内部接続) | 見送り |

**トレードオフ**: GPIO 引き出しから PC3 と PA6 がなくなりました (PD 給電の許可と W 相センシングに使うため)。
状態 LED は PC4 (USER/BOOT) と共用にしています。
2 線 SWD (PA2 = SWCLK) もやめて、1 線 SDI (PA3) にしました。WCH-LinkE の標準は 1 線です。

---

## 1. プログラマブル電流源 / シンク

### 1.1 仕様 (DS 表3-38, RM 20.3)

| ブロック | ピン | 範囲・分解能 | 想定用途 (WCH) |
|---|---|---|---|
| ISINK1 / ISINK2 | PA6 / PA7 | 0〜250µA, 0.244µA/LSB (10bit), 更新 1MS/s, 整定 3µs, 動作にはピン電圧 0.6V 以上が必要 | 外付け DC-DC の FB に電流を注入し、出力を 20mV 刻みで調整する (PPS) |
| ISOURCE1 / ISOURCE2 | PA4 / PA5 | 2 ギア (High/Low)。電流値は工場校正値 (`ISOURCEx_GetData()`, nA) | NTC による温度測定 |

どちらも `PWR_ISINKCmd(ENABLE)` (ISINKEN) が前提です。また USB PD PHY を使う場合も ISINKEN が必要です (RM 15.2 注記)。

### 1.2 適用結果

- **ISOURCE1 → NTC (継続)**: 抵抗は R = V / I (I は工場校正値) で求め、B 定数の式で温度に換算します (`Mpb_Ntc_DeciCelsius()`)。
  外付けの分圧抵抗が不要になり、R110 は DNP のまま使いません。
- **ISOURCE2 → モーター結線の自己診断 (新規)**
  - PA5 は SENS_U (BEMF_U の分圧点) につながっています。ここへ Is を注入すると、モーターが接続されていれば
    `BEMF_U → 20k → OUT0 → 巻線 → OUT1 → 20k → BEMF_V → 3k → GND` の経路ができます。
  - その結果、PA7 (ADC) に **BEMF_V ≈ Is × 131Ω** が現れます (Is = 100µA なら約 13mV = 16LSB)。
  - 未接続・断線なら 0V です。**FET を一度も ON にせずに**、「モーター未接続」「U/V 断線」を起動前に検出できます。
  - 条件: JP2/JP3 = 1-2、ゲート OFF (`Mpb_SelfTest_Wiring()`)。W 相 (PA6) には ADC がないため、W の断線は低電力の試験パルスで確認します (FW)。
- **ISINK1/ISINK2**
  - ピンが CMP3 の N 入力 (PA6/PA7) と同じです。Rev 0.2 では 3 相センシングを優先したので、ISINK 出力は使いません。
    ただし PD のために ISINKEN は常時有効です。
  - ISINK の本領は「ソフトウェアで出力電圧を 20mV 刻みで変えられる DC-DC」です。モーター基板では、**可変補助電源 (AUX 3.3〜12V)** として活きます
    (ファン・サーボ・センサ・LED テープへの給電)。
    FB 分圧の上側抵抗を R1 とすると、Vout = VFB·(1 + R1/R2) + I_SINK·R1 です。R1 = 80kΩ なら 0.244µA × 80k ≈ 19.5mV/LSB、
    全範囲で 20V です。
  - → **Rev 0.3 案**: ステッピング / DC モードでは PA6/PA7 が空くので、ジャンパで ISINK2 を AUX 降圧の FB に接続できます
    (3 相モードでは既定電圧で固定)。

---

## 2. USB-PD / Type-C

### 2.1 Rev 0.1 の状態

CC1R/CC2R 内蔵の Rd で 5V を受電し、USB FS (書き込み) と MCU への給電だけに使っていました。PD 通信はしていませんでした。

### 2.2 Rev 0.2: PD シンクでモーター電源を得る

```
USB-C VBUS ─F3 5A─ USB_VBUS_P ─┬─ Q10 (TPN1R603PL) ── VBUS (モーター電源)
                               │   └ U5 LM74700 (理想ダイオード, EN = PC3)
                               ├─ D9 SMAJ20A
                               └─ 120k/10k → PA2 (USB_VBUS_SNS, ADC IN15)
J1 12V ─F1 15A─ VIN_F ── Q9 (TPN1R603PL) ── VBUS
                          └ U4 LM74700 (理想ダイオード, 常時 ON = 逆接保護を兼ねる)
```

| 項目 | 設計 |
|---|---|
| 交渉 | PD0 (CC1/CC2 = PA0/PA1)。WCH `USBPD_SNK` を移植 (`pd_process.c`)。Source_Capabilities の固定 PDO から **8〜15V で最も高い電圧** (同電圧なら電流の大きい方) を要求 (`Mpb_PD_SelectPdo()`) |
| 15V 上限の理由 | VBUS 側の TVS SMBJ16A (Vwm 16V)、MOSFET 30V、VHV 絶対最大 30V。20V PDO は要求しない |
| 給電許可 | PS_RDY を受信し、USB VBUS が契約電圧の ±10% に入っていることを PA2 で確認してから PD_PWR_EN = High |
| 遮断 | USB VBUS < 3.5V (抜去) か契約電圧から逸脱したら即 OFF。MCU リセット中は R6 で OFF。**PB4 の OVP リセット (VBUS 18V) でも自動で OFF** |
| J1 との共存 | **理想ダイオード OR**。電圧の高い側が供給し、互いに逆流しない (J1 12V と PD 15V を同時につないでも安全)。PD ソースが電流制限で落ちると、自動的に J1 へ引き継がれる |
| 逆接保護 | Rev 0.1 の GND 側 FET (Q9) は、U4 + Q9 のハイサイド理想ダイオードに置き換え (−65V まで耐える) |
| ESD | USBLC6-2SC6 の VBUS ピン定格は 5.25V → 基準を +3V3 に変更。VBUS には SMAJ20A |
| 電流 | ケーブル 3A (e-marker 付きで 5A)。15V × 3A = 45W、15V × 5A = 75W。FW で IBUS を契約電流以下に制限し、CMP2 + DAC でサイクル毎の上限も設定可能 |

### 2.3 見送った / 将来の PD 機能

| 機能 | 判断 |
|---|---|
| PPS (プログラマブル電源) | WCH サンプルは PPS APDO を除外する。電圧を細かく選べる利点はあるが、モーター用途では固定 PDO で十分 → 将来 |
| PD1 (CC3/CC4 = PA2/PA3) でのソース / DRP | PA2 を USB VBUS 監視、PA3 を SDI に使うため見送り。2 ポート目の USB-C で外部機器へ給電するなら Rev 0.3 で検討 |
| BC1.2 / DCP 判定 | 5V (最大 1.5A) しか得られずモーター駆動には不足 → 使わない |
| USB FS とデータの同時利用 | 対応済み。PD シンク中も USB ベンダーインターフェース (書き込み・設定) は使える |

---

## 3. OPA / CMP / DAC の組み合わせ

### 3.1 ブロックと接続可能性 (RM 第 17 章)

| ブロック | 入力 | 出力先 | 主な設定 |
|---|---|---|---|
| OPA1 (QII1) | PA12 (90kΩ 入力, 自己バイアス 1.23V) | CMP1, ADC IN19 | AV 20/40 |
| OPA2 (QII2) | PA13 | CMP2, ADC IN18 | AV 5/10/20/40, QII / 増幅モード |
| OPA3 (ISP1) | ISP1 / PA8 (ISN1) or VSS | ADC IN9, CMP2 P, CMP3 P | 4/8/16/55, バイアス 0.55/1.6V |
| OPA4 (ISP2) | PA10 / PA11 or VSS | ADC IN10, CMP3 P | 同上 |
| CMP1 | OPA1 出力 | **TIM3 CH1 捕捉**, PA12 | ヒス 100/200mV, デジタルフィルタ |
| CMP2 | P: PB5 / OPA2 / OPA3、N: PB6 / VB / **DAC (0.1〜3.1V, 0.2V 刻み)** / VSS | **TIM1 BKIN**, 割込み, PA13 | ヒス 0〜200mV, フィルタ 375ns〜12µs |
| CMP3 | P: PA3 / PB0 / PB1 / PB3 / OPA3 / OPA4、N: PA5 / PA6 / PA7 / PB2 / DAC、**内部仮想中性点 RMID (80kΩ ×3)** | **TIM1 BKIN**, **TIM2 CH1〜4 巡回捕捉** (TIM1 CC4/CC5・TIM2/TIM3 CCx で切替), PB4/PB5 | ヒス 0〜40mV, フィルタ |

### 3.2 Rev 0.2 の割り当て (モード別)

| モード | JP7 / JP5 | OPA3 | OPA4 | CMP2 | CMP3 | OPA1+CMP1 | TIM2 |
|---|---|---|---|---|---|---|---|
| 3 相 FOC (2 シャント) | 1-2 / 1-2 | IA = U 相 (差動) | IB = V 相 | IA 過電流 (DAC) | **バス過電流** (PB3 vs PB2) | タコ等 | (空き) |
| 3 相 ホール 6 ステップ | 1-2 / 1-2 | IA | IB | IA | バス過電流 | — | **ホール XOR** |
| 3 相 センサレス 6 ステップ | **2-3** / 1-2 | **バス電流 (単端)** | IB | **バス過電流 (DAC)** | **BEMF: 各相 (N) vs 仮想中性点 → TIM2 捕捉** | — | BEMF 捕捉 |
| DC ×2 / ステッピング | 1-2 / 2-3 | A 相 | B 相 | A 相電流制限 | バス過電流 | — | HB2/HB3 PWM |
| ブラシ DC + リップル計数 | 1-2 / — | 電流 | — | 電流制限 | バス過電流 | **JP8=2-3: 整流子リップル → TIM3** | — |

ポイント:
- **3 相センシングを PA5/PA6/PA7 に集約**しました (Rev 0.1 の W 相 = PA12 を PA6 へ移動)。これで次の 3 つが同じ 3 本のピンで使えます。
  - CMP3 の N 入力 (N0/N1/N2) と内部仮想中性点 (RMID)
  - TIM2 CH1/CH2/CH3 (ホール XOR)
  - ISOURCE2 / ISINK1 / ISINK2
- センサレス時の比較タイミングは TIM1 CC4 (PWM ON の中央) で CMP3 を切り替えます。スイッチングノイズを避け、結果は TIM2 の CH1→CH2→CH3 に巡回で捕捉されます。
  ソフトウェアの仕事は、転流ごとに浮き相 (NSEL) を選ぶことだけです (`Mpb_Bemf_SelectPhase()`)。
- CMP3 を BEMF に使う間は、**JP7 でバス電流を OPA3 に通し、CMP2 + DAC で保護**します。どのモードでもハードウェアの過電流遮断が残ります。
- DAC (4bit) は粗いですが、OPA3 のゲインで分解能を作れます。G = 16 なら 1 ステップ (0.2V) = 1.25A、G = 8 なら 2.5A (`Mpb_Ocp_DacCode()`)。
- QII1 は本来、ワイヤレス充電の Q 値検出用の AC 小信号アンプ + コンパレータです。AC 結合 (C105) 入力と TIM3 捕捉を活かして、次に使います。
  - **周期計測**: ファン FG、VR センサ、光学センサなどの小振幅パルス
  - **ブラシ DC の整流子リップル計数**: バス電流の AC 成分。エンコーダ無しで回転数・位置を推定できる
  - ゲイン 40 × リップル数 mV が CMP1 のヒステリシス (100mV) を超えない小型モーターでは、OPA1 出力を ADC IN19 で取り込み、ソフトウェアで検出する
- 見送り: OPA2/QII2 (CMP2 を保護に使うため)、Q_DET 出力ピン (PA14/PA15 を I2C に使うため)、CMP3 のアナログ / プッシュプル出力 (PB4/PB5 は VBUS 監視・水晶)。

---

## 4. 回路変更の一覧 (Rev 0.1 → 0.2)

| ピン / 部品 | Rev 0.1 | Rev 0.2 |
|---|---|---|
| PA2 | SWCLK (2 線デバッグ) | **USB VBUS 監視 (ADC IN15)**, R7/R8/C7 |
| PA6 | 状態 LED / GPIO | **SENS_W** (CMP3 N1, TIM2 CH2, ISINK1) |
| PA12 | SENS_W | **QII_IN** (OPA1 → CMP1 → TIM3) |
| PC3 | GPIO (J6) | **PD_PWR_EN** (U5 EN, R6 プルダウン) |
| PC4 | USER/BOOT | USER/BOOT **+ 状態 LED** (+3V3–LED–1k–PC4, オープンドレイン Low 点灯) |
| J1 入力 | Q9 (GND 側逆接保護) + R1/R2/DZ1 | **U4 LM74700 + Q9 (ハイサイド理想ダイオード)** |
| USB 給電 | PTC 0.5A → VHV のみ | + **F3 5A → U5 LM74700 + Q10 → VBUS**, D9 SMAJ20A |
| U3 USBLC6 | VBUS ピン = USB VBUS | VBUS ピン = **+3V3** (PD 20V 対策) |
| JP7 (新) | — | OPA3 入力 = HB0 レッグ / バス |
| JP8 + R123 + C105 (新) | — | QII1 入力 = TACH_IN (J6-5) / バス電流リップル |
| J6 | GND/3V3/PC3/PC4/PA6/PC5/nFAULT/5V | GND/3V3/PC4/PC5/**TACH_IN**/nFAULT/5V/GND |
| J7 | 5P (SWDIO/SWCLK/RST) | **4P 1 線 SDI** (3V3/SWIO/RST/GND) |

## 5. ファームウェア (`firmware/app_template/src/mpb*.c`)

| API | 内容 |
|---|---|
| `Mpb_Time_Init/Micros/Millis` | TIM3 1MHz 時間基準 (TIM3 CH1 はタコ捕捉と共用) |
| `Mpb_ISense_Init/mA` | OPA3/OPA4 (ゲイン, バイアス 1.6V, JP7 に合わせ差動 / 単端) |
| `Mpb_Ocp_BusCmp3_Init` / `Mpb_Ocp_Cmp2_Init` / `Mpb_Ocp_DacCode` | ハード過電流遮断 (TIM1 BKIN) + 割込みで TIM2 側も停止 (`OPA_IRQHandler`) |
| `Mpb_Bemf_Init/SelectPhase` | CMP3 + RMID + TIM1 CC4 同期 + TIM2 巡回捕捉【要実機確認】 |
| `Mpb_Hall_Init` | TIM2 ホールセンサ XOR |
| `Mpb_Tach_Init/PeriodUs` | QII1 (OPA1+CMP1) → TIM3 CH1 |
| `Mpb_Ntc_Init/DeciCelsius` | ISOURCE1 + 工場校正値 + B 定数 |
| `Mpb_SelfTest_Wiring` | ISOURCE2 による結線診断 |
| `Mpb_PD_Init/Task/Status` | PD シンク交渉 + 給電パス制御 (ポリシー: 8〜15V) |

`sketch.c` は PD 交渉・温度・過電流保護を初期化し、PD 給電中は LED を速く点滅させる例です。
ビルドは GCC 13 で警告 0 (アプリ 10.5KB / 44KB)。

## 6. 【要実機確認】

1. **CMP3 の RMID**: 仮想中性点が P 側に入るという解釈 (PSEL = 0x7 = 未接続、リセット値) は RM 図 17-4 からの推定。チャネル切替と TIM2 巡回捕捉の対応も含めてオシロで確認する
2. **LM74700-Q1 のピン配置** (KiCad 公式シンボル: 1 VCAP, 2 GND, 3 EN, 4 CATHODE, 5 GATE, 6 ANODE) と EN しきい値 (3.3V ロジックで ON できること)、VCAP コンデンサの接続先
3. ISOURCE1/2 の実電流 (工場校正値) と、結線診断の判定しきい値 (理論値の 30%)
4. PD の相互接続性 (WCH サンプル自体に「互換性の問題があり得る」との注記がある)。複数の充電器で 9/15V の交渉と抜去検出を確認する
5. USB-C コネクタ (GCT USB4105) とケーブルの定格電流、F3 の溶断特性、VBUS 充電時の突入電流 (PD ソースの OCP が働かないこと)
6. QII1 のリップル計数に必要な信号振幅 (モーターごとにゲイン・ヒステリシスを調整)

## 7. Rev 0.3 の候補

- ISINK2 で出力を調整できる**可変 AUX 降圧電源** (3.3〜12V / 1A, ステッピング・DC モード時)
- PD1 (CC3/CC4) で 2 ポート目の USB-C (ソース / DRP) を設け、外部機器へ給電する
- PPS 対応 (PD 電圧を 20mV 刻みで最適化し、モーターの効率点に合わせる)
