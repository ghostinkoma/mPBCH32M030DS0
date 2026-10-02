/*
 * mpb_dc — ブラシ付き DC モーター
 * Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
 */
#include "mpb_dc.h"

typedef struct {
    Mpb_DcCfg  cfg;
    Mpb_DcMode mode;
    int16_t    target;      /* duty モードの目標 (±‰) */
    int16_t    duty;        /* 実際の duty (±‰) */
    int32_t    i_ref;       /* 電流モードの目標 [mA] */
    int32_t    integ;       /* PI の積分項 (‰ × 1000) */
    uint8_t    used;
    int8_t     dir;         /* STOP: 止める前の回転の向き (+1 / −1) */
    uint16_t   brake_mA;    /* STOP: 制動電流 */
    uint16_t   k;           /* 制動 (回生) の強さ 0〜1000: VBUS が上限を超えると下げる */
    uint16_t   n_low;       /* STOP: 止まったとみなすまでの連続回数 [ms] */
    uint32_t   vlim;        /* 回生で許す VBUS [mV] */
    uint32_t   hold_until;  /* BRAKE: この時刻で惰性へ (0 = ずっと保持) */
    uint8_t    regen, limited, short_ok;
} Dc;

static Dc s_m[2];
static uint32_t s_vbus_mv;
static uint32_t s_vnom;                 /* 回生していないときの VBUS (上限の基準) */
static uint32_t s_t_ms;

#define REGEN_THR_MA   100              /* これより大きい逆向き電流を回生とみなす */
#define VLIM_RISE_MV   1000u            /* 既定: 平常の VBUS からの上がり幅 */
#define STOP_DUTY_END  10               /* STOP: |duty| がこれ以下 (1%) で… */
#define STOP_END_MS    30u              /* …この時間続いたら停止とみなす */

/* レッグ番号: モーター 0 = HB0/HB1, モーター 1 = HB2/HB3 */
static void apply(uint8_t m)
{
    Dc *d = &s_m[m];
    uint8_t a = (uint8_t)(m * 2u), b = (uint8_t)(a + 1u);

    switch (d->mode)
    {
    case MPB_DC_COAST:
        Mpb_Bridge_Leg(a, MPB_LEG_FLOAT);
        Mpb_Bridge_Leg(b, MPB_LEG_FLOAT);
        break;
    case MPB_DC_BRAKE:
        Mpb_Bridge_Leg(a, 0);
        Mpb_Bridge_Leg(b, 0);
        break;
    default:
        if (d->duty >= 0)
        {
            Mpb_Bridge_Leg(a, d->duty);   /* 正転: A を PWM, B はローサイド ON */
            Mpb_Bridge_Leg(b, 0);
        }
        else
        {
            Mpb_Bridge_Leg(a, 0);
            Mpb_Bridge_Leg(b, (int16_t)-d->duty);
        }
        break;
    }
}

void Mpb_Dc_Init(uint8_t m, const Mpb_DcCfg *cfg)
{
    static const Mpb_DcCfg dflt = {0, 0, 2, 0, 0, 0};
    Dc *d;

    if (m > 1)
    {
        return;
    }
    d = &s_m[m];
    d->cfg = cfg ? *cfg : dflt;
    if (!d->cfg.kp) d->cfg.kp = 40;
    if (!d->cfg.ki) d->cfg.ki = 4;
    d->mode = MPB_DC_COAST;
    d->duty = d->target = 0;
    d->i_ref = d->integ = 0;
    d->k = 1000;
    d->hold_until = 0;
    d->used = 1;
    if (!s_vnom) s_vnom = Mpb_Vbus_mV();
    apply(m);
}

