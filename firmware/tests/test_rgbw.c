/* ホストテスト: RGBW 調光エンジン (HSV → 比率, CIE, マスター × チャネル L*, フェード) */
#include <stdio.h>
#include "mpb.h"
#include "mpb_rgbw.h"

static uint32_t g_ms;
uint32_t Mpb_Millis(void) { return g_ms; }
uint32_t Mpb_Micros(void) { return g_ms * 1000u; }
uint32_t Mpb_Vbus_mV(void) { return 12000; }
static uint16_t g_low[4];
void Mpb_Bridge_LegLow(uint8_t leg, uint16_t on) { g_low[leg] = on; }
uint16_t Mpb_Bridge_Vdd8Auto(void) { return 10000; }
#include "../lib/mpb_rgbw.c"

static int fails;
#define CHECK(c, ...) do { if (!(c)) { fails++; printf("FAIL %d: ", __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

int main(void)
{
    uint16_t r, g, b;
    static const uint8_t legs[4] = {0, 1, 2, 3};

    Mpb_Hsv2Rgb(0, 1000, &r, &g, &b);   CHECK(r == 1000 && g == 0 && b == 0, "red %u %u %u", r, g, b);
    Mpb_Hsv2Rgb(120, 1000, &r, &g, &b); CHECK(r == 0 && g == 1000 && b == 0, "green %u %u %u", r, g, b);
    Mpb_Hsv2Rgb(240, 1000, &r, &g, &b); CHECK(r == 0 && g == 0 && b == 1000, "blue %u %u %u", r, g, b);
    Mpb_Hsv2Rgb(77, 0, &r, &g, &b);     CHECK(r == 1000 && g == 1000 && b == 1000, "white %u %u %u", r, g, b);

    Mpb_Rgbw_Init(legs, 4);
    /* 赤 100%, マスター L* 100 → R = 65535, 他 0 */
    Mpb_Rgbw_SetHsv(0, 1000, 1000);
    Mpb_Rgbw_SetMaster(10000, 0);
    g_ms++; Mpb_Rgbw_Task();
    CHECK(g_low[0] == 65535 && g_low[1] == 0 && g_low[2] == 0 && g_low[3] == 0, "R %u %u %u %u", g_low[0], g_low[1], g_low[2], g_low[3]);
    /* 彩度 0 → RGB 等量 + 白 100% */
    Mpb_Rgbw_SetHsv(0, 0, 1000);
    g_ms++; Mpb_Rgbw_Task();
    CHECK(g_low[0] == 65535 && g_low[3] == 65535, "W %u %u", g_low[0], g_low[3]);
    /* マスター L* 50 → 線形 18.4% */
    Mpb_Rgbw_SetMaster(5000, 0);
    g_ms++; Mpb_Rgbw_Task();
    CHECK(g_low[0] >= 12060 && g_low[0] <= 12080, "L50 %u", g_low[0]);
    /* チャネル L*: 255 × マスター 50 = L* 50 / 128 → L* 25.1 */
    Mpb_Rgbw_SetLevels(255, 128, 0, 0);
    g_ms++; Mpb_Rgbw_Task();
    CHECK(g_low[0] >= 12060 && g_low[0] <= 12080 && g_low[1] > 2900 && g_low[1] < 3100 && g_low[2] == 0,
          "levels %u %u %u", g_low[0], g_low[1], g_low[2]);
    /* フェード: 0 → 100 を 1000ms。途中は単調に増え, 終わりで最大 */
    Mpb_Rgbw_SetHsv(0, 1000, 0);
    Mpb_Rgbw_SetMaster(0, 0); g_ms++; Mpb_Rgbw_Task();
    Mpb_Rgbw_SetMaster(10000, 1000);
    uint16_t prev = 0; int mono = 1;
    for (int i = 0; i < 1100; i++) { g_ms++; Mpb_Rgbw_Task(); if (g_low[0] < prev) mono = 0; prev = g_low[0]; }
    CHECK(mono && g_low[0] == 65535 && !Mpb_Rgbw_Fading(), "fade %u", g_low[0]);
    /* RGB 3ch: W は出さない */
    Mpb_Rgbw_Init(legs, 3); g_low[3] = 77;
    Mpb_Rgbw_SetHsv(0, 0, 1000); Mpb_Rgbw_SetMaster(10000, 0); g_ms++; Mpb_Rgbw_Task();
    CHECK(g_low[3] == 77 && g_low[0] == 65535 && g_low[1] == 65535, "rgb3 %u", g_low[3]);

    printf(fails ? "rgbw: %d FAILED\n" : "rgbw: all tests passed\n", fails);
    return fails != 0;
}
