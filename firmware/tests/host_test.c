/*
 * ホスト (PC) で動く単体テスト: 書式化 / CIE / 環境センサの換算 (データシートの例題) / CRC
 *   make -C firmware/tests      (gcc があればよい。実機は不要)
 */
#include <stdio.h>
#include <string.h>
#include "mpb.h"
#include "mpb_cie.h"
#include "mpb_i2c.h"

USART_TypeDef g_usart;
static uint32_t g_ms;
uint32_t Mpb_Millis(void) { return g_ms; }
void USART1_CFG(uint32_t b) { (void)b; }

#include "../lib/mpb_log.c"

/* mpb_env.c の I2C 呼び出しはテストでは使わない (convert だけ試す) */
uint8_t Mpb_I2c_Start(uint8_t a, const uint8_t *t, uint8_t nt, uint8_t *r, uint8_t nr) { (void)a; (void)t; (void)nt; (void)r; (void)nr; return 0; }
void Mpb_I2c_Task(void) {}
uint8_t Mpb_I2c_Done(void) { return 0; }
Mpb_I2cResult Mpb_I2c_Result(void) { return MPB_I2C_OK; }
#include "../lib/mpb_env.c"

static int fails;
#define CHECK(c, ...) do { if (!(c)) { fails++; printf("FAIL %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

static void t_fmt(void)
{
    char b[64];
    Mpb_Fmt(b, sizeof b, "[%5u.%03u] %c %d|%-7s|%02x|%X", 12u, 45u, 'I', -123, "SHT", 10, 0xBEEFu);
    CHECK(!strcmp(b, "[   12.045] I -123|SHT    |0a|BEEF"), "fmt got '%s'", b);
    Mpb_Fmt(b, sizeof b, "%d %05d %u", (int32_t)0x80000000, -42, 4294967295u);
    CHECK(!strcmp(b, "-2147483648 -0042 4294967295"), "fmt2 got '%s'", b);
    Mpb_Fmt(b, 6, "%s", "truncate");
    CHECK(!strcmp(b, "trunc"), "trunc got '%s'", b);
    CHECK(!strcmp(Mpb_Log_Fixed(-5, 1), "-0.5"), "fixed1 %s", Mpb_Log_Fixed(-5, 1));
    CHECK(!strcmp(Mpb_Log_Fixed(123456, 2), "1234.56"), "fixed2 %s", Mpb_Log_Fixed(123456, 2));
    CHECK(!strcmp(Mpb_Log_Fixed(7, 0), "7"), "fixed0");
}

static void t_log(void)
{
    g_ms = 1234;
    s_head = s_tail = 0;
    Mpb_Log_Line('I', "v=%u", 5u);
    char out[64] = {0};
    for (uint32_t i = s_tail; i != s_head; i++) out[i] = s_buf[i & (MPB_LOG_BUF - 1)];
    CHECK(!strcmp(out, "[    1.234] I v=5\r\n"), "line '%s'", out);
    CHECK(g_usart.CTLR1 & UART_CTLR1_TXEIE, "TXEIE not set");
    /* 溢れ */
    char big[600];
    memset(big, 'x', sizeof big);
    s_head = s_tail = 0; s_drop = 0;
    CHECK(Mpb_Log_Write(big, sizeof big) == (int)MPB_LOG_BUF, "write n");
    CHECK(Mpb_Log_Dropped() == sizeof big - MPB_LOG_BUF, "dropped %u", Mpb_Log_Dropped());
}

static void t_cie(void)
{
    CHECK(Mpb_Cie(10000, 1000) == 1000, "cie max");
    CHECK(Mpb_Cie(0, 1000) == 0, "cie 0");
    /* L* = 50 → Y = (66/116)^3 = 0.18419 */
    uint32_t d = Mpb_Cie(5000, 100000);
    CHECK(d >= 18410 && d <= 18425, "cie 50 = %u", d);
    /* L* = 8 → Y = 8/903.3 = 0.008856 (つなぎ目) */
    d = Mpb_Cie(800, 1000000);
    CHECK(d >= 8850 && d <= 8862, "cie 8 = %u", d);
    CHECK(Mpb_Cie(801, 1000000) >= d, "cie monotonic at 8");
}

