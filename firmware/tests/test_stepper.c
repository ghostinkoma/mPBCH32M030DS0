/*
 * ホストテスト: ステッピングの台形加減速・位置決め (PWM 20kHz の割込みと 1ms の Task を模擬)
 */
#include <stdio.h>
#include "mpb.h"
#include "mpb_stepper.h"

static uint32_t g_ms;
uint32_t Mpb_Millis(void) { return g_ms; }
uint32_t Mpb_Micros(void) { return g_ms * 1000u; }
uint32_t Mpb_Vbus_mV(void) { return 12000; }
static Mpb_BridgeHook g_hook;
static int16_t g_leg[4];
void Mpb_Bridge_AddHook(Mpb_BridgeHook fn) { g_hook = fn; }
static int32_t g_q[4];
void Mpb_Bridge_Leg(uint8_t leg, int16_t d) { g_leg[leg] = d; }
void Mpb_Bridge_LegQ16(uint8_t leg, uint16_t q) { if (q > 58982u) q = 58982u; g_q[leg] = q; }
uint32_t Mpb_Bridge_PwmHz(void) { return 20000; }
uint16_t Mpb_Bridge_MaxDuty(void) { return 900; }
int32_t Mpb_Bridge_Current_mA(uint8_t ch) { (void)ch; return 0; }
uint16_t Mpb_Bridge_Vdd8Auto(void) { return 10000; }

#include "../lib/mpb_stepper.c"

static int fails;
#define CHECK(c, ...) do { if (!(c)) { fails++; printf("FAIL %d: ", __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

/* ms ミリ秒進める。戻り値: 最高速度 */
static int32_t run(uint32_t ms, int32_t lo, int32_t hi, int *out_of_range)
{
    int32_t vmax = 0;
    for (uint32_t k = 0; k < ms; k++)
    {
        for (int t = 0; t < 20; t++) g_hook(0, 0);
        g_ms++;
        Mpb_Stepper_Task();
        int32_t v = Mpb_Stepper_Speed(); if (v < 0) v = -v; if (v > vmax) vmax = v;
        int32_t p = Mpb_Stepper_Position();
        if (p < lo || p > hi) (*out_of_range)++;
    }
    return vmax;
}

