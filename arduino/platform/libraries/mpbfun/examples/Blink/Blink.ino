/*
 * Blink — Arduino の書き方そのままの例 (状態 LED D3 = PC4, Low で点灯)
 * Serial は UART TX (PC1 / J2-3, 460800bps)。USB-C からの書き込み要求は delay() の中でも受け付ける。
 * モーターや LED のライブラリ (mpbfun) を使うときは delay() を使わず, millis() で間隔を測る
 * (ライブラリの *_Task() を loop() で毎回呼ぶため)。他のサンプル (ファイル → スケッチ例 → mpbfun) を参照。
 */

struct Counter {                 // 大域オブジェクトのコンストラクタも動く
    uint32_t n;
    Counter() : n(100) {}
};
Counter count;

void setup()
{
    Serial.begin();
    pinMode(LED_BUILTIN, OUTPUT_OPEN_DRAIN);   // PC4 は USER ボタンと共用: オープンドレインで駆動
    Serial.println("Blink start");
}

void loop()
{
    digitalWrite(LED_BUILTIN, LOW);            // 点灯
    delay(100);
    digitalWrite(LED_BUILTIN, HIGH);           // 消灯
    delay(900);
    Serial.printf("count %u  vbus %u mV\r\n", (unsigned)count.n++, (unsigned)Mpb_Vbus_mV());
    Serial.print("pi = ");
    Serial.println(3.14159, 3);
}
