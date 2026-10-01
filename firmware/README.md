# mPBCH32M030DS0 ファームウェア — スケッチ環境 (mpbfun)

`setup()` / `loop()` を書くだけで使える, ch32fun 風の小さな環境です。
モーター制御・I2C・UART ログ・WS2812・LED 調光・センサ・エンコーダを, **どれも待たない (delay を使わない) API** で揃えています。

> **実機では未確認です** (基板未製作)。ビルドは GCC 13 で警告 0, 計算部分はホスト (PC) の単体テストで確認しています。
> モーターを回す前に, 必ず電流制限付きの電源で, ゲート確認 LED とオシロで波形を確かめてください。

## 構成

```
firmware/
├── common/            ボード定義 (board.h), リンカスクリプト, ビルドルール (rules.mk / app.mk)
├── core/              常にリンクされる土台: 起動, USB/UART 書き込み要求, USB-PD, mpb.h (ADC・電流アンプ・過電流・タコ・NTC)
├── lib/               機能ライブラリ (アーカイブにして, スケッチが使った物だけリンク)
│   └── mpbfun.h       これ 1 つを include すれば全部使える
├── app_template/      自分のスケッチの出発点 (src/sketch.c)
├── examples/          サンプル 9 本 (各ディレクトリで make / make upload)
├── tests/             ホスト (PC) で動く単体テスト
├── bootloader/        USB/UART ブートローダ (最初の 1 回だけ WCH-LinkE で書く)
└── sdk/               WCH 公式 SDK (./sdk/fetch_sdk.sh で取得)
```

## ビルドと書き込み

```bash
# ツール (Ubuntu の例)
sudo apt install gcc-riscv64-unknown-elf picolibc-riscv64-unknown-elf
cd firmware && ./sdk/fetch_sdk.sh

make                              # ブートローダ + テンプレート + 全サンプル
make test                         # 単体テスト (実機不要)
make -C examples/dc_motor upload  # サンプルを USB-C で書き込む
make -C app_template POWER_STAGE=B upload   # 子基板 B (24V 系) 用
```

- 自分のスケッチは `app_template/` をコピーして `src/sketch.c` を書き換えます。`Makefile` は 2 行です。

  ```make
  TARGET := app
  include ../../common/app.mk        # ディレクトリの深さに合わせる
  ```
- `src/` に置いた `.c` は全部リンクされます。`EXTRA_CFLAGS += -DMPB_UART_BOOT=0` などで設定を変えられます。
- コンパイラ: 汎用 GCC (`riscv64-unknown-elf-`, 既定) / xPack・MounRiver GCC (`make PREFIX=riscv-none-elf- LIBC_SPECS="--specs=nano.specs --specs=nosys.specs"`) /
  WCH GCC の高速割込み (`make IRQ=wch PREFIX=riscv-wch-elf-`)。
- MounRiver Studio で使う場合は「Makefile プロジェクト」として `firmware/` を開き, ビルドコマンドに上の `make` を指定します
  (SDK のサンプルと同じ WCH GCC で, 割込みは `IRQ=wch`)。IDE 独自のプロジェクト生成は不要です。

## スケッチの書き方

```c
#include "mpbfun.h"

void setup(void)
{
    Mpb_Time_Init();                 /* µs / ms の時計 (TIM3) — 最初に呼ぶ */
    Mpb_Log_Init(0);                 /* UART ログ (J2-3, 460800bps) */
    ...
}

void loop(void)
{
    Mpb_Dc_Task();                   /* 使うモジュールの *_Task() を毎回呼ぶ */
    MPB_EVERY_MS(t, 200) { MPB_LOGI("I %d mA", Mpb_Dc_Current_mA(0)); }
}
```

- **loop() を止めないこと**。どの関数も待たずに戻り, 時間のかかる処理は `*_Task()` が少しずつ進めます
  (USB-PD の処理も 1ms 周期で回す必要があります)。
- 周期処理は `MPB_EVERY_MS(変数名, ms) { … }`。時刻は `Mpb_Millis()` / `Mpb_Micros()`。
- 例外として短い待ちが 2 つあります: ADC の単発変換 (約 4µs) と, WS2812 の送信 (LED 1 個 30µs, 送信中は割込み停止)。

## ライブラリ一覧

