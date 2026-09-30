/*
 * mpb_env — I2C 環境センサ (SHT3x / AHT20 / BMP280・BME280 / S-5851A)
 * 換算式は各データシートの整数版。
 * Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
 */
#include "mpb_env.h"
#include "mpb.h"

enum { ST_SETUP = 0, ST_SETUP_WAIT, ST_IDLE, ST_TRIG, ST_TRIG_WAIT, ST_CONV, ST_READ, ST_READ_WAIT };

static Mpb_Env *s_owner;                 /* いま I2C を使っているセンサ */

/* 転送を予約 (I2C が空いていなければ 0) */
static uint8_t xfer(Mpb_Env *e, uint8_t ntx, uint8_t nrx)
{
    if (s_owner || !Mpb_I2c_Start(e->addr, e->cmd, ntx, e->buf, nrx))
    {
        return 0;
    }
    s_owner = e;
    return 1;
}

/* 自分の転送が終わったら 1 (*ok に成否) */
static uint8_t xdone(Mpb_Env *e, uint8_t *ok)
{
    if (s_owner != e || !Mpb_I2c_Done())
    {
        return 0;
    }
    *ok = (Mpb_I2c_Result() == MPB_I2C_OK);
    s_owner = 0;
    return 1;
}

static uint8_t crc8_sht(const uint8_t *d, uint8_t n)
{
    uint8_t c = 0xFF;
    for (uint8_t i = 0; i < n; i++)
    {
        c ^= d[i];
        for (uint8_t b = 0; b < 8; b++) c = (uint8_t)((c & 0x80u) ? ((uint32_t)c << 1) ^ 0x31u : (uint32_t)c << 1);
    }
    return c;
}

void Mpb_Env_Init(Mpb_Env *e, Mpb_EnvType type, uint8_t addr)
{
    static const uint8_t dflt[] = {0x44, 0x38, 0x76, 0x48};

    *e = (Mpb_Env){0};
    e->type = type;
    e->addr = addr ? addr : dflt[type & 3];
    e->period_ms = 1000;
    e->state = ST_SETUP;
    e->t_next = Mpb_Millis();
}

void Mpb_Env_SetPeriod(Mpb_Env *e, uint16_t ms) { e->period_ms = ms ? ms : 1; }

const char *Mpb_Env_Name(const Mpb_Env *e)
{
    switch (e->type)
    {
    case MPB_ENV_SHT3X: return "SHT3x";
    case MPB_ENV_AHT20: return "AHT20";
    case MPB_ENV_BMX280: return e->is_bme ? "BME280" : "BMP280";
    default: return "S-5851A";
    }
}

/* ------------------------------------------------ 初期化の手順 (種類ごと) ----------- */
/* 戻り値: 0 = 続く (次の手へ), 1 = 初期化完了 */
static uint8_t setup_step(Mpb_Env *e, uint8_t step, uint8_t *ntx, uint8_t *nrx, uint32_t *wait)
{
    *wait = 0;
    switch (e->type)
    {
    case MPB_ENV_AHT20:
        if (step == 0) { e->cmd[0] = 0xBE; e->cmd[1] = 0x08; e->cmd[2] = 0x00; *ntx = 3; *nrx = 0; *wait = 10; return 0; }
        return 1;
    case MPB_ENV_BMX280:
        if (step == 0) { e->cmd[0] = 0xD0; *ntx = 1; *nrx = 1; return 0; }                /* chip id */
        if (step == 1) { e->cmd[0] = 0x88; *ntx = 1; *nrx = 24; return 0; }               /* T1〜P9 */
        if (step == 2 && e->is_bme) { e->cmd[0] = 0xA1; *ntx = 1; *nrx = 1; return 0; }  /* H1 */
        if (step == 3 && e->is_bme) { e->cmd[0] = 0xE1; *ntx = 1; *nrx = 7; return 0; }  /* H2〜H6 */
        if (step == 4 && e->is_bme) { e->cmd[0] = 0xF2; e->cmd[1] = 0x01; *ntx = 2; *nrx = 0; return 0; }  /* 湿度 ×1 */
        return 1;
    default:
        return 1;                                 /* SHT3x / S-5851A: 初期化不要 */
    }
}

