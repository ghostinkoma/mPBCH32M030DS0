/*
 * サンプル: FreeRTOS — ステッピングモーターを回しながら, 状態を 3 種類の表示器に出す
 *
 *   OLED (SSD1306 / SH1106, I2C)          … 回転数・位置・VBUS・電流・温度・稼働時間 + 回転数のバー
 *   HT16K33 8×8 ×4 (I2C, 0x70〜0x73)      … 回転数 (数字)
 *   TM1640 2 色 8×8 ×4 (SCLK + DIN ×4)    … 状態を流れる文字で (正常 = 緑, 停止 = 橙, 故障 = 赤)
 *
 * タスク (優先度の高い順):
 *   motor   (4) 1ms ごと: USB-PD, ステッピングの制御, 自動運転の rpm 切替, 過電流の解除
 *   tm1640  (3) 10ms ごと: 文字を流して送る (1 画面 ≈ 0.7ms, 4 枚を同時に送る)
 *   monitor (2) 100ms ごと: 書き込み要求の処理, 温度・電流の集計, 1 秒ごとのログ, 表示の文字を作る
 *   i2c     (1) OLED と HT16K33 (同じバス) を送り続ける。送るものが無ければ 20ms 休む
 * タスク間は g_st (状態) を共有する。32 ビットの読み書きは 1 命令なので, 値ごとの食い違いは起きない。
 *
 * 配線: モーターは examples/stepper と同じ (A 相 = OUT0/OUT1, B 相 = OUT2/OUT3, JP7 = 1-2, JP5 = 2-3)。
 *       I2C: SDA = PA14 (J2-19), SCL = PA15 (J2-18), 4.7k プルアップ。表示器の電源は 3.3V か 5V (モジュール次第)。
 *       TM1640: SCLK = PA5 (J1-14), DIN0〜3 = PA6 (J1-16) / PA7 / PC2 (J2-2) / PC4 (J1-4)。JP2〜JP4 = 2-3。
 * 書き込み: PC2 を使うので UART からの書き込みは無効 (USB-C で make upload)。
 */
#include "config.h"
#include <string.h>
#include "mpbfun.h"
#include "FreeRTOS.h"
#include "task.h"

/* ---- タスク間で共有する状態 ---- */
typedef struct {
    volatile int32_t  rpm_x10, target_rpm, pos;
    volatile int32_t  ia_mA, ib_mA, temp_c10;
    volatile uint32_t vbus_mV;
    volatile uint8_t  ready, fault;
} Status;
static Status g_st;

static char s_marquee[MPB_MATRIX_TEXT];      /* TM1640 に流す文字 (monitor が作る) */
static volatile uint8_t s_marquee_seq, s_marquee_color = MPB_MX_ORANGE;

static Mpb_Matrix s_ht, s_tm;

/* ---- 静的に確保したタスクのスタック ---- */
#define TASK(name, words) static StackType_t name##_stack[words]; static StaticTask_t name##_tcb
TASK(motor, CFG_STACK_MOTOR);
TASK(i2c, CFG_STACK_I2C);
TASK(tm, CFG_STACK_TM1640);
TASK(mon, CFG_STACK_MONITOR);
static TaskHandle_t s_task[4];

