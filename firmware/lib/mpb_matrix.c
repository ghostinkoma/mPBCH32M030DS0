/*
 * mpb_matrix — 8 ドット高の LED マトリクスの描画バッファ
 * 描き方は ghostinkoma/TM1640MatrixChain (drawDotExt / appendChar / ScrollString) を C に移したもの。
 * Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
 */
#include <string.h>
#include "mpb_matrix.h"
#include "mpb_font5x7.h"
#include "mpb.h"

#define TEXT_Y 1     /* 文字の上端 (7 ドットの字を 8 行の下寄せに: TM1640MatrixChain と同じ) */

void Mpb_Matrix_Init(Mpb_Matrix *m, uint8_t width)
{
    memset(m, 0, sizeof(*m));
    m->w = width > MPB_MATRIX_MAXW ? MPB_MATRIX_MAXW : width;
    m->dirty = 1;
}

void Mpb_Matrix_Clear(Mpb_Matrix *m)
{
    memset(m->r, 0, sizeof(m->r));
    memset(m->g, 0, sizeof(m->g));
    m->dirty = 1;
}

void Mpb_Matrix_Dot(Mpb_Matrix *m, int x, int y, uint8_t color)
{
    uint8_t b;

    if (x < 0 || x >= m->w || y < 0 || y > 7)
    {
        return;
    }
    b = (uint8_t)(1u << y);
    m->r[x] = (uint8_t)((color & MPB_MX_RED) ? (m->r[x] | b) : (m->r[x] & ~b));
    m->g[x] = (uint8_t)((color & MPB_MX_GREEN) ? (m->g[x] | b) : (m->g[x] & ~b));
    m->dirty = 1;
}

int Mpb_Matrix_Char(Mpb_Matrix *m, int x, int y, char c, uint8_t color)
{
    const uint8_t *g = Mpb_Font5x7(c);

    for (int col = 0; col < 6; col++)
    {
        int xx = x + col;
        uint8_t bits;
        if (xx < 0 || xx >= m->w)
        {
            continue;
        }
        bits = col < 5 ? (uint8_t)(g[col] << y) : 0u;   /* 字の 7 行分だけ上書き (残りの行はそのまま) */
        {
            uint8_t mask = (uint8_t)(0x7Fu << y);
            m->r[xx] = (uint8_t)((m->r[xx] & ~mask) | ((color & MPB_MX_RED) ? bits : 0u));
            m->g[xx] = (uint8_t)((m->g[xx] & ~mask) | ((color & MPB_MX_GREEN) ? bits : 0u));
        }
    }
    m->dirty = 1;
    return 6;
}

void Mpb_Matrix_Print(Mpb_Matrix *m, int x, const char *s, uint8_t color)
{
    m->scrolling = 0;
    Mpb_Matrix_Clear(m);
    for (; *s && x < m->w; s++)
    {
        x += Mpb_Matrix_Char(m, x, TEXT_Y, *s, color);
    }
}

static void draw_marquee(Mpb_Matrix *m)
{
    int x = m->w - m->pos;

    memset(m->r, 0, sizeof(m->r));
    memset(m->g, 0, sizeof(m->g));
    for (const char *s = m->text; *s && x < m->w; s++, x += 6)
    {
        if (x > -6)
        {
            Mpb_Matrix_Char(m, x, TEXT_Y, *s, m->color);
        }
    }
    m->dirty = 1;
}

void Mpb_Matrix_Marquee(Mpb_Matrix *m, const char *s, uint8_t color, uint16_t step_ms)
{
    /* 同じ文字列・色なら流れ続ける (毎回呼んでも最初に戻らない) */
    if (m->scrolling && m->color == color && !strncmp(m->text, s, MPB_MATRIX_TEXT - 1u))
    {
        m->step_ms = step_ms;
        return;
    }
    strncpy(m->text, s, MPB_MATRIX_TEXT - 1u);
    m->text[MPB_MATRIX_TEXT - 1u] = 0;
    m->len_px = (int16_t)(strlen(m->text) * 6u);
    m->color = color;
    m->step_ms = step_ms ? step_ms : 1u;
    m->pos = 0;
    m->t = Mpb_Millis();
    m->scrolling = 1;
    draw_marquee(m);
}

uint8_t Mpb_Matrix_Tick(Mpb_Matrix *m)
{
    uint32_t now = Mpb_Millis();

    if (m->scrolling && (uint32_t)(now - m->t) >= m->step_ms)
    {
        m->t += m->step_ms;
        if ((uint32_t)(now - m->t) > 1000u) m->t = now;   /* 長く止まっていたら追いかけない */
        if (++m->pos > m->w + m->len_px)
        {
            m->pos = 0;
        }
        draw_marquee(m);
    }
    return m->dirty;
}
