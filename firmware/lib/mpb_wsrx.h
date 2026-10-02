/*
 * mpb_wsrx — WS2812B / SK6812 互換の受信: この基板を「大電流の 1 画素」として LED の数珠つなぎに入れる
 *
 *   上流のコントローラ (ESP32・Arduino・WLED など) ─ DIN ─[この基板 = 1 画素]─ DOUT ─ 次の WS2812 …
 *
 * 先頭の 1 画素分 (GRB 3 バイト / GRBW 4 バイト) を受け取り, 残りのデータは DOUT へそのまま中継する。
 *
 * 受信の方式 (空いているタイマーが無いので CPU で見張る):
 *   Mpb_WsRx_Poll(max_us) が DIN を約 0.1µs 間隔で見張り, 40µs 以上 Low (リセット) の直後の立ち上がりだけを
 *   フレームの先頭として受け付ける (途中から拾って化けるのを防ぐ)。受信中 (自分の 32 ビット = 約 40µs と,
 *   中継するフレームの残り) は割込みを止めて, SysTick (CPU クロック) で High の幅を測る:
 *   High > t1_ns なら 1。WS2812B (T0H 0.4 / T1H 0.8µs) と SK6812 (0.3 / 0.6µs) の両方に既定の 0.5µs で合う。
 *   loop() の他の処理をしている間に来たフレームは捨てる (多くのコントローラは同じ内容を毎秒 30〜60 回送るので
 *   次のフレームで受かる)。confirm = 1 なら同じ値が 2 回続いたときだけ反映する (ノイズで一瞬光るのを防ぐ)。
 *
 * 端子: 既定 DIN = PC2 (J2-2 UART_RX → config.h で MPB_UART_BOOT 0), DOUT = PA14 (J2-19, I2C を使わないとき)。
 *   5V のコントローラからは 1kΩ 程度を直列に入れ, 3.3V に分圧するかレベル変換を入れる (CH32M030 の I/O は 3.3V)。
 *   中継する DOUT は 3.3V 出力 (次の WS2812 が 5V 給電なら先頭はレベル変換があると確実)。
 * Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
 */
#ifndef MPB_WSRX_H
#define MPB_WSRX_H

#include <stdint.h>
#include "mpb.h"

typedef struct {
    GPIO_TypeDef *din_port;     /* NULL = PC2 */
    uint16_t din_pin;
    GPIO_TypeDef *dout_port;    /* NULL = PA14 (dout_pin = 0 なら中継しない) */
    uint16_t dout_pin;
    uint8_t  bytes;             /* 3 = WS2812 (GRB) / 4 = SK6812 RGBW (GRBW) */
    uint16_t t1_ns;             /* 1 と判定する High の幅 (既定 500) */
    uint8_t  confirm;           /* 1: 同じ値が 2 回続いたら反映 */
} Mpb_WsRxCfg;

void     Mpb_WsRx_Init(const Mpb_WsRxCfg *cfg);
/* 最大 max_us だけ DIN を見張る。新しい値を受けたら 1 を返し rgbw[0..3] = R, G, B, W (3 バイトのとき W = 0) */
uint8_t  Mpb_WsRx_Poll(uint32_t max_us, uint8_t rgbw[4]);
uint32_t Mpb_WsRx_Frames(void);         /* 受けたフレーム数 */
uint32_t Mpb_WsRx_Errors(void);         /* 途中で切れた / タイミング外れのフレーム数 */
uint32_t Mpb_WsRx_LastMs(void);         /* 最後に受けた時刻 [ms] (0 = まだ) */

#endif /* MPB_WSRX_H */