int main(void)
{
    Mpb_StepperCfg c = {200, 16, 800, 2800, 40000, 40, 500};
    int oor = 0;
    int32_t vmax;

    Mpb_Stepper_Init(&c);
    Mpb_Stepper_Enable(1);
    /* 振幅: 800mA × 2.8Ω / 12V = 186.7‰ → ×65.535 = 12233 */
    CHECK(s_amp == 12233, "amp %u", s_amp);

    Mpb_Stepper_Move(3200, 8000);
    vmax = run(3000, 0, 3200, &oor);
    CHECK(Mpb_Stepper_Position() == 3200, "pos %d", Mpb_Stepper_Position());
    CHECK(!Mpb_Stepper_Busy(), "still busy");
    CHECK(vmax <= 8000 && vmax >= 7500, "vmax %d", vmax);
    CHECK(oor == 0, "overshoot %d", oor);

    Mpb_Stepper_MoveTo(0, 8000);
    vmax = run(3000, 0, 3200, &oor);
    CHECK(Mpb_Stepper_Position() == 0 && oor == 0, "back pos %d oor %d", Mpb_Stepper_Position(), oor);

    /* 短い移動 (最高速まで届かない三角形) */
    Mpb_Stepper_Move(-50, 8000);
    run(1000, -50, 0, &oor);
    CHECK(Mpb_Stepper_Position() == -50 && oor == 0, "short pos %d oor %d", Mpb_Stepper_Position(), oor);

    /* 連続回転 → 停止: 減速して止まり, 位置が動かなくなる */
    Mpb_Stepper_SetRpm(60);                    /* 60rpm = 3200 µstep/s */
    run(500, -100000, 100000, &oor);
    CHECK(Mpb_Stepper_Speed() == 3200, "speed %d", Mpb_Stepper_Speed());
    CHECK(Mpb_Stepper_Rpm() == 60, "rpm %d", Mpb_Stepper_Rpm());
    Mpb_Stepper_Stop();
    run(200, -100000, 100000, &oor);
    int32_t p = Mpb_Stepper_Position();
    run(100, -100000, 100000, &oor);
    CHECK(Mpb_Stepper_Speed() == 0 && Mpb_Stepper_Position() == p, "stop %d", Mpb_Stepper_Speed());
    /* 保持電流: 500ms 後に 40% */
    run(600, -100000, 100000, &oor);
    CHECK(s_amp == 4893, "hold amp %u", s_amp);

    /* 1/16: 1 フルステップ (16 µstep) で電気角 90° 進む = A 相と B 相の役割が入れ替わる */
    Mpb_Stepper_SetPosition(0);
    Mpb_Stepper_SetCurrent(800);
    run(600, -100000, 100000, &oor);
    s_dirty = 1; g_hook(0, 0);
    int a0 = g_q[0] - g_q[1], b0 = g_q[2] - g_q[3];
    Mpb_Stepper_SetPosition(16);
    s_dirty = 1; g_hook(0, 0);
    int a1 = g_q[0] - g_q[1], b1 = g_q[2] - g_q[3];
    CHECK(a0 == 0 && b0 > 0 && a1 == b0 && b1 == 0, "phase a0 %d b0 %d a1 %d b1 %d", a0, b0, a1, b1);

    /* ---- 1/128 ---- */
    {
        Mpb_StepperCfg c128 = {200, 128, 800, 2800, 400000, 40, 500};
        Mpb_Stepper_Init(&c128);
        Mpb_Stepper_Enable(1);
        run(10, -1, 1, &oor);
        /* 電気角 1 周 (4 フルステップ = 512 µstep) で sin が 1 周: 0, 90, 180, 270° の値 */
        static const int32_t pos[4] = {0, 128, 256, 384};
        int32_t av[4], bv[4];
        for (int k = 0; k < 4; k++)
        {
            Mpb_Stepper_SetPosition(pos[k]);
            s_dirty = 1; g_hook(0, 0);
            av[k] = g_q[0] - g_q[1]; bv[k] = g_q[2] - g_q[3];
        }
        int32_t A = (int32_t)(((uint32_t)s_amp * 65535u) >> 16);
        CHECK(s_amp == 12233, "amp128 %u", s_amp);
        CHECK(av[0] == 0 && av[1] == A && av[2] == 0 && av[3] == -A, "a %d %d %d %d", av[0], av[1], av[2], av[3]);
        CHECK(bv[0] == A && bv[1] == 0 && bv[2] == -A && bv[3] == 0, "b %d %d %d %d", bv[0], bv[1], bv[2], bv[3]);
        /* 1 マイクロステップごとに単調 (0〜90°) で, 振幅 (a²+b²) がほぼ一定 */
        int32_t prev = -1, mono = 1, rmin = 1 << 30, rmax = 0;
        for (int32_t p = 0; p <= 128; p++)
        {
            Mpb_Stepper_SetPosition(p);
            s_dirty = 1; g_hook(0, 0);
            int32_t a = g_q[0] - g_q[1], b = g_q[2] - g_q[3];
            if (a < prev) mono = 0;
            prev = a;
            int32_t r2 = (int32_t)(((int64_t)a * a + (int64_t)b * b) >> 10);
            if (r2 < rmin) rmin = r2;
            if (r2 > rmax) rmax = r2;
        }
        CHECK(mono, "not monotonic");
        CHECK(rmax - rmin <= rmax / 500, "amplitude ripple %d..%d", rmin, rmax);
        /* 速い移動: 1 周期に複数ステップ進んでも目標で止まる (1 回転 = 25600 µstep, 最高 2 回転/s) */
        Mpb_Stepper_SetPosition(0);
        oor = 0;
        Mpb_Stepper_Move(25600, 51200);
        vmax = run(3000, 0, 25600, &oor);
        CHECK(Mpb_Stepper_Position() == 25600 && oor == 0, "fast pos %d oor %d", Mpb_Stepper_Position(), oor);
        CHECK(vmax == 51200, "fast vmax %d", vmax);
        CHECK(Mpb_Stepper_Rpm() == 0, "rpm after stop");
        /* 上限: 1 PWM 周期に 1 フルステップ (20kHz × 128 = 2.56M µstep/s) */
        Mpb_Stepper_SetSpeed(10000000);
        set_rate(10000000);
        CHECK(Mpb_Stepper_Speed() == 2560000, "cap %d", Mpb_Stepper_Speed());
        Mpb_Stepper_SetSpeed(0); set_rate(0);
    }

    printf(fails ? "stepper: %d FAILED\n" : "stepper: all tests passed\n", fails);
    return fails != 0;
}