/* ======================================================================== motor (4) ===== */
static void motor_task(void *arg)
{
    static const int16_t profile[] = CFG_PROFILE;
    TickType_t wake = xTaskGetTickCount();
    uint32_t t_step = 0;
    uint8_t idx = 0;

    for (;;)
    {
        vTaskDelayUntil(&wake, 1);
        Mpb_PD_Task();
        Mpb_Stepper_Task();

        if (!g_st.ready)
        {
            if (Mpb_Bridge_CurrentReady() && Mpb_Vbus_mV() >= CFG_VBUS_MIN_MV)
            {
                g_st.ready = 1;
                Mpb_Stepper_Enable(1);          /* 電流アンプの校正が済んでから励磁 */
                t_step = Mpb_Millis() - CFG_PROFILE_MS;
            }
            continue;
        }
        if (Mpb_Bridge_Faulted())
        {
            /* 過電流: 出力は止まっている。3 秒後に解除して最初からやり直す */
            if (!g_st.fault)
            {
                g_st.fault = 1;
                t_step = Mpb_Millis();
            }
            else if (Mpb_Millis() - t_step > 3000u)
            {
                g_st.fault = 0;
                Mpb_Bridge_ClearFault();
                Mpb_Stepper_SetSpeed(0);
                Mpb_Stepper_Enable(1);
                idx = 0;
                t_step = Mpb_Millis() - CFG_PROFILE_MS;
            }
            continue;
        }
        if (Mpb_Millis() - t_step >= CFG_PROFILE_MS)
        {
            t_step += CFG_PROFILE_MS;
            g_st.target_rpm = profile[idx];
            Mpb_Stepper_SetRpm(profile[idx]);
            idx = (uint8_t)((idx + 1u) % (sizeof(profile) / sizeof(profile[0])));
        }
        g_st.rpm_x10 = Mpb_Stepper_RpmX10();
        g_st.pos = Mpb_Stepper_Position();
    }
}

/* ========================================================================= i2c (1) ===== */
static const char *fixed(int32_t v, uint8_t dec, char *buf)   /* Mpb_Log_Fixed は静的バッファ 1 つなのでタスクごとに写す */
{
    const char *s = Mpb_Log_Fixed(v, dec);
    strcpy(buf, s);
    return buf;
}

static void i2c_task(void *arg)
{
    char a[16], b[16];
    int32_t shown_rpm = INT32_MIN;
    uint32_t t_oled = 0;

    Mpb_I2c_Init(CFG_I2C_HZ);
    Mpb_Oled_Init(CFG_OLED_ADDR, CFG_OLED_HEIGHT, CFG_OLED_TYPE);
    Mpb_Ht16k33_Init(CFG_HT_ADDR, CFG_HT_COUNT, CFG_HT_MAP, &s_ht);
    Mpb_Ht16k33_Brightness(CFG_HT_BRIGHT);
    Mpb_Oled_Printf(0, " mPBCH32M030 FreeRTOS");
    Mpb_Oled_Invert(0, 1);

    for (;;)
    {
        uint8_t busy;

        if (Mpb_Millis() - t_oled >= 100u)              /* OLED の文字を 10 回/秒 作り直す (変わった行だけ送られる) */
        {
            int32_t r = g_st.rpm_x10, ar = r < 0 ? -r : r;
            uint32_t up = Mpb_Millis() / 1000u;
            t_oled = Mpb_Millis();
            taskENTER_CRITICAL();                       /* Mpb_Log_Fixed の静的バッファを他のタスクと取り合わない */
            fixed(r, 1, a);
            taskEXIT_CRITICAL();
            Mpb_Oled_Printf(1, "rpm %7s  tgt %4d", a, (int)g_st.target_rpm);
            Mpb_Oled_Printf(2, "pos %11d", (int)g_st.pos);
            taskENTER_CRITICAL();
            fixed((int32_t)g_st.vbus_mV / 10, 2, a);
            fixed(g_st.temp_c10, 1, b);
            taskEXIT_CRITICAL();
            Mpb_Oled_Printf(3, "VBUS %6sV", a);
            Mpb_Oled_Printf(4, "I A%5dmA B%5dmA", (int)g_st.ia_mA, (int)g_st.ib_mA);
            Mpb_Oled_Printf(5, "T %6s\x7F" "C", g_st.temp_c10 == INT32_MIN ? "---" : b);
            if (g_st.fault)
            {
                Mpb_Oled_Printf(6, "!! OVERCURRENT !!");
            }
            else
            {
                Mpb_Oled_Printf(6, "up %02u:%02u:%02u %s", (unsigned)(up / 3600u), (unsigned)(up / 60u % 60u),
                                (unsigned)(up % 60u), g_st.ready ? "run" : "wait");
            }
            Mpb_Oled_Invert(6, g_st.fault);
            Mpb_Oled_Bar(7, (uint16_t)(ar >= CFG_RPM_MAX * 10 ? 1000 : ar * 100 / CFG_RPM_MAX));

            /* HT16K33: 回転数を右寄せの数字で (4 枚 = 5 文字) */
            if (r / 10 != shown_rpm)
            {
                char s[8];
                shown_rpm = r / 10;
                Mpb_Fmt(s, sizeof(s), "%5d", (int)shown_rpm);
                Mpb_Matrix_Print(&s_ht, (int)s_ht.w - 30, s, MPB_MX_RED);
            }
        }
        busy = Mpb_Oled_Task();
        busy |= Mpb_Ht16k33_Task();
        /* 送信中は休まず回す (優先度が一番低いので他のタスクを邪魔しない)。送り終えたら 20ms 休む */
        if (busy)
        {
            taskYIELD();
        }
        else
        {
            vTaskDelay(pdMS_TO_TICKS(20));
        }
    }
}

