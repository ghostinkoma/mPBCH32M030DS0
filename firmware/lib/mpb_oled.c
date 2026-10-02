/*
 * mpb_oled — I2C の OLED (SSD1306 / SH1106) にテキストとバー (待ちなし)
 * Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
 */
#include <stdarg.h>
#include <string.h>
#include "mpb_oled.h"
#include "mpb_i2c.h"
#include "mpb_log.h"
#include "mpb_font5x7.h"
#include "mpb.h"

#define NO_BAR 0xFFFFu

enum { ST_OFF, ST_INIT, ST_IDLE, ST_ADDR, ST_DATA, ST_CMD };

static char     s_text[MPB_OLED_ROWS][MPB_OLED_COLS];
static uint16_t s_bar[MPB_OLED_ROWS];
static uint8_t  s_inv, s_dirty, s_rows = 8, s_addr = 0x3C, s_type, s_height = 64;
static uint8_t  s_state = ST_OFF, s_pending, s_ready, s_page;
static uint8_t  s_contrast = 0xCF, s_contrast_req;
static uint32_t s_retry_ms;
static uint8_t  s_buf[1 + 128];      /* 制御バイト + 1 ページ (128 列) */

static uint8_t start(uint8_t n)
{
    if (Mpb_I2c_Start(s_addr, s_buf, n, 0, 0))
    {
        s_pending = 1;
        return 1;
    }
    return 0;
}

static uint8_t send_init(void)
{
    static const uint8_t seq[] = {
        0x00,                       /* 制御バイト: 以降すべてコマンド */
        0xAE, 0xD5, 0x80, 0xA8, 63, 0xD3, 0x00, 0x40, 0x8D, 0x14, 0x20, 0x00,
        0xA1, 0xC8, 0xDA, 0x12, 0x81, 0xCF, 0xD9, 0xF1, 0xDB, 0x40, 0xA4, 0xA6, 0xAF
    };
    memcpy(s_buf, seq, sizeof(seq));
    s_buf[5] = (uint8_t)(s_height - 1u);          /* マルチプレクス比 */
    s_buf[16] = s_height == 32u ? 0x02u : 0x12u;  /* COM ピン配置 */
    s_buf[18] = s_contrast;
    return start(sizeof(seq));
}

static uint8_t send_addr(uint8_t p)
{
    uint8_t n;

    s_buf[0] = 0x00;
    if (s_type == MPB_OLED_SH1106)
    {
        s_buf[1] = (uint8_t)(0xB0u | p);
        s_buf[2] = 0x02;                          /* 列 2 から (SH1106 は 132 列の中央 128 列) */
        s_buf[3] = 0x10;
        n = 4;
    }
    else
    {
        s_buf[1] = 0x21; s_buf[2] = 0; s_buf[3] = 127;
        s_buf[4] = 0x22; s_buf[5] = p; s_buf[6] = p;
        n = 7;
    }
    return start(n);
}

/* 1 ページ (= 1 行) を s_buf[1..128] に描く */
static void render(uint8_t p)
{
    uint8_t *d = &s_buf[1];

    s_buf[0] = 0x40;                              /* 制御バイト: 以降すべてデータ */
    if (s_bar[p] != NO_BAR)
    {
        uint16_t w = (uint16_t)((uint32_t)s_bar[p] * 126u / 1000u);
        d[0] = d[127] = 0x7E;
        for (uint8_t x = 1; x < 127; x++)
        {
            d[x] = (uint8_t)(0x42u | (x <= w ? 0x3Cu : 0u));
        }
    }
    else
    {
        for (uint8_t c = 0; c < MPB_OLED_COLS; c++)
        {
            const uint8_t *g = Mpb_Font5x7(s_text[p][c]);
            memcpy(&d[c * 6u], g, 5);
            d[c * 6u + 5u] = 0;
        }
        d[126] = d[127] = 0;
    }
    if (s_inv & (1u << p))
    {
        for (uint8_t x = 0; x < 128; x++) d[x] = (uint8_t)~d[x];
    }
}

void Mpb_Oled_Init(uint8_t addr7, uint8_t height, Mpb_OledType type)
{
    s_addr = addr7 ? addr7 : 0x3C;
    s_height = height == 32u ? 32u : 64u;
    s_rows = (uint8_t)(s_height / 8u);
    s_type = (uint8_t)type;
    s_ready = 0;
    s_pending = 0;
    s_retry_ms = Mpb_Millis() - 400u;             /* 電源投入から 100ms 待って初期化 */
    Mpb_Oled_Clear();
    s_state = ST_INIT;
}