| ヘッダ | 内容 | 主な関数 |
|---|---|---|
| `mpb.h` (core) | 時間, ADC, VBUS, 電流アンプ, 過電流, ホール / BEMF, タコ (QII), NTC, USB-PD | `Mpb_Millis` `Mpb_Vbus_mV` `Mpb_Ocp_*` `Mpb_Tach_PeriodUs` `Mpb_Ntc_DeciCelsius` `Mpb_PD_*` |
| `mpb_bridge.h` | 4 本のハーフブリッジ: 中心揃えの相補 PWM + デッドタイム (TIM1 と TIM2 を同期), ゲート電源 VDD8 の自動選択, **PWM の山で IA/IB を同時に取り込む電流計測**, ローサイドだけの PWM | `Mpb_Bridge_Init` `Mpb_Bridge_Leg` `Mpb_Bridge_LegLow` `Mpb_Bridge_CurrentInit` `Mpb_Bridge_Current_mA` |
| `mpb_dc.h` | DC モーター ×2: 正転 / 逆転, duty (加減速付き) または **電流制御 (PI)**, 電流制限, 短絡ブレーキ, **Kv [rpm/V] からの回転数の概算** | `Mpb_Dc_SetDuty` `Mpb_Dc_SetCurrent` `Mpb_Dc_Rpm` |
| `mpb_stepper.h` | 2 相バイポーラ: フル〜**1/128 マイクロステップ** (sin 表はフラッシュ 258 バイト), 正転 / 逆転, 台形加減速, 位置決め, 保持電流, **ソフトウェア タコ** | `Mpb_Stepper_SetRpm` `Mpb_Stepper_MoveTo` `Mpb_Stepper_Rpm` |
| `mpb_bldc.h` | 3 相ブラシレス 6 ステップ: **ホールセンサ** (エッジで転流 + 周期でタコ) / **センサなしのオープンループ** (V/f), 正転 / 逆転, 電流制限, 外部タコ (TACH_IN) | `Mpb_Bldc_SetDuty` `Mpb_Bldc_SetRpm` `Mpb_Bldc_Rpm` `Mpb_Bldc_TachRpm` |
| `mpb_led.h` + `mpb_cie.h` | パワー段 (MOSFET) につないだ単色 LED の **CIE 1931 L*** 調光, フェード, 呼吸 | `Mpb_Led_Fade` `Mpb_Led_Breathe` `Mpb_Cie` |
| `mpb_ws2812.h` | WS2812B / SK6812 (RGB/RGBW), HSV, L* での減光, 変化したときだけ送信 | `Mpb_Ws2812_Hsv` `Mpb_Ws2812_Show` |
| `mpb_encoder.h` | ロータリーエンコーダ (EXTI, 4 逓倍, チャタリング打ち消し) + ボタン (デバウンス, 長押し) | `Mpb_Enc_Delta` `Mpb_Enc_Pressed` |
| `mpb_i2c.h` | I2C マスタ (割込みなしのステートマシン, タイムアウトとバス復旧) | `Mpb_I2c_Start` `Mpb_I2c_Done` |
| `mpb_i2c_slave.h` | I2C スレーブ (レジスタマップ, 書き込み範囲の通知) | `Mpb_I2cSlave_Init` `Mpb_I2cSlave_Written` |
| `mpb_env.h` | 環境センサ: **SHT3x / AHT20 / BMP280・BME280 / S-5851A** (TinyWetherMemo と同じ種類) | `Mpb_Env_Init` `Mpb_Env_Task` |
| `mpb_log.h` | UART ログ (リングバッファ + 送信割込み), 整数の printf, 小数の表示 | `MPB_LOGI` `Mpb_Log_Printf` `Mpb_Log_Fixed` |

## サンプル

| ディレクトリ | 内容 | 配線 / ジャンパ |
|---|---|---|
| `examples/dc_motor` | DC モーターの正転 / 逆転。エンコーダで **回転数の目安 (Kv から逆算)** か **電流** を設定, 長押しで切り替え | OUT0–OUT1, JP7/JP5 = 1-2, エンコーダ = HALL_A/HALL_C (JP2/JP4 = 2-3) |
| `examples/stepper` | ステッピング 1/16 マイクロステップ。エンコーダで回転数 (±), 長押しで 1 回転の位置決め往復, 相電流とタコをログ | A = OUT0/OUT1, B = OUT2/OUT3, JP5 = 2-3 |
| `examples/bldc_hall` | 3 相 (ホール付き)。ボタンで duty と向きを切り替え, ホール周期と TACH_IN の 2 通りのタコ | U/V/W = OUT0〜2, JP2〜4 = 2-3 |
| `examples/bldc_open` | 3 相 (センサなし)。エンコーダで回転数 (±), 転流周期からのソフトウェア タコ | U/V/W = OUT0〜2 |
| `examples/i2c_sensors` | I2C マスタ。SHT3x / AHT20 / BMx280 / S-5851A を同じバスで読み, UART に出す | SDA = J2-19, SCL = J2-18, プルアップ R114/R115 |
| `examples/i2c_slave` | I2C スレーブ (0x30)。VBUS・温度・時刻を読み出し, LED の点灯方法を書き込める | 同上 |
| `examples/uart_log` | UART ログ。VBUS・USB 電圧・NTC 温度・PD の状態を 1 秒ごと | TX = J2-3 |
| `examples/ws2812` | WS2812 8 個: 虹色 / 呼吸 (L*), エンコーダで明るさ | DIN = J2-2 (PC2) |
| `examples/led_cie` | LED テープを OUT0 のローサイドで CIE 調光 (2kHz, 1/18000), フェードと呼吸 | LED + = VBUS, − = OUT0 |

