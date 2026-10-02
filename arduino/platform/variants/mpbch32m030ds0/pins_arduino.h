/*
 * pins_arduino.h — mPBCH32M030DS0 の端子番号 (番号 = ポート × 16 + ビット: PA0 = 0, PB0 = 16, PC0 = 32)
 * モジュールの端子 (J1 / J2) との対応はリポジトリの README を参照。
 */
#ifndef PINS_ARDUINO_H
#define PINS_ARDUINO_H

enum {
    PA0 = 0, PA1, PA2, PA3, PA4, PA5, PA6, PA7, PA8, PA9, PA10, PA11, PA12, PA13, PA14, PA15,
    PB0 = 16, PB1, PB2, PB3, PB4, PB5, PB6, PB7, PB8, PB9, PB10, PB11, PB12, PB13, PB14, PB15,
    PC0 = 32, PC1, PC2, PC3, PC4, PC5, PC6, PC7
};

#define LED_BUILTIN     PC4     /* 状態 LED D3 (Low で点灯) — USER ボタン SW2 と共用 */
#define BUTTON_BUILTIN  PC4     /* 押すと Low */
#define PIN_HALL_A      PA5     /* J1-14 (JP2 = 2-3 で外部入力) */
#define PIN_HALL_C      PA6     /* J1-16 (JP4 = 2-3) */
#define PIN_HALL_B      PA7     /* JP3 = 2-3 */
#define PIN_UART_RX     PC2     /* J2-2 */
#define PIN_UART_TX     PC1     /* J2-3 */
#define PIN_SDA         PA14    /* J2-19 */
#define PIN_SCL         PA15    /* J2-18 */
#define PIN_HV_IO       PC5     /* High = VHV (軽負荷のプッシュプル) */

#endif