void Mpb_Oled_Clear(void)
{
    memset(s_text, ' ', sizeof(s_text));
    for (uint8_t r = 0; r < MPB_OLED_ROWS; r++) s_bar[r] = NO_BAR;
    s_inv = 0;
    s_dirty = 0xFF;
}

void Mpb_Oled_Print(uint8_t row, uint8_t col, const char *s)
{
    if (row >= MPB_OLED_ROWS)
    {
        return;
    }
    for (; col < MPB_OLED_COLS && *s; col++, s++)
    {
        if (s_text[row][col] != *s)
        {
            s_text[row][col] = *s;
            s_dirty |= (uint8_t)(1u << row);
        }
    }
    if (s_bar[row] != NO_BAR)
    {
        s_bar[row] = NO_BAR;
        s_dirty |= (uint8_t)(1u << row);
    }
}

void Mpb_Oled_Printf(uint8_t row, const char *fmt, ...)
{
    char line[MPB_OLED_COLS + 1];
    va_list ap;
    int n;

    va_start(ap, fmt);
    n = Mpb_VFmt(line, sizeof(line), fmt, ap);
    va_end(ap);
    if (n < 0) n = 0;
    if (n > (int)MPB_OLED_COLS) n = MPB_OLED_COLS;
    memset(&line[n], ' ', MPB_OLED_COLS - (uint8_t)n);
    line[MPB_OLED_COLS] = 0;
    Mpb_Oled_Print(row, 0, line);
}

void Mpb_Oled_Bar(uint8_t row, uint16_t permille)
{
    if (row >= MPB_OLED_ROWS)
    {
        return;
    }
    if (permille > 1000u) permille = 1000u;
    /* 1 ドット (= 1000/126) 未満の変化は送らない */
    if (s_bar[row] == NO_BAR || s_bar[row] * 126u / 1000u != permille * 126u / 1000u)
    {
        s_dirty |= (uint8_t)(1u << row);
    }
    s_bar[row] = permille;
}

void Mpb_Oled_Invert(uint8_t row, uint8_t on)
{
    uint8_t m = (uint8_t)(1u << row);

    if (row < MPB_OLED_ROWS && !!(s_inv & m) != !!on)
    {
        s_inv ^= m;
        s_dirty |= m;
    }
}

void Mpb_Oled_Contrast(uint8_t c)
{
    s_contrast = c;
    s_contrast_req = 1;
}

uint8_t Mpb_Oled_Ready(void) { return s_ready; }

uint8_t Mpb_Oled_Task(void)
{
    uint8_t rowmask = (uint8_t)((1u << s_rows) - 1u);

    if (s_state == ST_OFF)
    {
        return 0;
    }
    Mpb_I2c_Task();
    if (s_pending)
    {
        Mpb_I2cResult r;
        if (!Mpb_I2c_Done())
        {
            return 1;
        }
        r = Mpb_I2c_Result();
        s_pending = 0;
        if (r != MPB_I2C_OK)
        {
            /* 応答なし: 0.5 秒後に初期化からやり直す (抜き差しにも追従) */
            s_ready = 0;
            s_dirty = 0xFF;
            s_state = ST_INIT;
            s_retry_ms = Mpb_Millis();
            return 1;
        }
        switch (s_state)
        {
        case ST_INIT: s_ready = 1; s_state = ST_IDLE; break;
        case ST_ADDR: s_state = ST_DATA; break;
        default:      s_state = ST_IDLE; break;
        }
    }

    switch (s_state)
    {
    case ST_INIT:
        if ((uint32_t)(Mpb_Millis() - s_retry_ms) >= 500u)
        {
            send_init();
        }
        return 1;
    case ST_DATA:
        render(s_page);
        start(1 + 128);
        return 1;
    case ST_IDLE:
        if (s_contrast_req)
        {
            s_buf[0] = 0x00; s_buf[1] = 0x81; s_buf[2] = s_contrast;
            if (start(3)) { s_contrast_req = 0; s_state = ST_CMD; }
            return 1;
        }
        if (!(s_dirty & rowmask))
        {
            return 0;
        }
        for (uint8_t p = 0; p < s_rows; p++)
        {
            if (s_dirty & (1u << p))
            {
                if (send_addr(p))
                {
                    s_page = p;
                    s_dirty &= (uint8_t)~(1u << p);   /* 送信中に変わったらもう一度立つ */
                    s_state = ST_ADDR;
                }
                break;
            }
        }
        return 1;
    default:
        return 1;
    }
}