/* ====================================================================== tm1640 (3) ===== */
static void tm_task(void *arg)
{
    Mpb_Tm1640Cfg c = {.n = CFG_TM_COUNT, .duty = CFG_TM_DUTY, .half_us = CFG_TM_HALF_US};
    TickType_t wake = xTaskGetTickCount();
    uint8_t seq = 0xFF;

    Mpb_Tm1640_Init(&c, &s_tm);
    for (;;)
    {
        vTaskDelayUntil(&wake, pdMS_TO_TICKS(10));
        if (seq != s_marquee_seq)
        {
            char t[MPB_MATRIX_TEXT];
            taskENTER_CRITICAL();
            seq = s_marquee_seq;
            memcpy(t, s_marquee, sizeof(t));
            taskEXIT_CRITICAL();
            Mpb_Matrix_Marquee(&s_tm, t, s_marquee_color, CFG_SCROLL_MS);   /* 同じ文字なら流れ続ける */
        }
        Mpb_Tm1640_Task();
    }
}

/* ===================================================================== monitor (2) ===== */
static void mon_task(void *arg)
{
    TickType_t wake = xTaskGetTickCount();
    uint32_t t_log = 0, t_text = 0;

    for (;;)
    {
        vTaskDelayUntil(&wake, pdMS_TO_TICKS(100));
        Mpb_Core_Service();                             /* USB からの書き込み要求 (あればリセットしてブートローダへ) */
        g_st.vbus_mV = Mpb_Vbus_mV();
        g_st.temp_c10 = Mpb_Ntc_DeciCelsius();
        g_st.ia_mA = Mpb_Stepper_CoilA_mA();
        g_st.ib_mA = Mpb_Stepper_CoilB_mA();

        if (Mpb_Millis() - t_text >= 3000u)             /* TM1640 の文字は 3 秒ごとに作り直す */
        {
            char t[MPB_MATRIX_TEXT], v[12];
            uint8_t color;
            t_text = Mpb_Millis();
            taskENTER_CRITICAL();
            strcpy(v, Mpb_Log_Fixed((int32_t)g_st.vbus_mV / 100, 1));
            taskEXIT_CRITICAL();
            if (g_st.fault)
            {
                Mpb_Fmt(t, sizeof(t), "OVERCURRENT! restart in 3s   ");
                color = MPB_MX_RED;
            }
            else
            {
                Mpb_Fmt(t, sizeof(t), "%d rpm  %sV  %d\x7F" "C   ", (int)(g_st.rpm_x10 / 10), v,
                        (int)(g_st.temp_c10 / 10));
                color = g_st.target_rpm ? MPB_MX_GREEN : MPB_MX_ORANGE;
            }
            taskENTER_CRITICAL();
            memcpy(s_marquee, t, sizeof(t));
            s_marquee_color = color;
            s_marquee_seq = (uint8_t)(s_marquee_seq + 1u);
            taskEXIT_CRITICAL();
        }
        if (Mpb_Millis() - t_log >= CFG_LOG_MS)
        {
            t_log = Mpb_Millis();
            MPB_LOGI("rpm %s pos %d vbus %u mV  I %d/%d mA  oled %u ht %02x  stack free m%u i%u t%u n%u",
                     Mpb_Log_Fixed(g_st.rpm_x10, 1), (int)g_st.pos, (unsigned)g_st.vbus_mV, (int)g_st.ia_mA,
                     (int)g_st.ib_mA, Mpb_Oled_Ready(), Mpb_Ht16k33_Online(),
                     (unsigned)uxTaskGetStackHighWaterMark(s_task[0]), (unsigned)uxTaskGetStackHighWaterMark(s_task[1]),
                     (unsigned)uxTaskGetStackHighWaterMark(s_task[2]), (unsigned)uxTaskGetStackHighWaterMark(s_task[3]));
        }
    }
}

