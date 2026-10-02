/*
 * mpb_freertos.c — Arduino の setup()/loop() と FreeRTOS をつなぐ部分
 * Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
 */
#include "mpb_freertos.h"
#include "mpb.h"

void setup(void);
void loop(void);

static TaskHandle_t s_loop;
TaskHandle_t Mpb_Rtos_LoopTask(void) { return s_loop; }

static void loop_task(void *arg)
{
    (void)arg;
    for (;;)
    {
        loop();
        Mpb_Core_Service();               /* USB / UART からの書き込み要求 */
    }
}

/* core/main.c が setup() の後に呼ぶ: loop() をタスクにしてスケジューラを開始 (戻らない) */
void Mpb_Rtos_AfterSetup(void)
{
#if configSUPPORT_STATIC_ALLOCATION
    static StaticTask_t tcb;
    static StackType_t stack[MPB_LOOP_STACK];
    s_loop = xTaskCreateStatic(loop_task, "loop", MPB_LOOP_STACK, NULL, MPB_LOOP_PRIO, stack, &tcb);
#else
    xTaskCreate(loop_task, "loop", MPB_LOOP_STACK, NULL, MPB_LOOP_PRIO, &s_loop);
#endif
    vTaskStartScheduler();
    for (;;) {}                           /* ヒープ不足でアイドルタスクを作れなかったときだけ来る */
}

#if configSUPPORT_STATIC_ALLOCATION
__attribute__((weak)) void vApplicationGetIdleTaskMemory(StaticTask_t **tcb, StackType_t **stack, uint32_t *words)
{
    static StaticTask_t idle_tcb;
    static StackType_t idle_stack[configMINIMAL_STACK_SIZE];
    *tcb = &idle_tcb;
    *stack = idle_stack;
    *words = configMINIMAL_STACK_SIZE;
}
#if configUSE_TIMERS
__attribute__((weak)) void vApplicationGetTimerTaskMemory(StaticTask_t **tcb, StackType_t **stack, uint32_t *words)
{
    static StaticTask_t tmr_tcb;
    static StackType_t tmr_stack[configTIMER_TASK_STACK_DEPTH];
    *tcb = &tmr_tcb;
    *stack = tmr_stack;
    *words = configTIMER_TASK_STACK_DEPTH;
}
#endif
#endif

#if configCHECK_FOR_STACK_OVERFLOW
/* スタックあふれ: 割込みを止めて止まる (状態 LED PC4 を点灯)。上書きしたいときはスケッチで同名の関数を定義する */
__attribute__((weak)) void vApplicationStackOverflowHook(TaskHandle_t t, char *name)
{
    (void)t;
    (void)name;
    taskDISABLE_INTERRUPTS();
    GPIOC->BCR = GPIO_Pin_4;
    for (;;) {}
}
#endif

#if configUSE_MALLOC_FAILED_HOOK
__attribute__((weak)) void vApplicationMallocFailedHook(void)
{
    taskDISABLE_INTERRUPTS();
    GPIOC->BCR = GPIO_Pin_4;
    for (;;) {}
}
#endif
