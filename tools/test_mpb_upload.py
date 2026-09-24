#!/usr/bin/env python3
"""
mpb_upload.py のプロトコル試験。
ブートローダ (firmware/bootloader/src/iap.c の RecData_Deal / UART_Rx_Deal) の処理を
Python で忠実に再現したシミュレータに対して書き込み、フラッシュ内容が一致することを確認する。
  python3 -m unittest tools/test_mpb_upload.py
"""
import io
import os
import random
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import mpb_upload as mu  # noqa: E402

FLASH_BASE = 0x08005000
PAGE = 128


class SimBootloader:
    """iap.c の RecData_Deal を移植したもの (USB: パケット単位)."""

    def __init__(self):
        self.flash = bytearray(b"\xff" * 0x10000)   # 0x08000000 起点
        self.prog = FLASH_BASE
        self.ver = FLASH_BASE
        self.buf = bytearray(390)
        self.codelen = 0
        self.vflag = 0
        self.end = False

    def _write_page(self, addr, data):
        o = addr - 0x08000000
        assert addr % PAGE == 0 and len(data) == PAGE
        self.flash[o:o + PAGE] = data

    def rec(self, pkt):
        cmd, n = pkt[0], pkt[1]
        if cmd == 0x81:
            return 0
        if cmd == 0x80:
            data = pkt[2:2 + n]
            self.buf[self.codelen:self.codelen + n] = data
            self.codelen += n
            if self.codelen >= 128:
                self._write_page(self.prog, bytes(self.buf[:128]))
                self.codelen -= 128
                self.buf[:self.codelen] = self.buf[128:128 + self.codelen]
                self.prog += 0x80
            return 0
        if cmd == 0x82:
            if self.vflag == 0:
                self.vflag = 1
                if self.codelen:
                    page = bytes(self.buf[:self.codelen]) + b"\xff" * (128 - self.codelen)
                    self._write_page(self.prog, page)
                    self.codelen = 0
            data = pkt[6:6 + n]
            o = self.ver - 0x08000000
            st = 0 if bytes(self.flash[o:o + n]) == bytes(data) else 1
            self.ver += n
            return st
        if cmd == 0x83:
            self.end = True
            return 2
        if cmd == 0x84:
            return 0
        return 1


class FakeUsb:
    state = "boot"

    def __init__(self):
        self.sim = SimBootloader()

    def xfer(self, pkt, expect_reply=True):
        assert len(pkt) <= 64, "USB パケットは 64B 以下"
        st = self.sim.rec(bytes(pkt))
        if st == 2:
            assert not expect_reply, "END には応答が無い"
            return 0
        assert expect_reply
        return st

    def close(self):
        pass


class FakeSerial:
    """UART_Rx_Deal のフレーム解析を再現し、SimBootloader に渡す."""

    def __init__(self):
        self.sim = SimBootloader()
        self.rx = b""

    def write(self, frame):
        f = io.BytesIO(frame)
        rd = lambda: f.read(1)[0]
        assert rd() == 0xAA and rd() == 0x55
        cmd, n = rd(), rd()
        s = cmd + n
        pkt = bytearray([cmd, n])
        if cmd in (0x81, 0x82):
            a = bytes(rd() for _ in range(4))
            s += sum(a)
            pkt += a
        if cmd in (0x80, 0x82):
            d = bytes(rd() for _ in range(n))
            s += sum(d)
            pkt += d
        assert rd() == s & 0xFF and rd() == (s >> 8) & 0xFF, "チェックサム"
        assert rd() == 0x55 and rd() == 0xAA
        if cmd == 0x82:
            pass  # UART 版は UART.data (offset 2) で比較するが, 内容は同じデータ
        st = self.sim.rec(bytes(pkt))
        if st != 2:
            self.rx += bytes([0xAA, 0x55, 0x00, 1 if st == 1 else 0, 0x55, 0xAA])

    def read(self, n):
        r, self.rx = self.rx[:n], self.rx[n:]
        return r

    def close(self):
        pass


def _flash_image(sim, n):
    o = FLASH_BASE - 0x08000000
    return bytes(sim.flash[o:o + n])


class UploadTest(unittest.TestCase):
    def _image(self, n, seed=1):
        rnd = random.Random(seed)
        return bytes(rnd.randrange(256) for _ in range(n))

    def test_usb_various_sizes(self):
        for n in (1, 59, 60, 127, 128, 129, 1000, 4824, 44928):
            with self.subTest(n=n):
                link = FakeUsb()
                img = self._image(n, n)
                mu.upload(link, img, out=io.StringIO())
                self.assertTrue(link.sim.end)
                self.assertEqual(_flash_image(link.sim, n), img)

    def test_uart(self):
        link = mu.UartLink.__new__(mu.UartLink)
        link.ser = FakeSerial()
        img = self._image(3001, 7)
        mu.upload(link, img, out=io.StringIO())
        self.assertTrue(link.ser.sim.end)
        self.assertEqual(_flash_image(link.ser.sim, len(img)), img)

    def test_verify_mismatch_detected(self):
        link = FakeUsb()
        img = self._image(300, 3)
        orig = link.sim._write_page

        def corrupt(addr, data):
            orig(addr, bytes([data[0] ^ 1]) + data[1:])
        link.sim._write_page = corrupt
        with self.assertRaises(mu.UploadError):
            mu.upload(link, img, out=io.StringIO())

    def test_hex_loader(self):
        img = self._image(300, 9)
        lines = [":020000040800F2"]
        for off in range(0, len(img), 16):
            chunk = img[off:off + 16]
            addr = 0x5000 + off
            rec = bytes([len(chunk), addr >> 8, addr & 0xFF, 0]) + chunk
            lines.append(":" + (rec + bytes([(-sum(rec)) & 0xFF])).hex().upper())
        lines.append(":00000001FF")
        with tempfile.NamedTemporaryFile("w", suffix=".hex", delete=False) as f:
            f.write("\n".join(lines))
        try:
            self.assertEqual(mu.load_image(f.name), img)
        finally:
            os.unlink(f.name)

    def test_state_detection(self):
        self.assertEqual(mu.state_of(0xA001), "app")
        self.assertEqual(mu.state_of(0xB001), "boot")
        self.assertEqual(mu.state_of(0x0100), "boot")   # WCH 純正 IAP


if __name__ == "__main__":
    unittest.main()
