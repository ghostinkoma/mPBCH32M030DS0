/*
 * mpb_config_select.h — 全ソースの先頭で読まれる (platform.txt の -include)
 * スケッチに config.h タブがあれば読む: ライブラリ (mpbfun) の設定 (MPB_LOG_BUF など) とスケッチの CFG_* が効く。
 * 子基板 (MPB_POWER_STAGE) と UART 書き込み (MPB_UART_BOOT) は「ツール」メニューで選ぶ。
 */
#ifndef MPB_CONFIG_SELECT_H
#define MPB_CONFIG_SELECT_H
#if defined(__has_include)
#if __has_include("config.h")
#include "config.h"
#endif
#endif
#endif
