/* heap_4 (FreeRTOS) — 動的確保を使う設定のときだけ組み込む */
#include "FreeRTOS.h"
#if configSUPPORT_DYNAMIC_ALLOCATION
#include "heap_4.inc"
#endif
