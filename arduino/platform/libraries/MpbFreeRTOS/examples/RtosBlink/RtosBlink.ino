/*
 * RtosBlink — FreeRTOS の最小例 (「ツール → RTOS → FreeRTOS」を選んでから書き込む)
 *
 *   blink タスク : 状態 LED (PC4) を 2Hz で点滅
 *   vbus  タスク : 100ms ごとに VBUS を測ってキューへ
 *   loop()       : それ自体が優先度 1 のタスク。キューから受け取ってログに出す
 * delay() は vTaskDelay() になり, 待っている間は他のタスクが動く。
 * Serial (UART ログ) は 1 つのタスク (ここでは loop) からだけ使う。
 */

static QueueHandle_t q;

static void blink_task(void *arg)
{
    pinMode(LED_BUILTIN, OUTPUT_OPEN_DRAIN);
    for (;;) {
        digitalToggle(LED_BUILTIN);
        delay(250);
    }
}

static void vbus_task(void *arg)
{
    TickType_t wake = xTaskGetTickCount();
    for (;;) {
        uint32_t mv = Mpb_Vbus_mV();
        xQueueSend(q, &mv, 0);
        vTaskDelayUntil(&wake, pdMS_TO_TICKS(100));
    }
}

void setup()
{
    Serial.begin();
    q = xQueueCreate(8, sizeof(uint32_t));
    xTaskCreate(blink_task, "blink", 128, NULL, 2, NULL);   // スタックは語 (4 バイト) 単位
    xTaskCreate(vbus_task, "vbus", 160, NULL, 3, NULL);
    Serial.println("RtosBlink: tasks created");
}   // setup() から戻るとスケジューラが始まり, loop() もタスクとして動き出す

void loop()
{
    uint32_t mv;
    if (xQueueReceive(q, &mv, pdMS_TO_TICKS(1000)) == pdTRUE) {
        static uint32_t n;
        if (++n % 10 == 0) {
            Serial.printf("vbus %u mV  heap free %u  loop stack free %u\r\n", (unsigned)mv,
                          (unsigned)xPortGetFreeHeapSize(), (unsigned)uxTaskGetStackHighWaterMark(NULL));
        }
    }
}