/* ---- FreeRTOS が求める関数 (静的確保) ---- */
void vApplicationGetIdleTaskMemory(StaticTask_t **tcb, StackType_t **stack, uint32_t *words)
{
    static StaticTask_t idle_tcb;
    static StackType_t idle_stack[configMINIMAL_STACK_SIZE];
    *tcb = &idle_tcb;
    *stack = idle_stack;
    *words = configMINIMAL_STACK_SIZE;
}

void vApplicationStackOverflowHook(TaskHandle_t t, char *name)
{
    Mpb_Bridge_AllFloat();                              /* モーターを止めて止まる (ログは割込みが要るので出せない) */
    taskDISABLE_INTERRUPTS();
    for (;;) {}
}

/* ---- setup: ハードの初期化とタスクの作成。スケジューラを開始したら戻らない (loop は呼ばれない) ---- */
void setup(void)
{
    Mpb_BridgeCfg b = {.pwm_hz = CFG_PWM_HZ, .dead_ns = CFG_DEAD_NS, .max_duty = CFG_MAX_DUTY, .use_tim2 = 1,
                       .hw_break = CFG_HW_BREAK};
    Mpb_StepperCfg st = {.steps_per_rev = CFG_STEPS_PER_REV, .microstep = CFG_MICROSTEP, .current_mA = CFG_COIL_MA,
                         .coil_r_mohm = CFG_COIL_R_MOHM, .accel = CFG_ACCEL, .hold_pct = CFG_HOLD_PCT,
                         .hold_ms = CFG_HOLD_MS};

    Mpb_Time_Init();
    Mpb_Log_Init(0);
    Mpb_PD_Init(NULL);
    Mpb_Ntc_Init();
    Mpb_Bridge_Init(&b);
    Mpb_Bridge_CurrentInit(OPA_ISP_GAIN_16, MPB_ISP_LEG);
    Mpb_Ocp_BusCmp3_Init();
    Mpb_Stepper_Init(&st);
    g_st.temp_c10 = INT32_MIN;
    MPB_LOGI("rtos_motor_display: FreeRTOS %s", tskKERNEL_VERSION_NUMBER);

    s_task[0] = xTaskCreateStatic(motor_task, "motor", CFG_STACK_MOTOR, NULL, 4, motor_stack, &motor_tcb);
    s_task[1] = xTaskCreateStatic(i2c_task, "i2c", CFG_STACK_I2C, NULL, 1, i2c_stack, &i2c_tcb);
    s_task[2] = xTaskCreateStatic(tm_task, "tm1640", CFG_STACK_TM1640, NULL, 3, tm_stack, &tm_tcb);
    s_task[3] = xTaskCreateStatic(mon_task, "monitor", CFG_STACK_MONITOR, NULL, 2, mon_stack, &mon_tcb);
    vTaskStartScheduler();
    for (;;) {}
}

void loop(void) {}
