/*
 * mpb_ht16k33 — HT16K33(A) 8×8 マトリクスの数珠つなぎ (I2C, 待ちなし)
 * Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
 */
#include "mpb_ht16k33.h"
#include "mpb_i2c.h"
#include "mpb.h"

/* 1 モジュールの初期化手順: 発振 ON → 表示 ON (点滅) → 明るさ。その後データ */
enum { ST_OSC, ST_DISP, ST_DIM, ST_DATA, ST_OK };

static Mpb_Matrix *s_m;
static uint8_t  s_addr, s_n, s_map, s_dim = 8, s_blink;
static uint8_t  s_st[MPB_HT16K33_MAX], s_dirty, s_online, s_fail;
static uint8_t  s_cur = 0xFF, s_pending, s_next;
static uint32_t s_retry_ms[MPB_HT16K33_MAX];
static uint8_t  s_buf[17];

void Mpb_Ht16k33_Init(uint8_t first_addr7, uint8_t n, uint8_t map, Mpb_Matrix *m)
{
    s_addr = first_addr7 ? first_addr7 : 0x70;
    s_n = n ? n : 1u;
    if (s_n > MPB_HT16K33_MAX) s_n = MPB_HT16K33_MAX;
    s_map = map;
    s_m = m;
    Mpb_Matrix_Init(m, (uint8_t)(s_n * 8u));
    for (uint8_t i = 0; i < s_n; i++) s_st[i] = ST_OSC;
    s_fail = 0;
    s_dirty = 0;
    s_online = 0;
    s_pending = 0;
    s_cur = 0xFF;
}

static void reinit_all(uint8_t from)
{
    for (uint8_t i = 0; i < s_n; i++)
    {
        if (s_st[i] > from) s_st[i] = from;
    }
}

void Mpb_Ht16k33_Brightness(uint8_t b) { s_dim = b & 15u; reinit_all(ST_DIM); }
void Mpb_Ht16k33_Blink(uint8_t mode)   { s_blink = mode & 3u; reinit_all(ST_DISP); }
uint8_t Mpb_Ht16k33_Online(void)       { return s_online; }

/* モジュール i の 16 バイトを作る */
static void render(uint8_t i)
{
    const uint8_t *r = s_m->r + i * 8u, *g = s_m->g + i * 8u;
    uint8_t base = s_map & 0x0Fu;

    for (uint8_t k = 0; k < 16; k++) s_buf[1 + k] = 0;
    s_buf[0] = 0x00;                                  /* 表示 RAM の先頭から */
    for (uint8_t x = 0; x < 8; x++)
    {
        uint8_t cr = r[x], cg = g[x];
        uint8_t xx = (s_map & MPB_HT_FLIPX) ? (uint8_t)(7u - x) : x;
        for (uint8_t y = 0; y < 8; y++)
        {
            uint8_t on_r = (uint8_t)((cr >> y) & 1u), on_g = (uint8_t)((cg >> y) & 1u);
            uint8_t yy = (s_map & MPB_HT_FLIPY) ? (uint8_t)(7u - y) : y;
            uint8_t row = yy, col = xx;
            if (s_map & MPB_HT_COLROW) { row = xx; col = yy; }
            if (base == MPB_HT_BICOLOR)
            {
                if (on_g) s_buf[1 + row * 2u] |= (uint8_t)(1u << col);
                if (on_r) s_buf[2 + row * 2u] |= (uint8_t)(1u << col);
            }
            else if (on_r | on_g)                     /* 単色: どちらかの色で点灯 */
            {
                if (base == MPB_HT_ADAFRUIT) col = (uint8_t)((col + 7u) & 7u);
                s_buf[1 + row * 2u] |= (uint8_t)(1u << col);
            }
        }
    }
}

static uint8_t start(uint8_t i, uint8_t len)
{
    if (Mpb_I2c_Start((uint8_t)(s_addr + i), s_buf, len, 0, 0))
    {
        s_cur = i;
        s_pending = 1;
        return 1;
    }
    return 0;
}

uint8_t Mpb_Ht16k33_Task(void)
{
    uint8_t busy = 0;

    if (!s_m)
    {
        return 0;
    }
    if (Mpb_Matrix_Tick(s_m))
    {
        s_m->dirty = 0;
        s_dirty = (uint8_t)((1u << s_n) - 1u);       /* 変わったモジュールだけ送るのが理想だが, 流れる文字は全部変わる */
    }
    Mpb_I2c_Task();
    if (s_pending)
    {
        if (!Mpb_I2c_Done())
        {
            return 1;
        }
        s_pending = 0;
        if (Mpb_I2c_Result() == MPB_I2C_OK)
        {
            s_st[s_cur]++;
            if (s_st[s_cur] == ST_OK)
            {
                s_online |= (uint8_t)(1u << s_cur);
                s_fail &= (uint8_t)~(1u << s_cur);
            }
        }
        else
        {
            s_st[s_cur] = ST_OSC;                     /* 応答なし: 1 秒後にやり直す (抜き差しに追従) */
            s_retry_ms[s_cur] = Mpb_Millis();
            s_fail |= (uint8_t)(1u << s_cur);
            s_dirty |= (uint8_t)(1u << s_cur);
            s_online &= (uint8_t)~(1u << s_cur);
        }
    }
    /* 送るものがあるモジュールを順番に (1 回に 1 転送) */
    for (uint8_t k = 0; k < s_n; k++)
    {
        uint8_t i = (uint8_t)((s_next + k) % s_n);
        uint8_t st = s_st[i];
        if ((s_fail & (1u << i)) && (uint32_t)(Mpb_Millis() - s_retry_ms[i]) < 1000u)
        {
            continue;                                  /* 応答の無かったモジュールは 1 秒おきに試す */
        }
        if (st == ST_OK && !(s_dirty & (1u << i)))
        {
            continue;
        }
        busy = 1;
        switch (st)
        {
        case ST_OSC:
            s_buf[0] = 0x21;
            start(i, 1);
            break;
        case ST_DISP:
            s_buf[0] = (uint8_t)(0x81u | (s_blink << 1));
            start(i, 1);
            break;
        case ST_DIM:
            s_buf[0] = (uint8_t)(0xE0u | s_dim);
            start(i, 1);
            break;
        default:                                       /* ST_DATA / ST_OK: 画を送る */
            render(i);
            if (start(i, 17))
            {
                s_dirty &= (uint8_t)~(1u << i);
                s_st[i] = ST_DATA;                     /* 成功で ST_OK へ */
            }
            break;
        }
        if (s_pending)
        {
            s_next = (uint8_t)(i + 1u);
            break;
        }
    }
    return busy;
}