/* 初期化の各手の結果を取り込む */
static void setup_result(Mpb_Env *e, uint8_t step)
{
    const uint8_t *b = e->buf;

    if (e->type != MPB_ENV_BMX280) return;
    if (step == 0) e->is_bme = (b[0] == 0x60);
    if (step == 1)
    {
        e->T1 = (uint16_t)(b[1] << 8 | b[0]); e->T2 = (int16_t)(b[3] << 8 | b[2]); e->T3 = (int16_t)(b[5] << 8 | b[4]);
        e->P1 = (uint16_t)(b[7] << 8 | b[6]); e->P2 = (int16_t)(b[9] << 8 | b[8]); e->P3 = (int16_t)(b[11] << 8 | b[10]);
        e->P4 = (int16_t)(b[13] << 8 | b[12]); e->P5 = (int16_t)(b[15] << 8 | b[14]); e->P6 = (int16_t)(b[17] << 8 | b[16]);
        e->P7 = (int16_t)(b[19] << 8 | b[18]); e->P8 = (int16_t)(b[21] << 8 | b[20]); e->P9 = (int16_t)(b[23] << 8 | b[22]);
    }
    if (step == 2) e->H1 = b[0];
    if (step == 3)
    {
        e->H2 = (int16_t)(b[1] << 8 | b[0]);
        e->H3 = b[2];
        e->H4 = (int16_t)((int16_t)(int8_t)b[3] * 16 | (b[4] & 0x0F));
        e->H5 = (int16_t)((int16_t)(int8_t)b[5] * 16 | (b[4] >> 4));
        e->H6 = (int8_t)b[6];
    }
}

/* ------------------------------------------------ 測定 ------------------------------- */
static void trig_cmd(Mpb_Env *e, uint8_t *ntx, uint32_t *wait)
{
    switch (e->type)
    {
    case MPB_ENV_SHT3X: e->cmd[0] = 0x24; e->cmd[1] = 0x00; *ntx = 2; *wait = 16; break;   /* 高精度, ストレッチなし */
    case MPB_ENV_AHT20: e->cmd[0] = 0xAC; e->cmd[1] = 0x33; e->cmd[2] = 0x00; *ntx = 3; *wait = 80; break;
    case MPB_ENV_BMX280: e->cmd[0] = 0xF4; e->cmd[1] = 0x25; *ntx = 2; *wait = 10; break;  /* T×1, P×1, 強制モード */
    default: *ntx = 0; *wait = 0; break;                                                    /* S-5851A: 連続変換 */
    }
}

static void read_cmd(Mpb_Env *e, uint8_t *ntx, uint8_t *nrx)
{
    switch (e->type)
    {
    case MPB_ENV_SHT3X: *ntx = 0; *nrx = 6; break;
    case MPB_ENV_AHT20: *ntx = 0; *nrx = 7; break;
    case MPB_ENV_BMX280: e->cmd[0] = 0xF7; *ntx = 1; *nrx = e->is_bme ? 8 : 6; break;
    default: e->cmd[0] = 0x00; *ntx = 1; *nrx = 2; break;
    }
}

static uint8_t convert(Mpb_Env *e)
{
    const uint8_t *b = e->buf;
    Mpb_EnvReading *r = &e->r;

    switch (e->type)
    {
    case MPB_ENV_SHT3X:
    {
        if (crc8_sht(b, 2) != b[2] || crc8_sht(b + 3, 2) != b[5]) return 0;
        uint32_t t = (uint32_t)(b[0] << 8 | b[1]), h = (uint32_t)(b[3] << 8 | b[4]);
        r->t_c100 = (int16_t)(-4500 + (int32_t)(17500u * t / 65535u));
        r->rh_100 = (uint16_t)(10000u * h / 65535u);
        r->caps = MPB_ENV_CAP_T | MPB_ENV_CAP_H;
        return 1;
    }
    case MPB_ENV_AHT20:
    {
        if (b[0] & 0x80u) return 0;               /* 変換中 */
        uint32_t h = ((uint32_t)b[1] << 12) | ((uint32_t)b[2] << 4) | (b[3] >> 4);
        uint32_t t = (((uint32_t)b[3] & 0x0Fu) << 16) | ((uint32_t)b[4] << 8) | b[5];
        r->rh_100 = (uint16_t)((uint64_t)h * 10000u >> 20);
        r->t_c100 = (int16_t)((int32_t)((uint64_t)t * 20000u >> 20) - 5000);
        r->caps = MPB_ENV_CAP_T | MPB_ENV_CAP_H;
        return 1;
    }
    case MPB_ENV_BMX280:
    {
        int32_t adc_p = (int32_t)((uint32_t)b[0] << 12 | (uint32_t)b[1] << 4 | b[2] >> 4);
        int32_t adc_t = (int32_t)((uint32_t)b[3] << 12 | (uint32_t)b[4] << 4 | b[5] >> 4);
        int32_t v1, v2, tf;
        int64_t p1, p2, p;

        if (adc_t == 0x80000) return 0;           /* 未変換 */
        v1 = ((((adc_t >> 3) - ((int32_t)e->T1 << 1))) * e->T2) >> 11;
        v2 = (((((adc_t >> 4) - (int32_t)e->T1) * ((adc_t >> 4) - (int32_t)e->T1)) >> 12) * e->T3) >> 14;
        tf = v1 + v2;
        r->t_c100 = (int16_t)((tf * 5 + 128) >> 8);
        p1 = (int64_t)tf - 128000;
        p2 = p1 * p1 * e->P6;
        p2 += (p1 * e->P5) << 17;
        p2 += (int64_t)e->P4 << 35;
        p1 = ((p1 * p1 * e->P3) >> 8) + ((p1 * e->P2) << 12);
        p1 = ((((int64_t)1) << 47) + p1) * e->P1 >> 33;
        if (p1 == 0) return 0;
        p = 1048576 - adc_p;
        p = (((p << 31) - p2) * 3125) / p1;
        p1 = ((int64_t)e->P9 * (p >> 13) * (p >> 13)) >> 25;
        p2 = ((int64_t)e->P8 * p) >> 19;
        p = ((p + p1 + p2) >> 8) + ((int64_t)e->P7 << 4);   /* Q24.8 [Pa] */
        r->p_pa = (uint32_t)(p >> 8);
        r->caps = MPB_ENV_CAP_T | MPB_ENV_CAP_P;
        if (e->is_bme)
        {
            int32_t adc_h = (int32_t)(b[6] << 8 | b[7]);
            int32_t x = tf - 76800;
            x = (((((adc_h << 14) - (((int32_t)e->H4) << 20) - (((int32_t)e->H5) * x)) + 16384) >> 15) *
                 (((((((x * (int32_t)e->H6) >> 10) * (((x * (int32_t)e->H3) >> 11) + 32768)) >> 10) + 2097152) *
                   (int32_t)e->H2 + 8192) >> 14));
            x = x - (((((x >> 15) * (x >> 15)) >> 7) * (int32_t)e->H1) >> 4);
            if (x < 0) x = 0;
            if (x > 419430400) x = 419430400;
            r->rh_100 = (uint16_t)(((uint32_t)(x >> 12) * 100u) >> 10);   /* Q22.10 %RH → 0.01% */
            r->caps |= MPB_ENV_CAP_H;
        }
        return 1;
    }
    default:
    {
        int16_t raw = (int16_t)(b[0] << 8 | b[1]);          /* 12bit 左詰め, 0.0625℃/LSB */
        r->t_c100 = (int16_t)(((int32_t)(raw >> 4) * 625) / 100);
        r->caps = MPB_ENV_CAP_T;
        return 1;
    }
    }
}