void Mpb_Dc_SetDuty(uint8_t m, int16_t duty)
{
    if (m > 1) return;
    if (duty > MPB_DUTY_FULL) duty = MPB_DUTY_FULL;
    if (duty < -MPB_DUTY_FULL) duty = -MPB_DUTY_FULL;
    if (s_m[m].mode != MPB_DC_DUTY)
    {
        if (s_m[m].mode == MPB_DC_COAST || s_m[m].mode == MPB_DC_BRAKE)
        {
            s_m[m].duty = 0;      /* 停止状態からは ramp で立ち上げる (回転中の duty はそのまま引き継ぐ) */
        }
        s_m[m].mode = MPB_DC_DUTY;
    }
    s_m[m].target = duty;
}

void Mpb_Dc_SetCurrent(uint8_t m, int32_t mA)
{
    if (m > 1) return;
    if (s_m[m].mode != MPB_DC_CURRENT)
    {
        s_m[m].integ = (int32_t)s_m[m].duty * 1000;   /* 今の duty から滑らかに移る */
        s_m[m].mode = MPB_DC_CURRENT;
    }
    s_m[m].i_ref = mA;
}

void Mpb_Dc_Coast(uint8_t m)
{
    if (m > 1) return;
    s_m[m].mode = MPB_DC_COAST;
    s_m[m].duty = s_m[m].target = 0;
    apply(m);
}

void Mpb_Dc_Brake(uint8_t m)
{
    if (m > 1) return;
    s_m[m].mode = MPB_DC_BRAKE;
    s_m[m].duty = s_m[m].target = 0;
    s_m[m].hold_until = 0;
    apply(m);
}

static uint32_t vlim_of(const Dc *d)
{
    uint32_t lim = s_vnom + VLIM_RISE_MV, cap = MPB_VBUS_MAX_MV - 1000u;

    if (d->cfg.brake_vbus_max_mV)
    {
        lim = d->cfg.brake_vbus_max_mV;
    }
    return lim < cap ? lim : cap;
}

static void enter_hold(Dc *d, uint32_t now)
{
    uint16_t hold = d->cfg.brake_hold_ms ? d->cfg.brake_hold_ms : 300u;
    d->mode = MPB_DC_BRAKE;
    d->duty = d->target = 0;
    d->hold_until = (now + hold) ? now + hold : 1u;
}

void Mpb_Dc_Stop(uint8_t m, uint16_t brake_mA)
{
    Dc *d;
    int32_t i;

    if (m > 1) return;
    d = &s_m[m];
    if (d->mode == MPB_DC_COAST || d->mode == MPB_DC_BRAKE || d->mode == MPB_DC_STOP)
    {
        return;                  /* 惰性中は向きが分からないので惰性のまま (いきなり短絡すると大電流になりうる) */
    }
    i = Mpb_Dc_Current_mA(m);
    d->dir = d->duty > 0 ? 1 : (d->duty < 0 ? -1 : (i > REGEN_THR_MA ? 1 : (i < -REGEN_THR_MA ? -1 : 0)));
    if (!d->dir || !Mpb_Bridge_CurrentReady())
    {
        enter_hold(d, Mpb_Millis());    /* もう止まっている */
        apply(m);
        return;
    }
    d->brake_mA = brake_mA ? brake_mA : 500u;
    d->vlim = vlim_of(d);
    d->k = 0;                            /* 回生はゆっくり立ち上げる (母線の容量は小さい) */
    d->short_ok = 0;
    d->n_low = 0;
    d->integ = (int32_t)d->duty * 1000;  /* 今の duty から滑らかに */
    d->mode = MPB_DC_STOP;
}

uint8_t Mpb_Dc_Regen(uint8_t m) { return m < 2 ? s_m[m].regen : 0; }
uint8_t Mpb_Dc_VbusLimited(uint8_t m) { return m < 2 ? s_m[m].limited : 0; }

Mpb_DcMode Mpb_Dc_Mode(uint8_t m) { return m < 2 ? s_m[m].mode : MPB_DC_COAST; }
int16_t Mpb_Dc_Duty(uint8_t m) { return m < 2 ? s_m[m].duty : 0; }
uint32_t Mpb_Dc_VbusMv(void) { return s_vbus_mv; }

