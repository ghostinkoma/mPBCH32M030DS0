/*
 * test_dc — mpb_dc の停止 (回生 → 短絡 → 保持 → 惰性) をモーターと母線のモデルで確かめる
 *
 * モデル (平均化, 同期整流なので電流は両方向に流れる):
 *   巻線: L di/dt = D·V − R·i − Ke·ω      (D = 符号付き duty。両レッグ開放 = 惰性はダイオード整流)
 *   回転: J dω/dt = Kt·i − b·ω
 *   母線: C dV/dt = I_src − D·i           (電源は流し出すだけで吸い込めない = USB-PD / ベンチ電源)
 * 確かめること: 逆転 (プラギング) しない / VBUS が上限を超えない / 電流が制動電流 + 余裕に収まる /
 *              最後は惰性 (全 FET OFF) / 止まるまでの時間が惰性より十分短い / 回生できる電源なら母線へ戻す
 */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../lib/mpb_dc.c"

/* ---------------- ブリッジのスタブ ---------------- */
static int16_t g_leg[4] = {MPB_LEG_FLOAT, MPB_LEG_FLOAT, MPB_LEG_FLOAT, MPB_LEG_FLOAT};
static double g_i, g_w, g_v;           /* 巻線電流 [A], 角速度 [rad/s], 母線 [V] */
static uint32_t g_ms;

void Mpb_Bridge_Leg(uint8_t leg, int16_t duty) { g_leg[leg] = duty; }
uint16_t Mpb_Bridge_MaxDuty(void) { return 900; }
uint16_t Mpb_Bridge_Vdd8Auto(void) { return 10000; }
uint8_t Mpb_Bridge_Faulted(void) { return 0; }
uint8_t Mpb_Bridge_CurrentReady(void) { return 1; }
int32_t Mpb_Bridge_Current_mA(uint8_t ch) { return ch == 1 ? (int32_t)lround(g_i * 1000) : -(int32_t)lround(g_i * 1000); }
uint32_t Mpb_Bridge_Vbus_mV(void) { return (uint32_t)lround(g_v * 1000); }
uint32_t Mpb_Vbus_mV(void) { return Mpb_Bridge_Vbus_mV(); }
uint32_t Mpb_Millis(void) { return g_ms; }
uint32_t Mpb_Micros(void) { return g_ms * 1000u; }

/* ---------------- モデル ---------------- */
typedef struct {
    double R, L, Ke, J, b, C, Vs, Rs, Iload;
    int sink;                          /* 1 = 電源が吸い込める (バッテリー) */
} Plant;

static int g_fail;
static uint16_t g_r_mohm = 1000;   /* スケッチに与える巻線抵抗 (0 = 不明) */
#define CHECK(c, ...) do { if (!(c)) { printf("FAIL %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); g_fail++; } } while (0)

static void plant_step(const Plant *p, double dt)
{
    double bemf = p->Ke * g_w, isrc, ibus, vm;
    int a = g_leg[0], bl = g_leg[1];

    if (a < 0 && bl < 0)
    {
        /* 惰性: 逆起電力が母線を超えたらダイオードで母線へ流れる */
        double over = fabs(bemf) - g_v - 1.4;
        double target = over > 0 ? -copysign(over / p->R, bemf) : 0.0;
        g_i += (target - g_i) * fmin(1.0, dt * p->R / p->L);
        ibus = -fabs(g_i);
    }
    else
    {
        double D = (a > 0 ? a : 0) / 1000.0 - (bl > 0 ? bl : 0) / 1000.0;
        vm = D * g_v;
        g_i += (vm - p->R * g_i - bemf) / p->L * dt;
        ibus = D * g_i;
    }
    g_w += (p->Ke * g_i - p->b * g_w) / p->J * dt;
    isrc = (p->Vs - g_v) / p->Rs;
    if (!p->sink && isrc < 0) isrc = 0;
    g_v += (isrc - ibus - p->Iload) / p->C * dt;      /* Iload: MCU などが常に使う電流 */
}

typedef struct { double vmax, imax, t_stop; int plug, end_coast; double e_back; } Result;

static Result run(const Plant *p, int16_t duty, uint16_t brake_mA, uint16_t vmax_cfg, int use_stop)
{
    Mpb_DcCfg c = {0};
    Result r = {0};
    double dt = 5e-6;
    int8_t sign0;

    c.ramp_per_ms = 0;
    c.i_limit_mA = 3000;
    c.r_mohm = g_r_mohm;
    c.brake_vbus_max_mV = vmax_cfg;
    g_i = 0; g_w = 0; g_v = p->Vs; g_ms = 1;
    memset(s_m, 0, sizeof(s_m));
    s_vnom = 0;
    s_t_ms = 0;
    Mpb_Dc_Init(0, &c);
    Mpb_Dc_SetDuty(0, duty);
    for (int ms = 0; ms < 1500; ms++)      /* 1.5 秒加速 */
    {
        g_ms++;
        Mpb_Dc_Task();
        for (int k = 0; k < 200; k++) plant_step(p, dt);
    }
    sign0 = g_w > 0 ? 1 : -1;
    if (use_stop) Mpb_Dc_Stop(0, brake_mA);
    else Mpb_Dc_Coast(0);
    r.t_stop = -1;
    for (int ms = 0; ms < 20000; ms++)
    {
        g_ms++;
        Mpb_Dc_Task();
        if ((sign0 > 0 && Mpb_Dc_Duty(0) < 0) || (sign0 < 0 && Mpb_Dc_Duty(0) > 0)) r.plug = 1;
        for (int k = 0; k < 200; k++)
        {
            plant_step(p, dt);
            if (g_v > r.vmax) r.vmax = g_v;
            if (fabs(g_i) > r.imax) r.imax = fabs(g_i);
            {
                double ib = (g_leg[0] < 0 && g_leg[1] < 0) ? 0 : ((g_leg[0] > 0 ? g_leg[0] : 0) - (g_leg[1] > 0 ? g_leg[1] : 0)) / 1000.0 * g_i;
                if (ib < 0) r.e_back += -ib * g_v * dt;      /* 母線へ戻したエネルギー [J] */
            }
        }
        if (r.t_stop < 0 && fabs(g_w) < 2.0) r.t_stop = ms / 1000.0;
        if (Mpb_Dc_Mode(0) == MPB_DC_COAST && r.t_stop >= 0) { r.end_coast = 1; break; }
    }
    return r;
}