uint8_t Mpb_Env_Task(Mpb_Env *e)
{
    uint32_t now = Mpb_Millis(), wait;
    uint8_t ntx = 0, nrx = 0, ok;

    Mpb_I2c_Task();
    switch (e->state)
    {
    case ST_SETUP:                                /* buf[25] を初期化の手番号に使う */
        if ((int32_t)(now - e->t_next) < 0) break;
        if (setup_step(e, e->buf[25], &ntx, &nrx, &wait))
        {
            e->present = 1;
            e->state = ST_IDLE;
            break;
        }
        if (xfer(e, ntx, nrx))
        {
            e->t_wait = wait;
            e->state = ST_SETUP_WAIT;
        }
        break;
    case ST_SETUP_WAIT:
        if (xdone(e, &ok))
        {
            uint8_t step = e->buf[25];
            if (!ok)
            {
                e->buf[25] = 0;                   /* 応答なし: 周期ごとに初期化からやり直す */
                e->errors++;
                e->r.ok = 0;
                e->t_next = now + e->period_ms;
                e->state = ST_SETUP;
                return 1;
            }
            setup_result(e, step);
            e->buf[25] = (uint8_t)(step + 1u);
            e->t_next = now + e->t_wait;
            e->state = ST_SETUP;
        }
        break;
    case ST_IDLE:
        if ((int32_t)(now - e->t_next) >= 0)
        {
            e->t_next = now + e->period_ms;
            e->state = ST_TRIG;
        }
        break;
    case ST_TRIG:
        trig_cmd(e, &ntx, &wait);
        if (ntx == 0)
        {
            e->state = ST_READ;
            break;
        }
        if (xfer(e, ntx, 0))
        {
            e->t_wait = now + wait;
            e->state = ST_TRIG_WAIT;
        }
        break;
    case ST_TRIG_WAIT:
        if (xdone(e, &ok))
        {
            e->state = ok ? ST_CONV : ST_IDLE;
            if (!ok) { e->r.ok = 0; e->errors++; e->state = ST_SETUP; e->buf[25] = 0; return 1; }
        }
        break;
    case ST_CONV:
        if ((int32_t)(now - e->t_wait) >= 0) e->state = ST_READ;
        break;
    case ST_READ:
        read_cmd(e, &ntx, &nrx);
        if (xfer(e, ntx, nrx)) e->state = ST_READ_WAIT;
        break;
    case ST_READ_WAIT:
        if (xdone(e, &ok))
        {
            e->state = ST_IDLE;
            e->r.ok = ok && convert(e);
            if (!e->r.ok) e->errors++;
            return 1;
        }
        break;
    default:
        e->state = ST_SETUP;
        break;
    }
    return 0;
}