int32_t Mpb_Dc_Current_mA(uint8_t m)
{
    /* シャントは各レッグのローサイドの帰路。PWM の山では両ローサイド ON で,
     * 正転の電流は B レッグに +I, A レッグに −I が流れる (ソース → GND を正) */
    if (m == 0)
    {
        return (Mpb_Bridge_Current_mA(1) - Mpb_Bridge_Current_mA(0)) / 2;
    }
    return -Mpb_Bridge_Current_mA(1);   /* モーター 1: IB = HB2 (JP5=2-3) */
}

int32_t Mpb_Dc_Rpm(uint8_t m)
{
    Dc *d;
    int32_t mv;

    if (m > 1 || !s_m[m].cfg.kv_rpm_per_v) return 0;
    d = &s_m[m];
    mv = (int32_t)s_vbus_mv * d->duty / MPB_DUTY_FULL;                      /* 平均印加電圧 */
    mv -= Mpb_Dc_Current_mA(m) * (int32_t)d->cfg.r_mohm / 1000;             /* 巻線の電圧降下 */
    if ((d->duty > 0 && mv < 0) || (d->duty < 0 && mv > 0)) mv = 0;
    return mv * (int32_t)d->cfg.kv_rpm_per_v / 1000;
}

static int16_t clamp_duty(int32_t v)
{
    int32_t mx = Mpb_Bridge_MaxDuty();
    return (int16_t)(v > mx ? mx : (v < -mx ? -mx : v));
}

/* 電流 PI: 目標 ref [mA] に対する duty を返す (飽和中は積分しない) */
static int16_t pi_step(Dc *d, int32_t ref, int32_t i)
{
    int32_t e = ref - i, out;
    int16_t duty;

    d->integ += e * (int32_t)d->cfg.ki;
    if (d->integ > 1000000) d->integ = 1000000;
    if (d->integ < -1000000) d->integ = -1000000;
    out = (e * (int32_t)d->cfg.kp + d->integ) / 1000;
    duty = clamp_duty(out);
    if (duty != out)
    {
        d->integ -= e * (int32_t)d->cfg.ki;
    }
    return duty;
}

/* 回生の強さ k (0〜1000) を VBUS で調整する: 上限を超えたら素早く下げ, 余裕が戻ったらゆっくり上げる */
static void regen_limit(Dc *d, uint32_t v)
{
    if (v + 200u > d->vlim)
    {
        d->k = d->k > 200u ? (uint16_t)(d->k - 200u) : 0u;      /* 上限の 0.2V 手前から素早く弱める */
    }
    else if (v + 500u < d->vlim && d->k < 1000u)
    {
        d->k = (uint16_t)(d->k + 2u);                            /* 0.5 秒かけて最大まで */
    }
    d->limited = d->k < 1000u;
}

