# Arduino IDE / arduino-cli で使う (Boards Manager)

## 入れ方

1. Arduino IDE 2 の **ファイル → 基本設定 → 追加のボードマネージャの URL** に次を足す
   ```
   https://raw.githubusercontent.com/ghostinkoma/mPBCH32M030DS0/main/package_mpbch32m030_index.json
   ```
2. **ツール → ボード → ボードマネージャ** で `mPBCH32M030DS0` を検索してインストール。
   コンパイラ (xPack riscv-none-elf-gcc 14.3.0-1) も自動で入る (このリポジトリの Releases にミラーしたもの)。
3. **ツール → ボード → mPBCH32M030DS0 (CH32M030)** を選ぶ。

arduino-cli:
```sh
URL=https://raw.githubusercontent.com/ghostinkoma/mPBCH32M030DS0/main/package_mpbch32m030_index.json
arduino-cli core update-index --additional-urls $URL
arduino-cli core install mpbch32m030:ch32m030 --additional-urls $URL
arduino-cli compile -b mpbch32m030:ch32m030:mpb:stage=A MySketch
arduino-cli upload  -b mpbch32m030:ch32m030:mpb -P mpbusb MySketch     # USB-C で書き込み
```

## ツールメニュー

| メニュー | 選択肢 | 意味 |
|---|---|---|
| Power stage | A (12V) / B (24V) / C | 子基板。VBUS の分圧比が変わる (`MPB_POWER_STAGE`) |
| UART boot request | On / Off | On: UART (PC2) からの書き込み要求も受ける。PC2 を WS2812 入力や TM1640 に使うときは Off |
| Upload method | USB-C / UART | USB-C: ブートローダへ USB で。UART: 選んだシリアルポートへ |

## 書き込み

* **USB-C**: ポートを選ばずに **スケッチ → 書き込み装置を使って書き込む** (書き込み装置 = `mPB USB-C bootloader`)。
  シリアルポートを選んであれば普通の「書き込み」でもよい (USB-C のときポートは使わない)。
* 書き込みは `tools/mpb_upload.py` を使う: **Python 3** と `pip install pyusb pyserial` が必要。
  Linux は `tools/99-mpb.rules` を `/etc/udev/rules.d/` へ, Windows は Zadig で 1A86:55E0 に WinUSB。
* ブートローダ (firmware/bootloader) はあらかじめ WCH-LinkE で書いておく (Arduino の「ブートローダを書き込む」は未対応)。

## スケッチの書き方

* `Arduino.h` は最小限: `pinMode / digitalWrite / digitalRead / millis / micros / delay / Serial (送信のみ) / analogRead(ADC チャンネル)`。
  端子名は `PA0`〜`PC7`, `LED_BUILTIN` (= PC4, Low で点灯, ボタンと共用なので `OUTPUT_OPEN_DRAIN` で)。
* 本体の機能は **mpbfun** ライブラリ (= `firmware/lib` と同じコード)。例は **ファイル → スケッチ例 → mpbfun**
  (`firmware/examples` の 11 例 + Blink)。どれも待たない書き方なので, モーターなどを使うときは `delay()` ではなく
  `MPB_EVERY_MS()` や `millis()` で間隔を測る。
* スケッチに **config.h タブ** を置くと, ライブラリの設定 (`MPB_LOG_BUF` など) とスケッチの `CFG_*` が全ファイルに効く
  (make 版の `src/config.h` と同じ。子基板と UART 書き込みだけはツールメニューで選ぶ)。
* FreeRTOS のサンプル (`rtos_motor_display`) は make 版のみ。

## パッケージの作り方 (保守者向け)

```sh
git tag arduino-v0.1.0 && git push origin arduino-v0.1.0
```
(または GitHub の Actions → arduino-package → Run workflow で版を入力)

`.github/workflows/arduino-package.yml` が次を行う:

1. WCH SDK を取得し `arduino/build_package.py` でコア `mpbch32m030-<版>.tar.bz2` を作る (同じ入力なら同じバイト列)
2. xPack riscv-none-elf-gcc (Linux x64/arm64, macOS x64/arm64, Windows x64) を本家の Releases から取り,
   **SHA-256 を xPack の公開値と照合**して, このリポジトリの Release にミラーする
3. 全サンプルを arduino-cli でビルドして確かめる
4. Release を作り, 索引 `package_mpbch32m030_index.json` を main に置く (前の版も索引に残す)

手元で試すとき: `python3 arduino/build_package.py --version 0.1.0 --out dist --stage-only` で展開した形を作り,
`<スケッチブック>/hardware/mpbch32m030/ch32m030/` に置くと IDE から使える
(コンパイラは `--build-property runtime.tools.xpack-riscv-none-elf-gcc.path=<xPack のディレクトリ>` で指定)。

**リポジトリは公開 (public) にしておくこと** — 非公開だと IDE から索引もアーカイブも取得できない。

## 中身とライセンス

* `cores/mpb`: Arduino.h + `firmware/core` (起動・USB 書き込み・PD) + WCH CH32M030 EVT の SDK ソース
  (WCH の条件: WCH のマイコン用に限り使用可)
* `libraries/mpbfun`: `firmware/lib` (LICENSE: 個人利用は表示のうえ自由, 商用は sinhex.k@gmail.com へ連絡, 無保証)
* TM1640 ドライバとフォントは ghostinkoma/TM1640MatrixChain (CC BY-NC-SA 4.0) から移植
* コンパイラ: xPack GNU RISC-V Embedded GCC (GPL ほか各ライセンス, https://xpack-dev-tools.github.io/riscv-none-elf-gcc-xpack/)
