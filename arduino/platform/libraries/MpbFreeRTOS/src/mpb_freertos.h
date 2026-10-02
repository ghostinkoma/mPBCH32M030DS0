/*
 * mpb_freertos.h — mPBCH32M030DS0 の Arduino 用 FreeRTOS
 *
 * 「ツール → RTOS → FreeRTOS」を選ぶと Arduino.h が自動でこれを読む (スケッチに #include は不要)。
 *   ・setup() の後, loop() は優先度 1 のタスク "loop" として動く (ESP32 の Arduino と同じ形)。
 *     setup() の中で xTaskCreate() / xTaskCreateStatic() したタスクも一緒に動き出す。
 *     setup() の中で自分で vTaskStartScheduler() を呼んでもよい (その場合 loop() は呼ばれない)。
 *   ・delay() は vTaskDelay() になる (他のタスクに CPU を譲る)。
 *   ・設定はスケッチの FreeRTOSConfig.h タブ (無ければ既定: 1kHz ティック, ヒープ 4KB, 静的確保も可)。
 *     既定の値は config.h タブで個別に変えられる: #define MPB_RTOS_HEAP 3072 / #define configUSE_TIMERS 1 など。
 *   ・RAM は 12KB: ヒープ 4KB + loop タスク 1KB + 割込みスタック 768B を使う。
 * 注意:
 *   ・SysTick を OS が使うので, mpb_ws2812 / mpb_wsrx (SysTick で時間を測る) は使えない。
 *   ・mpb のライブラリ (I2C, ログ, 表示器 …) はタスク間で排他しない: 1 つの機能は 1 つのタスクから使う。
 * カーネルと RISC-V ポートは WCH CH32M030 EVT 同梱の FreeRTOS V10.4.6 (MIT ライセンス)。
 * Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
 */
#ifndef MPB_FREERTOS_H
#define MPB_FREERTOS_H

#if !MPB_RTOS
#error "FreeRTOS を使うには「ツール → RTOS → FreeRTOS」を選んでください"
#endif

#ifdef __cplusplus
extern "C" {
#endif
#include "FreeRTOS.h"
#include "task.h"
#include "queue.h"
#include "semphr.h"
#include "event_groups.h"
#if configUSE_TIMERS
#include "timers.h"
#endif

#ifndef MPB_LOOP_STACK
#define MPB_LOOP_STACK  256u     /* loop タスクのスタック [語 = 4 バイト] */
#endif
#ifndef MPB_LOOP_PRIO
#define MPB_LOOP_PRIO   1u
#endif

TaskHandle_t Mpb_Rtos_LoopTask(void);   /* loop タスクのハンドル (スタックの残りを見るときなど) */

#ifdef __cplusplus
}
#endif
#endif /* MPB_FREERTOS_H */
