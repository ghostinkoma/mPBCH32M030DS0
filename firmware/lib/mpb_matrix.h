/*
 * mpb_matrix — 8 ドット高の LED マトリクス (8×8 モジュールの数珠つなぎ) の描画バッファ
 *
 * HT16K33 (mpb_ht16k33) と TM1640 (mpb_tm1640) のドライバが共用する。色は 2 色 (赤 / 緑, 両方 = 橙)。
 * 単色のモジュールでは MPB_MX_RED (= 点灯) だけを使う。
 * 1 列 = 1 バイト (bit0 = 上の行), 左から x = 0, 1, … (モジュール 0 が左端)。
 * 文字は 5×7 (mpb_font5x7), 1 文字 6 ドット幅。8 枚つなげば 64 ドット = 10 文字。
 *
 *   static Mpb_Matrix mx;
 *   Mpb_Matrix_Init(&mx, 4 * 8);                     // 4 枚 = 32 ドット
 *   Mpb_Matrix_Print(&mx, 0, "12.3V", MPB_MX_GREEN); // 止まった文字
 *   Mpb_Matrix_Marquee(&mx, "Hello CH32M030 ", MPB_MX_ORANGE, 40);   // 流れる文字 (40ms/ドット)
 *   ドライバの Task() が Mpb_Matrix_Tick() を呼んで流し, 変わったときだけ送る。
 * Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
 */
#ifndef MPB_MATRIX_H
#define MPB_MATRIX_H

#include <stdint.h>

#ifndef MPB_MATRIX_MAXW
#define MPB_MATRIX_MAXW   64u        /* 最大幅 [ドット] = 8 枚 */
#endif
#ifndef MPB_MATRIX_TEXT
#define MPB_MATRIX_TEXT   48u        /* 流す文字列の最大長 (終端込み) */
#endif

enum { MPB_MX_OFF = 0, MPB_MX_RED = 1, MPB_MX_GREEN = 2, MPB_MX_ORANGE = 3 };

typedef struct {
    uint8_t  r[MPB_MATRIX_MAXW];
    uint8_t  g[MPB_MATRIX_MAXW];
    uint8_t  w;                      /* 幅 [ドット] */
    uint8_t  dirty;                  /* 1 = 送る必要がある (ドライバが 0 に戻す) */
    uint8_t  color, scrolling;
    uint16_t step_ms;
    int16_t  pos, len_px;
    uint32_t t;
    char     text[MPB_MATRIX_TEXT];
} Mpb_Matrix;

void    Mpb_Matrix_Init(Mpb_Matrix *m, uint8_t width);
void    Mpb_Matrix_Clear(Mpb_Matrix *m);
void    Mpb_Matrix_Dot(Mpb_Matrix *m, int x, int y, uint8_t color);
int     Mpb_Matrix_Char(Mpb_Matrix *m, int x, int y, char c, uint8_t color);     /* 戻り値 = 6 (次の文字の x 増分) */
void    Mpb_Matrix_Print(Mpb_Matrix *m, int x, const char *s, uint8_t color);   /* 流れを止めて画面を書き直す */
void    Mpb_Matrix_Marquee(Mpb_Matrix *m, const char *s, uint8_t color, uint16_t step_ms);   /* 右から左へ流す (繰り返し) */
uint8_t Mpb_Matrix_Tick(Mpb_Matrix *m);                                         /* 流す。1 = 画が変わった */

#endif /* MPB_MATRIX_H */