static void t_env(void)
{
    Mpb_Env e;
    /* SHT3x: CRC の例題 0xBEEF → 0x92 (データシート) */
    uint8_t be[2] = {0xBE, 0xEF};
    CHECK(crc8_sht(be, 2) == 0x92, "crc %02x", crc8_sht(be, 2));
    memset(&e, 0, sizeof e);
    e.type = MPB_ENV_SHT3X;
    e.buf[0] = 0x66; e.buf[1] = 0x66; e.buf[2] = crc8_sht(e.buf, 2);     /* T = −45 + 175 × 0.4 = 25.0℃ */
    e.buf[3] = 0x80; e.buf[4] = 0x00; e.buf[5] = crc8_sht(e.buf + 3, 2); /* RH = 50.0% */
    CHECK(convert(&e) && e.r.t_c100 == 2500 && e.r.rh_100 == 5000, "sht %d %u", e.r.t_c100, e.r.rh_100);
    e.buf[5] ^= 1;
    CHECK(!convert(&e), "sht bad crc accepted");

    /* AHT20: RH 2^19 → 50%, T 2^19 → 50℃ */
    memset(&e, 0, sizeof e);
    e.type = MPB_ENV_AHT20;
    uint32_t h = 1u << 19, t = 1u << 19;
    e.buf[0] = 0x1C; e.buf[1] = (uint8_t)(h >> 12); e.buf[2] = (uint8_t)(h >> 4);
    e.buf[3] = (uint8_t)(((h & 0xF) << 4) | (t >> 16)); e.buf[4] = (uint8_t)(t >> 8); e.buf[5] = (uint8_t)t;
    CHECK(convert(&e) && e.r.t_c100 == 5000 && e.r.rh_100 == 5000, "aht %d %u", e.r.t_c100, e.r.rh_100);

    /* BMP280 データシート 3.12 の例題: adc_T 519888 → 25.08℃, adc_P 415148 → 100653 Pa */
    memset(&e, 0, sizeof e);
    e.type = MPB_ENV_BMX280;
    e.T1 = 27504; e.T2 = 26435; e.T3 = -1000;
    e.P1 = 36477; e.P2 = -10685; e.P3 = 3024; e.P4 = 2855; e.P5 = 140; e.P6 = -7; e.P7 = 15500; e.P8 = -14600; e.P9 = 6000;
    uint32_t ap = 415148, at = 519888;
    e.buf[0] = (uint8_t)(ap >> 12); e.buf[1] = (uint8_t)(ap >> 4); e.buf[2] = (uint8_t)((ap & 0xF) << 4);
    e.buf[3] = (uint8_t)(at >> 12); e.buf[4] = (uint8_t)(at >> 4); e.buf[5] = (uint8_t)((at & 0xF) << 4);
    CHECK(convert(&e), "bmp convert");
    CHECK(e.r.t_c100 == 2508, "bmp T %d", e.r.t_c100);
    CHECK(e.r.p_pa >= 100652 && e.r.p_pa <= 100654, "bmp P %u", e.r.p_pa);

    /* S-5851A: 0x1900 → 25.0℃, 0xE700 → −25.0℃ */
    memset(&e, 0, sizeof e);
    e.type = MPB_ENV_S5851A;
    e.buf[0] = 0x19; e.buf[1] = 0x00;
    CHECK(convert(&e) && e.r.t_c100 == 2500, "s5851 %d", e.r.t_c100);
    e.buf[0] = 0xE7; e.buf[1] = 0x00;
    CHECK(convert(&e) && e.r.t_c100 == -2500, "s5851 neg %d", e.r.t_c100);
}

int main(void)
{
    t_fmt();
    t_log();
    t_cie();
    t_env();
    printf(fails ? "%d FAILED\n" : "all tests passed\n", fails);
    return fails != 0;
}
