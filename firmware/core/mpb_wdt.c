/*
 * mpb_wdt — ウォッチドッグ (WWDG) と「全 FET OFF」
 *
 * CH32M030 には独立ウォッチドッグ (IWDG) が無く, WWDG (HCLK/4096/8 = 455µs/カウント, 最長 約 29ms) だけ。
 * そこで 2 段にする:
 *   1) ハード: WWDG を 0x7F から数えさせ, 0x40 で早期警告割込み (EWI, 約 28.7ms ごと) を出す。
 *      割込みごと止まった (割込み禁止で無限ループ, クロック異常など) ときは EWI が動けず, 約 29ms で WWDG がリセット。
 *   2) ソフト: EWI の中で「メインループ (または RTOS のタスク) が MPB_WDT_MS 以内に Mpb_Wdt_Feed() したか」を見る。
 *      していれば WWDG を 0x7F に戻す。していなければ **全ゲートを OFF にしてから** WWDG にリセットさせる (≤0.5ms)。
 *   EWI ではブリッジの設定 (デッドタイム・極性・TIM1/TIM2 の重なり) も毎回点検し, おかしければ同じく OFF → リセット。
 *
 * リセット後: PB9/11/13/15 (HO) はリセット値が Low 出力, PB8/10/12/14 (LO) は内蔵プルダウン (切れない),
 *   子基板の各 FET に 10k/20k の G-S プルダウン → 全 FET OFF。さらに main() の最初で Mpb_Gates_Off() を呼ぶ。
 * 上下短絡 (同じレッグの HO と LO が同時に ON) は, どの経路でも起きないようにしている (mpb_bridge.c も参照)。
 * Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
 */
#include "mpb.h"

#define WWDG_TICK_US   455u           /* 4096 × 8 / 72MHz */
#define WWDG_EWI_MS    29u            /* 0x7F → 0x40 */

static volatile uint16_t s_miss;      /* 最後の Feed からの EWI の回数 */
static uint16_t s_limit;              /* これを超えたら止める */
static uint8_t  s_on, s_cause, s_pending;
static uint32_t s_pending_ms;

static inline uint8_t irq_enabled(void)
{
    uint32_t m;
    __asm volatile("csrr %0, mstatus" : "=r"(m));
    return (uint8_t)((m & 8u) != 0u);
}

void WWDG_IRQHandler(void) MPB_IRQ;

/* ブリッジ (lib/mpb_bridge.c) を使っているときだけリンクされる点検関数。0 = 異常 */
int Mpb_Bridge_SafetyCheck(void) __attribute__((weak));

/* 全ゲート OFF: どの状態からでも, どこから呼んでもよい (割込み内・故障処理・リセット前)。
 * TIM1 の主出力 (MOE) を切り, PB8〜PB15 を「GPIO 出力 Low」に 1 回の書き込みでまとめて切り替える。
 * 上下とも Low (= 全 FET OFF, 惰性回転) で, 短絡ブレーキ (ローサイド ON) にもしない。 */
void Mpb_Gates_Off(void)
{
    RCC->PB2PCENR |= RCC_PB2Periph_GPIOB;
    if (RCC->PB2PCENR & RCC_PB2Periph_TIM1)
    {
        TIM1->BDTR &= (uint16_t)~TIM_MOE;          /* OSSI = 1 なので出力は休止レベル (Low) */
    }
    GPIOB->BCR = 0xFF00u;                          /* 出力データを先に Low */
    GPIOB->CFGHR = 0x33333333u;                    /* PB8〜PB15 = 出力 PP Low (AF を外す) */
}

uint8_t Mpb_ResetCause(void) { return s_cause; }

const char *Mpb_ResetCauseText(uint8_t c)
{
    if (c & MPB_RST_WDT) return "watchdog";
    if (c & MPB_RST_POWER) return "power-on";
    if (c & MPB_RST_PIN) return "reset pin";
    if (c & MPB_RST_SOFT) return "software";
    if (c & MPB_RST_LOWPOWER) return "low-power";
    return "unknown";
}

void Mpb_Wdt_ReadResetCause(void)
{
    uint32_t r = RCC->RSTSCKR;

    s_cause = (uint8_t)(((r & RCC_WWDGRSTF) ? MPB_RST_WDT : 0u) | ((r & RCC_PORRSTF) ? MPB_RST_POWER : 0u) |
                        ((r & RCC_PINRSTF) ? MPB_RST_PIN : 0u) | ((r & RCC_SFTRSTF) ? MPB_RST_SOFT : 0u) |
                        ((r & RCC_LPWRRSTF) ? MPB_RST_LOWPOWER : 0u));
    RCC->RSTSCKR |= RCC_RMVF;
}

void Mpb_Wdt_SetLimit(uint32_t ms)
{
    if (s_pending)
    {
        s_pending_ms = ms;
    }
    uint32_t n = (ms + WWDG_EWI_MS - 1u) / WWDG_EWI_MS;
    s_limit = (uint16_t)(n < 1u ? 1u : (n > 60000u ? 60000u : n));
    s_miss = 0;
}

void Mpb_Wdt_Start(uint32_t ms)
{
    if (s_on)
    {
        Mpb_Wdt_SetLimit(ms);
        return;
    }
    if (!irq_enabled())
    {
        /* FreeRTOS はスケジューラ開始まで割込みを止めている → EWI が動けないので, 最初に割込み許可で
         * Mpb_Wdt_Feed() が呼ばれたとき (= タスクが動き出したとき) に開始する */
        s_pending = 1;
        s_pending_ms = ms;
        return;
    }
    Mpb_Wdt_SetLimit(ms);
    RCC_PB1PeriphClockCmd(RCC_PB1Periph_WWDG, ENABLE);
    WWDG->CFGR = WWDG_Prescaler_8 | 0x7Fu;         /* 窓 = 0x7F: いつ更新してもよい */
    WWDG->STATR = 0;
    WWDG->CFGR |= (1u << 9);                       /* EWI */
    NVIC_SetPriority(WWDG_IRQn, 0);                /* 一番高い優先度 */
    NVIC_EnableIRQ(WWDG_IRQn);
    WWDG->CTLR = 0x80u | 0x7Fu;                    /* 開始 (以後リセットまで止められない) */
    s_on = 1;
}

uint8_t Mpb_Wdt_Running(void) { return s_on; }

void Mpb_Wdt_Feed(void)
{
    s_miss = 0;
    if (s_pending && irq_enabled())
    {
        s_pending = 0;
        Mpb_Wdt_Start(s_pending_ms);
    }
    else if (s_on && !irq_enabled())
    {
        WWDG->CTLR = 0x7Fu;                        /* 割込み禁止中の給餌は EWI が動けないので直接更新 */
    }
}

void WWDG_IRQHandler(void)
{
    WWDG->STATR = 0;                               /* EWIF を消す */
    if ((Mpb_Bridge_SafetyCheck && !Mpb_Bridge_SafetyCheck()) || ++s_miss > s_limit)
    {
        /* 異常: 先に全ゲート OFF。更新しないので 1 カウント (≤455µs) 後に WWDG がリセットする */
        Mpb_Gates_Off();
        __disable_irq();
        for (;;)
        {
            Mpb_Gates_Off();
        }
    }
    WWDG->CTLR = 0x7Fu;                            /* 更新 (WDGA は 1 のまま) */
}
