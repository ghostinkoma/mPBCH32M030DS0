#!/usr/bin/env python3
"""
mpb.py — mPBCH32M030DS0 SDK のコマンド (エディタから呼ぶ入口。端末からも使える)

  python3 tools/mpb.py list                         プロジェクト (テンプレート・サンプル) の一覧
  python3 tools/mpb.py build   [パス] [--stage B]   ビルド (+ compile_commands.json を作る)
  python3 tools/mpb.py upload  [パス]               ビルドして USB-C で書き込む
  python3 tools/mpb.py clean   [パス]
  python3 tools/mpb.py compdb  [パス]               compile_commands.json だけ作る (clangd の補完・定義ジャンプ用)
  python3 tools/mpb.py new     <ディレクトリ> [--from stepper | --rtos]
  python3 tools/mpb.py monitor [--port /dev/ttyUSB0] [--baud 460800]    UART ログを見る (pyserial)
  python3 tools/mpb.py size    [パス]               フラッシュ / RAM の使用量

[パス] はプロジェクトのディレクトリか, その中のファイル (エディタで開いているファイル) でよい。
省略すると今のディレクトリから上へ探す。VS Code では firmware/.vscode/tasks.json がこれを呼ぶ。

Copyright (c) 2026 ghostinkoma — LICENSE 参照 (無保証)
"""
import argparse
import json
import os
import shlex
import subprocess
import sys

FW = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FLASH_MAX = 0xAF80
RAM_MAX = 12 * 1024


def find_project(path):
    p = os.path.abspath(path or os.getcwd())
    if os.path.isfile(p):
        p = os.path.dirname(p)
    while True:
        if os.path.isfile(os.path.join(p, "Makefile")) and os.path.isdir(os.path.join(p, "src")):
            return p
        parent = os.path.dirname(p)
        if parent == p:
            sys.exit(f"プロジェクト (Makefile と src/ のあるディレクトリ) が見つかりません: {path or os.getcwd()}")
        p = parent


def projects():
    out = []
    for base in ("app_template", "examples"):
        d = os.path.join(FW, base)
        cands = [d] if base == "app_template" else [os.path.join(d, n) for n in sorted(os.listdir(d))]
        for c in cands:
            if os.path.isfile(os.path.join(c, "Makefile")):
                out.append(c)
    return out


def make(proj, *args, stage=None):
    cmd = ["make", "-C", proj, f"-j{os.cpu_count() or 2}", *args]
    if stage:
        cmd.append(f"POWER_STAGE={stage}")
    print("$", " ".join(shlex.quote(c) for c in cmd), flush=True)
    return subprocess.call(cmd)


def compdb(proj, stage=None):
    """make -nB の出力から compile_commands.json を作る (ビルド設定と完全に同じフラグになる)"""
    cmd = ["make", "-C", proj, "-nB"] + ([f"POWER_STAGE={stage}"] if stage else [])
    out = subprocess.run(cmd, capture_output=True, text=True).stdout
    entries = []
    for line in out.splitlines():
        try:
            args = shlex.split(line)
        except ValueError:
            continue
        if not args or not args[0].endswith(("gcc", "g++")) or "-c" not in args:
            continue
        src = args[args.index("-c") + 1]
        entries.append({"directory": proj, "file": os.path.normpath(os.path.join(proj, src)), "arguments": args})
    path = os.path.join(proj, "compile_commands.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=1)
    print(f"compile_commands.json: {len(entries)} ファイル → {path}")
    return 0 if entries else 1


def size(proj):
    elf = os.path.join(proj, "build", "app.elf")
    if not os.path.isfile(elf):
        sys.exit("まだビルドしていません")
    tool = next((t for t in ("riscv64-unknown-elf-size", "riscv-none-elf-size", "riscv-wch-elf-size")
                 if subprocess.call(["which", t], stdout=subprocess.DEVNULL) == 0), None)
    if not tool:
        sys.exit("size コマンドが見つかりません")
    text, data, bss = map(int, subprocess.check_output([tool, elf], text=True).splitlines()[1].split()[:3])
    print(f"フラッシュ {text + data:6d} / {FLASH_MAX} バイト ({100 * (text + data) // FLASH_MAX}%)")
    print(f"RAM (静的) {data + bss:6d} / {RAM_MAX} バイト ({100 * (data + bss) // RAM_MAX}%)  + スタック")
    return 0


def monitor(port, baud):
    try:
        from serial.tools import miniterm
    except ImportError:
        sys.exit("pyserial が必要です: pip install pyserial")
    if not port:
        from serial.tools import list_ports
        ports = [p.device for p in list_ports.comports()]
        if not ports:
            sys.exit("シリアルポートが見つかりません (--port で指定)")
        port = ports[0]
    sys.argv = ["miniterm", port, str(baud), "--eol", "CRLF", "--raw"]
    print(f"{port} {baud}bps (Ctrl+] で終了)")
    miniterm.main()
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["list", "build", "upload", "clean", "compdb", "new", "monitor", "size"])
    ap.add_argument("path", nargs="?")
    ap.add_argument("--stage", choices=["A", "B", "C"], help="子基板 (config.h の MPB_POWER_STAGE を一時的に上書き)")
    ap.add_argument("--from", dest="src")
    ap.add_argument("--rtos", action="store_true")
    ap.add_argument("--port")
    ap.add_argument("--baud", type=int, default=460800)
    a = ap.parse_args()

    if a.cmd == "list":
        for p in projects():
            print(os.path.relpath(p, FW))
        return 0
    if a.cmd == "new":
        if not a.path:
            sys.exit("作るディレクトリを指定してください")
        args = [sys.executable, os.path.join(FW, "tools", "new_sketch.py"), a.path]
        args += (["--from", a.src] if a.src else []) + (["--rtos"] if a.rtos else [])
        return subprocess.call(args)
    if a.cmd == "monitor":
        return monitor(a.port, a.baud)
    proj = find_project(a.path)
    if a.cmd == "build":
        rc = make(proj, stage=a.stage)
        compdb(proj, a.stage)
        if rc == 0:
            size(proj)
        return rc
    if a.cmd == "upload":
        return make(proj, "upload", stage=a.stage)
    if a.cmd == "clean":
        return make(proj, "clean")
    if a.cmd == "compdb":
        return compdb(proj, a.stage)
    if a.cmd == "size":
        return size(proj)
    return 1


if __name__ == "__main__":
    sys.exit(main())
