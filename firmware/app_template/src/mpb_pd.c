/*
 * USB-PD シンクのポリシーと給電パス (U5 LM74700 + Q10) の制御
 *
 *  1. PD ソースの Source_Capabilities から「min_mV ≤ V ≤ max_mV で最も高い電圧」の固定 PDO を選ぶ
 *     (同電圧なら電流の大きい方)。該当なしなら 5V を要求し、モーター給電はしない。
 *  2. PS_RDY 受信後、USB_VBUS_SNS (PA2) で契約電圧 ±10% を確認してから PD_PWR_EN (PC3) = High。
 *  3. USB VBUS が 3.5V 未満 (抜去) / 契約電圧から外れたら即 OFF。
 *     MCU リセット (PB4 OVP を含む) 中は R6 プルダウンで OFF。
 *  4. J1 と同時接続時は理想ダイオード OR により電圧の高い側が供給する (逆流なし)。
 */
#include <string.h>
#include "mpb.h"
#include "pd_process.h"

static Mpb_PdPolicy s_pol = {15000u, 8000u, 3000u};
static Mpb_PdStatus s_st;
static uint16_t s_req_mV, s_req_mA;
static uint32_t s_last_ms;

void Mpb_PD_PowerEnable(uint8_t on)
{
    GPIO_WriteBit(MPB_PDEN_PORT, MPB_PDEN_PIN, on ? Bit_SET : Bit_RESET);
    s_st.power_enabled = on ? 1u : 0u;
}

void Mpb_PD_Init(const Mpb_PdPolicy *policy)
{
    GPIO_InitTypeDef g = {0};

    if (policy != NULL)
    {
        s_pol = *policy;
    }
    if (s_pol.max_mV > 15000u)
    {
        s_pol.max_mV = 15000u;    /* ハード上限: TVS SMBJ16A (Vwm 16V) / MOSFET 30V */
    }
    memset(&s_st, 0, sizeof(s_st));

    RCC_PB2PeriphClockCmd(RCC_PB2Periph_GPIOC, ENABLE);
    g.GPIO_Pin = MPB_PDEN_PIN;                /* PD_PWR_EN */
    g.GPIO_Mode = GPIO_Mode_Out_PP;
    g.GPIO_Speed = GPIO_Speed_30MHz;
    GPIO_Init(MPB_PDEN_PORT, &g);
    Mpb_PD_PowerEnable(0);

    PD_Init();                                /* PA0/PA1 = CC, ISINK 有効化 (PD PHY に必要) */
    s_last_ms = Mpb_Millis();
}

const Mpb_PdStatus *Mpb_PD_Status(void)
{
    return &s_st;
}

uint8_t Mpb_PD_SelectPdo(const uint8_t *srccap, uint8_t pdo_len)
{
    uint8_t best = 1;
    uint16_t best_mV = 0, best_mA = 0;

    for (uint8_t i = 1; i <= pdo_len; i++)
    {
        uint16_t mA, mV;

        PD_PDO_Analyse(i, (uint8_t *)srccap, &mA, &mV);
        if (mV < s_pol.min_mV || mV > s_pol.max_mV)
        {
            continue;
        }
        if (mV > best_mV || (mV == best_mV && mA > best_mA))
        {
            best = i;
            best_mV = mV;
            best_mA = mA;
        }
    }
    if (best_mV == 0u)
    {
        PD_PDO_Analyse(1, (uint8_t *)srccap, &best_mA, &best_mV);   /* 5V のみ: 給電はしない */
        best = 1;
    }
    s_req_mV = best_mV;
    s_req_mA = best_mA;
    s_st.attached = 1;
    return best;
}

void Mpb_PD_OnPsRdy(void)
{
    uint32_t v = Mpb_UsbVbus_mV();

    s_st.contract = 1;
    s_st.mV = s_req_mV;
    s_st.mA = s_req_mA;
    if (s_req_mV >= s_pol.min_mV && v * 10u >= s_req_mV * 9u && v * 10u <= s_req_mV * 11u)
    {
        Mpb_PD_PowerEnable(1);
    }
}

void Mpb_PD_OnDetach(void)
{
    Mpb_PD_PowerEnable(0);
    memset(&s_st, 0, sizeof(s_st));
}

void Mpb_PD_Task(void)
{
    uint32_t now = Mpb_Millis();
    uint32_t dlt = now - s_last_ms;
    uint32_t v;

    if (dlt == 0u)
    {
        return;
    }
    s_last_ms = now;
    Tmr_Ms_Dlt = (UINT8)(dlt > 255u ? 255u : dlt);
    PD_Ctl.Det_Timer += Tmr_Ms_Dlt;
    if (PD_Ctl.Det_Timer > 4)
    {
        PD_Ctl.Det_Timer = 0;
        PD_Det_Proc();
    }
    PD_Main_Proc();

    /* 抜去検出は VBUS で行う (WCH サンプルの注記どおり) */
    v = Mpb_UsbVbus_mV();
    if (PD_Ctl.Flag.Bit.Connected && v < 3500u)
    {
        PD_Ctl.Flag.Bit.Connected = 0;
        PD_Ctl.PD_State = STA_DISCONNECT;
        Mpb_PD_OnDetach();
    }
    /* 給電中の電圧逸脱 (ソース異常・ハードリセット) で即遮断 */
    if (s_st.power_enabled && (v * 10u < s_st.mV * 8u || v * 10u > s_st.mV * 12u))
    {
        Mpb_PD_PowerEnable(0);
    }
}
