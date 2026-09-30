TARGET := app
# PC2 (UART_RX) を WS2812 のデータに使うので, UART からの書き込み要求 (RX) は切る。書き込みは USB-C で行う
EXTRA_CFLAGS += -DMPB_UART_BOOT=0
include ../../common/app.mk
