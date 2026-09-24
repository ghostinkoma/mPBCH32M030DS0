#!/usr/bin/env python3
"""
生成した回路図の接続を検証する。

  kicad-cli sch export netlist --format kicadsexpr -o /tmp/out.net ch32m030_motor.kicad_sch
  python3 verify_netlist.py /tmp/out.net expected_nets.txt

KiCad が解釈したネットと gen_schematic.py の部品表から作った期待ネット
(expected_nets.txt) が完全一致するか確認する。未接続ネットも表示する。
"""
import re
import sys

txt = open(sys.argv[1], encoding="utf-8").read()
got = []
for m in re.finditer(r'\(net \(code "\d+"\) \(name "([^"]*)"\)(.*?)\)\s*(?=\(net |\)\s*\)\s*$)', txt, re.S):
    nodes = frozenset(f"{r}.{p}" for r, p in re.findall(r'\(node \(ref "([^"]+)"\) \(pin "([^"]+)"\)', m.group(2)))
    got.append((m.group(1), nodes))

exp = {}
for line in open(sys.argv[2], encoding="utf-8"):
    name, rest = line.rstrip("\n").split(": ", 1)
    exp[name] = frozenset(rest.split())

got_sets = {s for _, s in got}
bad = 0
for name, nodes in sorted(exp.items()):
    if nodes not in got_sets:
        bad += 1
        print("MISMATCH", name, sorted(nodes))
        for gname, gnodes in got:
            if gnodes & nodes:
                print("   kicad:", gname, sorted(gnodes))
print(f"expected {len(exp)} nets, matched {len(exp) - bad}, kicad nets {len(got)}")
print("single-node nets:", [g[0] for g in got if len(g[1]) == 1])
sys.exit(1 if bad else 0)