void Mpb_Dc_Task(void)
{
    uint32_t now = Mpb_Millis(), v;
    uint8_t not_idle = 0;

    if (now == s_t_ms)
    {
        return;                              /* 1ms ごと */
    }
    s_t_ms = now;
    Mpb_Bridge_Vdd8Auto();
    v = Mpb_Bridge_CurrentReady() ? Mpb_Bridge_Vbus_mV() : Mpb_Vbus_mV();
    s_vbus_mv = v;
    for (uint8_t m = 0; m < 2; m++)
    {
        Dc *d = &s_m[m];
        int32_t i = Mpb_Dc_Current_mA(m);

        if (!d->used)
        {
            continue;
        }
        if (Mpb_Bridge_Faulted())
        {
            d->mode = MPB_DC_COAST;          /* 故障: ブリッジが全 FET OFF にしている。状態も惰性に合わせる */
            d->duty = d->target = 0;
            continue;
        }
        d->regen = (uint8_t)((d->duty > 0 && i < -REGEN_THR_MA) || (d->duty < 0 && i > REGEN_THR_MA));
        /* 平常の VBUS を学習してよいのは, 母線から電力を取っているとき (力行) か止まっているときだけ */
        not_idle |= (uint8_t)!(d->mode == MPB_DC_COAST || (d->mode == MPB_DC_BRAKE && !d->hold_until) ||
                                (d->duty > 0 && i > REGEN_THR_MA) || (d->duty < 0 && i < -REGEN_THR_MA));
        if (d->mode != MPB_DC_STOP)
        {
            d->vlim = vlim_of(d);
        }
        if (d->mode == MPB_DC_DUTY)
        {
            int32_t step = d->cfg.ramp_per_ms ? d->cfg.ramp_per_ms : MPB_DUTY_FULL;
            int32_t tgt = d->target;
            if (tgt > d->duty + step) tgt = d->duty + step;
            if (tgt < d->duty - step) tgt = d->duty - step;
            /* 電流制限: 電流と逆向きに duty を動かす。力行 (電流と duty が同じ向き) なら 0 側へ,
             * 回生・短絡 (逆向き) なら逆起電力の側へ (0 へ寄せると制動電流が増えるため) */
            if (d->cfg.i_limit_mA && (i > (int32_t)d->cfg.i_limit_mA || i < -(int32_t)d->cfg.i_limit_mA))
            {
                int32_t over = (i > 0 ? i : -i) - (int32_t)d->cfg.i_limit_mA;
                int32_t delta = 5 + over * (int32_t)d->cfg.kp / 1000;
                tgt = d->duty + (i > 0 ? -delta : delta);
            }
            /* 減速の保護 (ランプなしで急に 0 にしても安全に):
             *  (a) 下げすぎない: 逆起電力の推定から, 制動電流が上限 (i_limit, 既定 3A) を超えない duty より下げない
             *      (いきなり 0 = 短絡にすると逆起電力 ÷ 巻線抵抗の大電流が流れ, その巻線のエネルギーが母線へ戻る)
             *  (b) 減速ストール防止: 回生で VBUS が上限を超えたら duty を少し上げ, 母線の電力をモーターへ戻す */
            d->limited = 0;
            if (!d->regen && !((d->duty > 0 && tgt < d->duty) || (d->duty < 0 && tgt > d->duty)))
            {
                d->k = 0;                        /* 減速していない: 次の減速は回生 0 から立ち上げる */
            }
            if (d->duty != 0 && ((d->duty > 0 && tgt < d->duty) || (d->duty < 0 && tgt > d->duty)) && v > 1000u)
            {
                int32_t mag = d->duty > 0 ? d->duty : -d->duty, t = d->duty > 0 ? tgt : -tgt, floor;
                int32_t isgn = d->duty > 0 ? i : -i;                              /* 回転の向きに直した電流 */
                int32_t r = (int32_t)d->cfg.r_mohm;
                int32_t bemf = (int32_t)v * mag / MPB_DUTY_FULL - isgn * r / 1000; /* 逆起電力の推定 [mV] */
                int32_t d_eq = bemf * MPB_DUTY_FULL / (int32_t)v;                  /* 電流 0 になる duty */
                if (v > d->vlim)
                {
                    floor = d_eq + 5;            /* (b) 母線が上限: 回生をやめ, 少しだけ母線から取る */
                    d->limited = 1;
                }
                else if (r)
                {
                    /* (a) 制動電流 ≤ ilim × k。k は回生の強さで, 減速を始めると 0 からゆっくり上がり,
                     *     VBUS が上限に近づくとすぐ下がる (停止 STOP と同じ regen_limit) */
                    int32_t ilim = d->cfg.i_limit_mA ? (int32_t)d->cfg.i_limit_mA : 3000;
                    regen_limit(d, v);
                    ilim = ilim * (int32_t)d->k / 1000;
                    floor = (bemf - ilim * r / 1000) * MPB_DUTY_FULL / (int32_t)v;
                }
                else
                {
                    floor = d->cfg.ramp_per_ms ? 0 : mag - 10;                     /* 巻線抵抗が不明: 1%/ms まで */
                }
                if (t < floor) t = floor;
                if (t < 0) t = 0;
                tgt = d->duty > 0 ? t : -t;
            }
            d->duty = clamp_duty(tgt);
        }
        else if (d->mode == MPB_DC_CURRENT && Mpb_Bridge_CurrentReady())
        {
            int32_t ref = d->i_ref;
            if (d->cfg.i_limit_mA)
            {
                if (ref > (int32_t)d->cfg.i_limit_mA) ref = d->cfg.i_limit_mA;
                if (ref < -(int32_t)d->cfg.i_limit_mA) ref = -(int32_t)d->cfg.i_limit_mA;
            }
            /* 目標が回転と逆向き (= 制動) のときだけ, VBUS に応じて弱める */
            regen_limit(d, v);
            if ((d->duty > 0 && ref < 0) || (d->duty < 0 && ref > 0))
            {
                ref = ref * (int32_t)d->k / 1000;
            }
            d->duty = pi_step(d, ref, i);
        }
        else if (d->mode == MPB_DC_STOP)
        {
            int32_t ref, imax = d->cfg.i_limit_mA ? (int32_t)d->cfg.i_limit_mA : 2 * (int32_t)d->brake_mA;
            int16_t duty;

            /* 1) 逆起電力 ÷ 巻線抵抗 (= 短絡したときの電流) が許容電流以下なら, もう短絡ブレーキでよい:
             *    母線へ電力を返さず (VBUS が上がらない), 巻線の熱で止まる */
            if (d->cfg.r_mohm && d->short_ok < 3u)
            {
                int32_t bemf_mv = (int32_t)v * d->duty / MPB_DUTY_FULL - i * (int32_t)d->cfg.r_mohm / 1000;
                int32_t ishort = bemf_mv * 1000 / (int32_t)d->cfg.r_mohm;
                if (ishort < 0) ishort = -ishort;
                d->short_ok = ishort <= imax ? (uint8_t)(d->short_ok + 1u) : 0u;
            }
            if (d->short_ok >= 3u)
            {
                d->duty = 0;                     /* 短絡ブレーキ (両ローサイド ON) */
                d->integ = 0;
            }
            else
            {
                /* 2) まだ速い: 回生で制動。強さ k はゆっくり上げ, VBUS が上限を超えたらすぐ下げる */
                regen_limit(d, v);
                ref = -(int32_t)d->dir * (int32_t)d->brake_mA * (int32_t)d->k / 1000;
                duty = pi_step(d, ref, i);
                /* 逆転させない (プラギング禁止): duty は止める前の向きの側だけ。0 = 短絡ブレーキ */
                if (d->dir > 0 && duty < 0) { duty = 0; d->integ = 0; }
                if (d->dir < 0 && duty > 0) { duty = 0; d->integ = 0; }
                d->duty = duty;
            }
            /* 短絡中で電流もほぼ 0 = 止まった → 保持 → 惰性 */
            if ((d->duty <= STOP_DUTY_END && d->duty >= -STOP_DUTY_END) &&
                (i < (int32_t)d->brake_mA / 4 && i > -(int32_t)d->brake_mA / 4))
            {
                if (++d->n_low >= STOP_END_MS)
                {
                    enter_hold(d, now);
                }
            }
            else
            {
                d->n_low = 0;
            }
        }
        else if (d->mode == MPB_DC_BRAKE && d->hold_until && (int32_t)(now - d->hold_until) >= 0)
        {
            d->mode = MPB_DC_COAST;          /* 保持の時間が過ぎたら全 FET OFF */
            d->duty = d->target = 0;
            d->hold_until = 0;
        }
        apply(m);
    }
    if (!not_idle)
    {
        /* 回生していないときの VBUS を基準にする。下がるのはすぐ, 上がるのはゆっくり (2V/s) 追う
         * (回生で上がった電圧を「平常」と取り違えないため。USB-PD の電圧切り替えには数秒で追いつく) */
        if (v < s_vnom) s_vnom = v;
        else s_vnom += (v - s_vnom) > 2u ? 2u : (v - s_vnom);
    }
}
