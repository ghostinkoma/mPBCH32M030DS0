#!/usr/bin/env python3
"""
mpb_upload.py — mPBCH32M030DS0 用ファームウェア書き込みツール (USB-C / UART)

ESP32-C3 や Arduino と同じ感覚で「ビルド → USB で書き込み」できるようにするホスト側ツール。
基板のブートローダ (firmware/bootloader, WCH IAP 互換プロトコル) と通信する。

  python3 mpb_upload.py app.bin                 # USB 経由 (既定)
  python3 mpb_upload.py app.hex                 # Intel HEX も可
  python3 mpb_upload.py --uart /dev/ttyUSB0 app.bin
  python3 mpb_upload.py --list                  # 接続中のデバイスを表示

動作:
  1. VID 0x1A86 / PID 0x55E0 のデバイスを探す。bcdDevice の上位バイトで状態を判定
       0xA0xx = アプリ実行中 → CMD_JUMP_IAP を送り、再接続 (ブートローダ) を待つ
       0xB0xx = ブートローダ (WCH 純正 IAP の 0x0100 もブートローダとして扱う)
  2. ERASE → PROGRAM (60B ずつ) → VERIFY (56B ずつ, 全量) → END (アプリ起動)

必要: pip install pyusb pyserial
  Linux  : tools/99-mpb.rules を /etc/udev/rules.d/ に置くと root 不要
  Windows: Zadig で WinUSB ドライバを 1A86:55E0 に割り当てる (WCH 純正ドライバ使用時は WCHMcuIAP_WinAPP を使う)

Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
"""
import argparse
import struct
import sys
import time

VID, PID = 0x1A86, 0x55E0
EP_OUT, EP_IN = 0x02, 0x82
APP_BASE = 0x08005000
APP_MAX = 0x0800FF80 - APP_BASE          # 最終ページはブート要求フラグ用
CMD_PROM, CMD_ERASE, CMD_VERIFY, CMD_END, CMD_JUMP = 0x80, 0x81, 0x82, 0x83, 0x84
PROG_CHUNK, VERIFY_CHUNK = 60, 56
UART_BAUD = 460800


class UploadError(Exception):
    pass


# --------------------------------------------------------------------------- 入力ファイル
def load_image(path):
    """.bin (0x08005000 起点) または Intel HEX を読み込み bytes を返す."""
    if path.lower().endswith(".hex"):
        return _load_hex(path)
    with open(path, "rb") as f:
        data = f.read()
    return data


def _load_hex(path):
    mem, upper = {}, 0
    with open(path) as f:
        for ln, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            if not line.startswith(":"):
                raise UploadError(f"{path}:{ln}: Intel HEX 形式ではありません")
            raw = bytes.fromhex(line[1:])
            if sum(raw) & 0xFF:
                raise UploadError(f"{path}:{ln}: チェックサム不一致")
            n, addr, typ = raw[0], (raw[1] << 8) | raw[2], raw[3]
            payload = raw[4:4 + n]
            if typ == 0:
                for i, b in enumerate(payload):
                    mem[upper + addr + i] = b
            elif typ == 4:
                upper = ((payload[0] << 8) | payload[1]) << 16
            elif typ == 2:
                upper = ((payload[0] << 8) | payload[1]) << 4
            elif typ == 1:
                break
    if not mem:
        raise UploadError("HEX にデータがありません")
    lo, hi = min(mem), max(mem)
    # 0x00005000 (エイリアス) / 0x08005000 どちらのリンクでも受け付ける
    base = APP_BASE if lo >= 0x08000000 else APP_BASE - 0x08000000
    if lo != base:
        raise UploadError(f"HEX の開始アドレス 0x{lo:08X} がアプリ領域 0x{base:08X} と一致しません")
    return bytes(mem.get(a, 0xFF) for a in range(lo, hi + 1))


# --------------------------------------------------------------------------- トランスポート
class UsbLink:
    def __init__(self, dev):
        self.dev = dev

    @staticmethod
    def find_all():
        try:
            import usb.core
        except ImportError:
            raise UploadError("pyusb がありません: pip install pyusb")
        try:
            return list(usb.core.find(find_all=True, idVendor=VID, idProduct=PID) or [])
        except usb.core.NoBackendError:
            raise UploadError("libusb が見つかりません (Linux: apt install libusb-1.0-0 / "
                              "macOS: brew install libusb / Windows: Zadig で WinUSB を導入)")

    @classmethod
    def open(cls, timeout=5.0, want=None):
        """want: None=何でも, 'boot'=ブートローダが現れるまで待つ."""
        t0 = time.time()
        while True:
            for dev in cls.find_all():
                if want is None or state_of(dev.bcdDevice) == want:
                    try:
                        dev.set_configuration()
                    except Exception:
                        pass
                    return cls(dev)
            if time.time() - t0 > timeout:
                raise UploadError("USB デバイス (1A86:55E0) が見つかりません。"
                                  " USER/BOOT ボタンを押しながらリセットしてブートローダを起動してください")
            time.sleep(0.2)

    @property
    def state(self):
        return state_of(self.dev.bcdDevice)

    def xfer(self, pkt, expect_reply=True):
        self.dev.write(EP_OUT, pkt, timeout=2000)
        if not expect_reply:
            return 0
        rsp = bytes(self.dev.read(EP_IN, 64, timeout=3000))
        if len(rsp) < 2:
            raise UploadError(f"応答が短すぎます: {rsp.hex()}")
        return rsp[1]

    def close(self):
        import usb.util
        usb.util.dispose_resources(self.dev)


