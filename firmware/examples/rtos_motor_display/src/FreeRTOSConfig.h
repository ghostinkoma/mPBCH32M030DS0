/*
 * FreeRTOSConfig.h — rtos_motor_display 用 (CH32M030: RAM 12KB なので静的確保だけ・ヒープなし)
 * ポートは WCH SDK 同梱の FreeRTOS V10.4.6 (RISC-V): SysTick = ティック, ソフトウェア割込み = タスク切替。
 * 【注意】SysTick を OS が使うので, mpb_ws2812 / mpb_wsrx (SysTick で時間を測る) は RTOS では使えない。
 */
#ifndef FREERTOS_CONFIG_H
#define FREERTOS_CONFIG_H

#include "debug.h"     /* SystemCoreClock, NVIC, SysTick */
void Mpb_Gates_Off(void);   /* core/mpb_wdt.c: 全 FET OFF */

#define configMTIME_BASE_ADDRESS                0
#define configMTIMECMP_BASE_ADDRESS             0
#define configUSE_PREEMPTION                    1
#define configCPU_CLOCK_HZ                      SystemCoreClock    /* SysTick は HCLK で数える (port.c) */
#define configTICK_RATE_HZ                      ((TickType_t)1000)
#define configMAX_PRIORITIES                    6
#define configMINIMAL_STACK_SIZE                ((unsigned short)96)   /* アイドルタスク [語] */
#define configMAX_TASK_NAME_LEN                 8
#define configUSE_16_BIT_TICKS                  0
#define configIDLE_SHOULD_YIELD                 1
#define configUSE_IDLE_HOOK                     0
#define configUSE_TICK_HOOK                     0
#define configUSE_MUTEXES                       1
#define configUSE_RECURSIVE_MUTEXES             0
#define configUSE_COUNTING_SEMAPHORES           0
#define configQUEUE_REGISTRY_SIZE               0
#define configUSE_TRACE_FACILITY                0
#define configGENERATE_RUN_TIME_STATS           0
#define configUSE_PORT_OPTIMISED_TASK_SELECTION 0
#define configUSE_CO_ROUTINES                   0
#define configUSE_TIMERS                        0
#define configUSE_MALLOC_FAILED_HOOK            0
#define configCHECK_FOR_STACK_OVERFLOW          2      /* タスク切替のたびにスタック末尾の印を確かめる */

/* メモリ: すべて静的 (xTaskCreateStatic)。heap_x.c をリンクしない */
#define configSUPPORT_STATIC_ALLOCATION         1
#define configSUPPORT_DYNAMIC_ALLOCATION        0
#define configTOTAL_HEAP_SIZE                   0

#define INCLUDE_vTaskDelay                      1
#define INCLUDE_xTaskDelayUntil                 1
#define INCLUDE_uxTaskGetStackHighWaterMark     1
#define INCLUDE_vTaskSuspend                    0
#define INCLUDE_vTaskDelete                     0
#define INCLUDE_vTaskPrioritySet                0
#define INCLUDE_uxTaskPriorityGet               0
#define INCLUDE_xTaskGetSchedulerState          1

#define configASSERT(x) do { if ((x) == 0) { taskDISABLE_INTERRUPTS(); Mpb_Gates_Off(); for (;;) {} } } while (0)

#endif /* FREERTOS_CONFIG_H */