int main(void)
{
    /* 12V 用の小型ギヤードモーター程度: R 1Ω, L 0.5mH, Ke 0.02 V·s/rad (≈ 480rpm/V), はずみ車付き */
    Plant pd = {1.0, 0.5e-3, 0.02, 2e-5, 2e-6, 100e-6, 12.0, 0.05, 0.03, 0};
    Plant bat = pd;
    Result r, rc;
    bat.sink = 1;

    /* 1) USB-PD (吸い込めない) で止める: 既定の上限 = 平常の VBUS + 1V */
    r = run(&pd, 800, 2000, 0, 1);
    printf("PD  stop : t=%.2fs  Vmax=%.2fV  Imax=%.2fA  plug=%d  coast=%d  back=%.3fJ\n", r.t_stop, r.vmax, r.imax, r.plug, r.end_coast, r.e_back);
    CHECK(!r.plug, "逆転した");
    CHECK(r.vmax < 12.0 + 1.0 + 0.6, "VBUS が上がりすぎ %.2fV", r.vmax);
    CHECK(r.imax < 2.0 * 1.5 + 0.5, "電流が大きすぎ %.2fA", r.imax);
    CHECK(r.end_coast, "最後が惰性 (全 FET OFF) でない");

    /* 2) 惰性で止めたときと比べる */
    rc = run(&pd, 800, 0, 0, 0);
    printf("PD  coast: t=%.2fs\n", rc.t_stop);
    if (rc.t_stop < 0) rc.t_stop = 20.0;                       /* 20 秒で止まらなかった */
    CHECK(r.t_stop > 0 && r.t_stop < rc.t_stop * 0.5, "制動が効いていない (%.2fs vs 惰性 %.2fs)", r.t_stop, rc.t_stop);

    /* 3) バッテリー (吸い込める) なら上限を上げて回生できる */
    r = run(&bat, 800, 2000, 15000, 1);
    printf("BAT stop : t=%.2fs  Vmax=%.2fV  Imax=%.2fA  plug=%d  coast=%d  back=%.3fJ\n", r.t_stop, r.vmax, r.imax, r.plug, r.end_coast, r.e_back);
    CHECK(!r.plug && r.end_coast, "バッテリーで止まらない");
    CHECK(r.e_back > 0.01, "回生していない (%.4fJ)", r.e_back);

    /* 4) 逆転方向でも同じ */
    r = run(&pd, -800, 2000, 0, 1);
    printf("PD  rev  : t=%.2fs  Vmax=%.2fV  Imax=%.2fA  plug=%d  coast=%d\n", r.t_stop, r.vmax, r.imax, r.plug, r.end_coast);
    CHECK(!r.plug && r.end_coast && r.vmax < 13.6, "逆転方向で失敗");

    /* 5) 巻線抵抗が不明 (r_mohm = 0) でも止まる (短絡への近道を使わず回生だけ) */
    g_r_mohm = 0;
    r = run(&pd, 800, 2000, 0, 1);
    printf("PD  stop R=?: t=%.2fs  Vmax=%.2fV  Imax=%.2fA  plug=%d  coast=%d\n", r.t_stop, r.vmax, r.imax, r.plug, r.end_coast);
    CHECK(!r.plug && r.end_coast && r.vmax < 13.6 && r.imax < 3.5, "巻線抵抗が不明だと失敗");
    g_r_mohm = 1000;

    /* 6) duty モードで急に 0 へ (ランプなし): 減速ストール防止で VBUS が上限で止まる */
    {
        Mpb_DcCfg c = {0};
        double vmax = 0, imax = 0;
        c.i_limit_mA = 3000;
        c.r_mohm = g_r_mohm;
        g_i = 0; g_w = 0; g_v = 12.0; g_ms = 1;
        memset(s_m, 0, sizeof(s_m)); s_vnom = 0; s_t_ms = 0;
        Mpb_Dc_Init(0, &c);
        Mpb_Dc_SetDuty(0, 800);
        for (int ms = 0; ms < 1500; ms++) { g_ms++; Mpb_Dc_Task(); for (int k = 0; k < 200; k++) plant_step(&pd, 5e-6); }
        Mpb_Dc_SetDuty(0, 0);
        for (int ms = 0; ms < 3000; ms++)
        {
            g_ms++; Mpb_Dc_Task();
            for (int k = 0; k < 200; k++) { plant_step(&pd, 5e-6); if (g_v > vmax) vmax = g_v; if (fabs(g_i) > imax && ms > 2) imax = fabs(g_i); }
        }
        printf("PD  duty→0: Vmax=%.2fV  Imax=%.2fA (2ms 以降)  w=%.1f\n", vmax, imax, g_w);
        CHECK(vmax < 13.6, "duty を急に下げると VBUS が上がりすぎ %.2fV", vmax);
        CHECK(imax < 3.0 * 1.5, "duty を急に下げると電流が大きすぎ %.2fA", imax);
    }

    if (g_fail)
    {
        printf("dc: %d FAILED\n", g_fail);
        return 1;
    }
    printf("dc: all tests passed\n");
    return 0;
}