class UartLink:
    """UART: AA 55 | cmd len [addr4] [data] | sum_lo sum_hi | 55 AA → 応答 AA 55 00 st 55 AA."""
    state = "boot"

    def __init__(self, port, baud):
        try:
            import serial
        except ImportError:
            raise UploadError("pyserial がありません: pip install pyserial")
        self.ser = serial.Serial(port, baud, timeout=2)

    def xfer(self, pkt, expect_reply=True):
        # パケットは USB と同じ並び (cmd len [addr4: ERASE/VERIFY] [data: PROM/VERIFY])
        body = bytes(pkt)
        s = sum(body) & 0xFFFF
        frame = b"\xaa\x55" + body + struct.pack("<H", s) + b"\x55\xaa"
        self.ser.write(frame)
        if not expect_reply:
            return 0
        rsp = self.ser.read(6)
        if len(rsp) != 6 or rsp[:2] != b"\xaa\x55" or rsp[4:] != b"\x55\xaa":
            raise UploadError(f"UART 応答が不正です: {rsp.hex()}")
        return rsp[3]

    def close(self):
        self.ser.close()


def state_of(bcd):
    hi = (bcd >> 8) & 0xFF
    return "app" if hi == 0xA0 else "boot"


# --------------------------------------------------------------------------- プロトコル
def packets(image):
    """書き込み手順のパケット列を生成する (テスト容易性のため I/O から分離)."""
    yield "erase", bytes([CMD_ERASE, 4]) + struct.pack("<I", len(image)), True
    for off in range(0, len(image), PROG_CHUNK):
        chunk = image[off:off + PROG_CHUNK]
        yield "prog", bytes([CMD_PROM, len(chunk)]) + chunk, True
    for off in range(0, len(image), VERIFY_CHUNK):
        chunk = image[off:off + VERIFY_CHUNK]
        yield "verify", bytes([CMD_VERIFY, len(chunk)]) + struct.pack("<I", off) + chunk, True
    yield "end", bytes([CMD_END, 0]), False


def upload(link, image, out=sys.stdout):
    total = sum(1 for _ in packets(image))
    last = ""
    for i, (phase, pkt, reply) in enumerate(packets(image), 1):
        st = link.xfer(pkt, reply)
        if st != 0:
            raise UploadError(f"{phase} でエラー (status={st}, packet {i}/{total})"
                              + (" — 検証不一致" if phase == "verify" else ""))
        if phase != last or i % 16 == 0 or i == total:
            out.write(f"\r  {phase:7s} {i * 100 // total:3d}%")
            out.flush()
            last = phase
    out.write("\n")


def enter_bootloader_usb(timeout):
    link = UsbLink.open(timeout=timeout)
    if link.state == "boot":
        return link
    print("アプリ実行中 → ブートローダへ切り替えます")
    link.xfer(bytes([CMD_JUMP, 0]))
    link.close()
    time.sleep(0.8)
    return UsbLink.open(timeout=timeout, want="boot")


def main(argv=None):
    ap = argparse.ArgumentParser(description="mPBCH32M030DS0 firmware uploader (USB / UART)")
    ap.add_argument("image", nargs="?", help="app.bin (0x08005000 起点) または app.hex")
    ap.add_argument("--uart", metavar="PORT", help="UART で書き込む (例: /dev/ttyUSB0, COM3)")
    ap.add_argument("--baud", type=int, default=UART_BAUD)
    ap.add_argument("--timeout", type=float, default=8.0, help="デバイス待ち時間 [s]")
    ap.add_argument("--list", action="store_true", help="接続中のデバイスを表示して終了")
    args = ap.parse_args(argv)

    if args.list:
        for d in UsbLink.find_all():
            print(f"bus {d.bus} addr {d.address}: 1A86:55E0 bcdDevice=0x{d.bcdDevice:04X} ({state_of(d.bcdDevice)})")
        return 0
    if not args.image:
        ap.error("書き込むファイルを指定してください")

    image = load_image(args.image)
    if len(image) > APP_MAX:
        raise UploadError(f"イメージが大きすぎます: {len(image)} > {APP_MAX} バイト")
    print(f"{args.image}: {len(image)} バイト → 0x{APP_BASE:08X}")

    if args.uart:
        link = UartLink(args.uart, args.baud)
        print("UART: USER/BOOT ボタンを押しながらリセットしてブートローダを起動しておくこと")
    else:
        link = enter_bootloader_usb(args.timeout)
    try:
        t0 = time.time()
        upload(link, image)
    finally:
        link.close()
    print(f"完了 ({time.time() - t0:.1f}s)。アプリを起動しました。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except UploadError as e:
        print(f"\nエラー: {e}", file=sys.stderr)
        sys.exit(1)
