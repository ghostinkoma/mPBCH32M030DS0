#!/usr/bin/env python3
"""新しいスケッチ (プロジェクト) を作る。全プロジェクトと同じ雛形 (Makefile + src/config.h + src/sketch.c) になる。

  python3 tools/new_sketch.py ../my_robot                  # 空のスケッチ (LED の点滅とログ)
  python3 tools/new_sketch.py ../my_stepper --from stepper # サンプルをもとにする (examples/<名前>)
  python3 tools/new_sketch.py ../my_app --rtos             # FreeRTOS を使うスケッチ

作ったら:  make -C ../my_robot  /  make -C ../my_robot upload
config.h の共通部分は tools/config_common.h.in が元 (ボード・ライブラリの設定)。
"""
import argparse
import os
import shutil
import sys

FW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SKETCH = """/*
 * {name}
 *
 * 設定 (ピン・定数) は src/config.h。ライブラリは "mpbfun.h" (firmware/README.md)。
 * loop() は止めないこと (delay を使わず, MPB_EVERY_MS や *_Task() で進める)。
 */
#include "config.h"         /* このスケッチの設定 (ピン・定数) */
#include "mpbfun.h"

static void led(uint8_t on)
{{
    GPIO_WriteBit(MPB_LED_PORT, MPB_LED_PIN, on ? MPB_LED_ON : MPB_LED_OFF);
}}

void setup(void)
{{
    GPIO_InitTypeDef g = {{0}};

    Mpb_Time_Init();                     /* µs / ms の時計 — 最初に呼ぶ */
    Mpb_Log_Init(0);                     /* UART ログ (J2-3, 460800bps) */
    RCC_PB2PeriphClockCmd(MPB_LED_RCC, ENABLE);
    g.GPIO_Pin = MPB_LED_PIN;
    g.GPIO_Mode = GPIO_Mode_Out_OD;      /* PC4 は USER ボタンと共用 → オープンドレイン */
    g.GPIO_Speed = GPIO_Speed_30MHz;
    GPIO_Init(MPB_LED_PORT, &g);
    MPB_LOGI("{name}: start");
}}

void loop(void)
{{
    static uint8_t on;

    MPB_EVERY_MS(t_led, CFG_LED_MS)
    {{
        on ^= 1;
        led(on);
    }}
}}
"""

BODY = """#define CFG_LED_MS          500u        /* 状態 LED の点滅 [ms] */
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dir", help="作るディレクトリ")
    ap.add_argument("--from", dest="src", help="もとにするサンプル (examples/ の名前)")
    ap.add_argument("--rtos", action="store_true", help="FreeRTOS を使う (examples/rtos_motor_display と同じ構成)")
    ap.add_argument("--force", action="store_true", help="既にあっても上書きする")
    a = ap.parse_args()

    dst = os.path.abspath(a.dir)
    name = os.path.basename(dst.rstrip("/"))
    if os.path.exists(os.path.join(dst, "src", "sketch.c")) and not a.force:
        sys.exit(f"{dst} には既にスケッチがあります (--force で上書き)")
    src = a.src or ("rtos_motor_display" if a.rtos else None)
    if src:
        sdir = os.path.join(FW, "examples", src)
        if not os.path.isdir(sdir):
            sys.exit(f"examples/{src} がありません: " + ", ".join(sorted(os.listdir(os.path.join(FW, "examples")))))
        shutil.copytree(os.path.join(sdir, "src"), os.path.join(dst, "src"), dirs_exist_ok=True)
        extra = open(os.path.join(sdir, "Makefile"), encoding="utf-8").read().splitlines()
        extra = [l for l in extra if not l.startswith(("TARGET", "include"))]
    else:
        os.makedirs(os.path.join(dst, "src"), exist_ok=True)
        tmpl = open(os.path.join(FW, "tools", "config_common.h.in"), encoding="utf-8").read()
        cfg = tmpl.replace("@NAME@", name).replace("@UART_BOOT@", "1").replace("@BODY@", BODY)
        open(os.path.join(dst, "src", "config.h"), "w", encoding="utf-8").write(cfg)
        open(os.path.join(dst, "src", "sketch.c"), "w", encoding="utf-8").write(SKETCH.format(name=name))
        extra = []
    rel = os.path.relpath(os.path.join(FW, "common", "app.mk"), dst)
    if rel.count("..") > 3:                     # firmware/ の外に作ったときは絶対パス
        rel = os.path.join(FW, "common", "app.mk")
    mk = ["TARGET := app"] + extra + [f"include {rel}"]
    open(os.path.join(dst, "Makefile"), "w", encoding="utf-8").write("\n".join(mk) + "\n")
    print(f"作成: {dst}\n  make -C {a.dir}          ビルド\n  make -C {a.dir} upload   USB-C で書き込み")


if __name__ == "__main__":
    main()
