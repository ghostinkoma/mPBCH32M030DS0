/*
 * サンプル: I2C マスタ + 環境センサ — SHT3x / AHT20 / BMP280・BME280 / S-5851A を同じバスで読み, UART に出す
 *
 * 配線: SDA → J2-19 (I2C_SDA = PA14), SCL → J2-18 (I2C_SCL = PA15), 3.3V (J1-6), GND。
 *       プルアップ: モジュールの R114/R115 (4.7k) を実装するか, センサ基板のプルアップを使う。
 * つながっていないセンサは「応答なし」になり, 周期ごとに初期化からやり直す (抜き差ししても復帰する)。
 * どの処理も待たない: 変換待ち (SHT3x 16ms, AHT20 80ms, BMx280 10ms) は時刻の比較で行う。
 */
#include "config.h"         /* このスケッチの設定 (ピン・定数) */
#include "mpbfun.h"

static Mpb_Env s_env[4];

static void report(Mpb_Env *e)
{
    const Mpb_EnvReading *r = &e->r;

    if (!r->ok)
    {
        MPB_LOGW("%-7s @0x%02x: no response (errors %u)", Mpb_Env_Name(e), e->addr, e->errors);
        return;
    }
    Mpb_Log_Line('I', "%-7s @0x%02x: T %s C%s%s%s%s", Mpb_Env_Name(e), e->addr, Mpb_Log_Fixed(r->t_c100, 2),
                 (r->caps & MPB_ENV_CAP_H) ? "  RH " : "", (r->caps & MPB_ENV_CAP_H) ? Mpb_Log_Fixed(r->rh_100, 2) : "",
                 (r->caps & MPB_ENV_CAP_P) ? "  P hPa " : "",
                 (r->caps & MPB_ENV_CAP_P) ? Mpb_Log_Fixed((int32_t)r->p_pa, 2) : "");
}

void setup(void)
{
    Mpb_Time_Init();
    Mpb_Log_Init(0);
    Mpb_I2c_Init(CFG_I2C_HZ);
    Mpb_Env_Init(&s_env[0], MPB_ENV_SHT3X, CFG_ADDR_SHT3X);
    Mpb_Env_Init(&s_env[1], MPB_ENV_AHT20, CFG_ADDR_AHT20);
    Mpb_Env_Init(&s_env[2], MPB_ENV_BMX280, CFG_ADDR_BMX280);
    Mpb_Env_Init(&s_env[3], MPB_ENV_S5851A, CFG_ADDR_S5851A);
    for (uint8_t i = 0; i < 4; i++)
    {
        Mpb_Env_SetPeriod(&s_env[i], CFG_PERIOD_MS);
    }
    MPB_LOGI("i2c_sensors: scanning SHT3x/AHT20/BMx280/S-5851A every 2 s");
}

void loop(void)
{
    Mpb_I2c_Task();
    for (uint8_t i = 0; i < 4; i++)
    {
        if (Mpb_Env_Task(&s_env[i]))
        {
            report(&s_env[i]);
        }
    }
}