## 資源の割り当て (同時に使えない組み合わせに注意)

| 資源 | 使い道 |
|---|---|
| TIM1 | HB0〜HB2 の PWM, CH4 = ADC 注入変換の起動 (PWM の山) |
| TIM2 | HB2/HB3 の PWM (`use_tim2 = 1`: ステッピング, DC 2ch) **または** ホールセンサ I/F (`mpb_bldc` のホール) |
| TIM3 | 時計 (1µs) + TACH_IN の周期計測 (QII1 → CH1) |
| ADC | 通常変換 = `Mpb_Adc_Read` (VBUS・NTC など), 注入変換 = IA/IB (PWM 同期, `ADC_IRQHandler`) |
| USART1 | ログの送信 (PC1) + 書き込み要求の受信 (PC2) |
| I2C1 | マスタ **または** スレーブ (PA14 SDA / PA15 SCL) |
| EXTI | エンコーダ (既定 PA5/PA6) |
| SysTick | WS2812 の送信中だけ HCLK で計時 (SDK の `Delay_*` も使う) |

| 端子 (モジュール) | 使い道 |
|---|---|
| PA5 / PA7 / PA6 (J1-14〜16 HALL_A/B/C, JP2〜4) | ホールセンサ, BEMF (1-2), エンコーダ (2-3 にしてプルアップと RC を使う) |
| PA14 / PA15 (J2-19 / J2-18) | I2C。**PA15 は TIM1 の BKIN 既定端子**なので, モーターと I2C を併用するときは `hw_break = 0` (既定) |
| PC1 / PC2 (J2-3 / J2-2) | UART TX / RX。WS2812 は PC2 を使う (UART からの書き込み要求は切る) |
| PC4 (J1-4) | 状態 LED + USER ボタン (共用, オープンドレイン) |
| PA12 (J1-20 TACH_IN) | 外部タコ / FG (JP8 = 1-2), またはバス電流のリップル (2-3) |

## 電流の向きと計測

- シャントは各レッグのローサイドの帰路 (ソース → シャント → GND) にあり, アンプは **ソース → GND の向きを正** に測ります。
- PWM は中心揃えで, 山 (カウンタ = ARR) では全レッグのローサイドが ON です。ここで IA/IB を取り込むので,
  PWM している相も含めて相電流が得られます (デューティ上限 `max_duty`, 既定 90% はこの時間とブートストラップのため)。
- DC モーター (HB0/HB1): 正転の電流 = (IB − IA) / 2。ステッピング: コイル電流 = −IA / −IB。3 相: ローサイド ON の相の電流。
- 起動直後に全レッグ開放で 256 回平均してオフセットを取ります (`Mpb_Bridge_CurrentReady()` が 1 になるまで約 13ms)。

## 保護

- `Mpb_Ocp_BusCmp3_Init()` (バス 25.4A) と `Mpb_Ocp_Cmp2_Init()` (OPA3 + DAC, レッグごとの制限) がコンパレータで過電流を検出し,
  割込みで全レッグのゲートを Low に固定します (`Mpb_Bridge_Faulted()`, 解除は `Mpb_Bridge_ClearFault()`)。
- `hw_break = 1` にすると TIM1 のハードのブレーキ (BKIN) も使いますが, BKIN の既定端子 PA15 (I2C の SCL) を Low に固定します。
- ゲート駆動電源 VDD8 はリセット時 5V です。`Mpb_Bridge_Init` と各モーターの `*_Task` が VBUS に合わせて 8 / 9 / 10V に上げます
  (VBUS ≥ 12V で 10V)。子基板 B の TKR74F04PB は 10V 駆動が前提です。
- ゲートを駆動する前に VBUS ≥ 8V を確認してください (サンプルは `Mpb_Vbus_mV() >= 8000` まで待ちます)。

## 未実装 / 今後

- 3 相のセンサレス閉ループ (BEMF ゼロクロス)。コンパレータと仮想中性点の設定 (`Mpb_Bemf_*`) はあるが, 転流制御は未実装。
- DC モーターの回転数の実測は, TACH_IN (エンコーダ / FG) か JP8 = 2-3 の電流リップルを `Mpb_Tach_PeriodUs()` で読む。
- 1-Wire (DS18B20)・DHT11 は未対応 (TinyWetherMemo の host 側にはある)。
