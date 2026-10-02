/*
 * FreeRTOSConfig.h — mPBCH32M030DS0 の Arduino 用の既定値
 * スケッチに FreeRTOSConfig.h タブを置くとそちらが使われる。個別の値は config.h タブで #define すれば変わる。
 * ポートは WCH SDK 同梱の FreeRTOS V10.4.6 (RISC-V): SysTick = ティック, ソフトウェア割込み = タスク切替。
 */
#ifndef FREERTOS_CONFIG_H
#define FREERTOS_CONFIG_H

#include "debug.h"     /* SystemCoreClock, NVIC, SysTick */
void Mpb_Gates_Off(void);   /* core/mpb_wdt.c: 全 FET OFF */

#ifndef MPB_RTOS_HEAP
#define MPB_RTOS_HEAP 4096u                    /* xTaskCreate / キュー などの動的確保の領域 [バイト] */
#endif

#define configMTIME_BASE_ADDRESS                0
#define configMTIMECMP_BASE_ADDRESS             0
#define configUSE_PREEMPTION                    1
#define configCPU_CLOCK_HZ                      SystemCoreClock
#ifndef configTICK_RATE_HZ
#define configTICK_RATE_HZ                      ((TickType_t)1000)
#endif
#ifndef configMAX_PRIORITIES
#define configMAX_PRIORITIES                    8
#endif
#ifndef configMINIMAL_STACK_SIZE
#define configMINIMAL_STACK_SIZE                ((unsigned short)96)   /* アイドルタスク [語] */
#endif
#define configMAX_TASK_NAME_LEN                 8
#define configUSE_16_BIT_TICKS                  0
#define configIDLE_SHOULD_YIELD                 1
#ifndef configUSE_IDLE_HOOK
#define configUSE_IDLE_HOOK                     1      /* アイドル中にウォッチドッグへ給餌 (mpb_freertos.c) */
#endif
#define configUSE_TICK_HOOK                     0
#define configUSE_MUTEXES                       1
#define configUSE_RECURSIVE_MUTEXES             1
#define configUSE_COUNTING_SEMAPHORES           1
#define configUSE_TASK_NOTIFICATIONS            1
#define configQUEUE_REGISTRY_SIZE               0
#define configUSE_TRACE_FACILITY                0
#define configGENERATE_RUN_TIME_STATS           0
#define configUSE_PORT_OPTIMISED_TASK_SELECTION 0
#define configUSE_CO_ROUTINES                   0
#ifndef configUSE_TIMERS
#define configUSE_TIMERS                        0      /* 1 にするとソフトウェアタイマー (タスク 1 本分の RAM を使う) */
#endif
#define configTIMER_TASK_PRIORITY               (configMAX_PRIORITIES - 1)
#define configTIMER_QUEUE_LENGTH                4
#define configTIMER_TASK_STACK_DEPTH            128
#ifndef configCHECK_FOR_STACK_OVERFLOW
#define configCHECK_FOR_STACK_OVERFLOW          2
#endif
#define configUSE_MALLOC_FAILED_HOOK            1

#define configSUPPORT_STATIC_ALLOCATION         1
#ifndef configSUPPORT_DYNAMIC_ALLOCATION
#define configSUPPORT_DYNAMIC_ALLOCATION        1
#endif
#define configTOTAL_HEAP_SIZE                   ((size_t)MPB_RTOS_HEAP)

#define INCLUDE_vTaskDelay                      1
#define INCLUDE_xTaskDelayUntil                 1
#define INCLUDE_vTaskDelete                     1
#define INCLUDE_vTaskSuspend                    1
#define INCLUDE_vTaskPrioritySet                1
#define INCLUDE_uxTaskPriorityGet               1
#define INCLUDE_uxTaskGetStackHighWaterMark     1
#define INCLUDE_xTaskGetSchedulerState          1
#define INCLUDE_xTaskGetCurrentTaskHandle       1
#define INCLUDE_eTaskGetState                   1

/* 失敗したら全 FET OFF で止まる (割込みが止まるので約 29ms 後にウォッチドッグがリセット) */
#define configASSERT(x) do { if ((x) == 0) { taskDISABLE_INTERRUPTS(); Mpb_Gates_Off(); for (;;) {} } } while (0)

#endif /* FREERTOS_CONFIG_H */
