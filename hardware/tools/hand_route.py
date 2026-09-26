#!/usr/bin/env python3
"""
自動配線で残った未接続の仕上げ (手配線の補助)。KiCad 8 の Python で実行する。

  python3 tools/hand_route.py export <board.kicad_pcb> <work_dir> NET1,NET2,...
      指定ネットの配線を外し, それ以外の配線を「固定 (protect)」にした DSN を <work_dir>/hr.dsn に書く
  (ホスト側で Freerouting: java -jar freerouting.jar -de hr.dsn -do hr.ses -mp 60)
  python3 tools/hand_route.py import <board.kicad_pcb> <work_dir> <out.kicad_pcb>
      hr.ses を取り込み, ベタを塗り直して DRC し, 未接続が減って電気的エラーが無ければ <out> に保存
"""
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import pcblib  # noqa: E402
from pcblib import pcbnew  # noqa: E402

ERR = ("[clearance]", "[shorting_items]", "[tracks_crossing]", "[copper_edge_clearance]", "[hole_clearance]",
       "[hole_near_hole]", "[via_diameter]", "[annular_width]", "[track_width]")


class Board:
    """pcblib.Pcb の一部メソッド (DSN のネットクラス, SES 取り込み) を, 既存の基板ファイルに対して使う."""
    def __init__(self, path):
        self.path = path
        self.b = pcbnew.LoadBoard(path)
        self.nets = {str(k): v for k, v in self.b.GetNetsByName().items() if str(k)}
        pro = json.load(open(path[:-len(".kicad_pcb")] + ".kicad_pro", encoding="utf-8"))
        self.assign = {p["pattern"]: p["netclass"] for p in pro["net_settings"].get("netclass_patterns", [])}

    _dsn_classes = pcblib.Pcb._dsn_classes
    import_ses = pcblib.Pcb.import_ses


def drc(path, rpt):
    subprocess.run(["kicad-cli", "pcb", "drc", "--units", "mm", "--severity-all", "-o", rpt, path], capture_output=True)
    txt = open(rpt, encoding="utf-8").read()
    blocks = re.findall(r"(^\[\w+\]:.*?\n(?:    .*\n)+)", txt, re.M)
    return sum(b.startswith(ERR) for b in blocks), sum(b.startswith("[unconnected_items]") for b in blocks), blocks


def export(path, work, nets):
    bd = Board(path)
    for z in list(bd.b.Zones()):
        if not z.GetIsRuleArea():
            bd.b.RemoveNative(z)
    n = 0
    for t in list(bd.b.GetTracks()):
        if t.GetNetname() in nets:
            bd.b.RemoveNative(t)
            n += 1
    os.makedirs(work, exist_ok=True)
    dsn = os.path.join(work, "hr.dsn")
    assert pcbnew.ExportSpecctraDSN(bd.b, dsn)
    bd._dsn_classes(dsn)
    txt = open(dsn, encoding="utf-8").read()
    txt = txt.replace("(type route)", "(type protect)")      # 外さなかった配線は Freerouting に動かさせない
    open(dsn, "w", encoding="utf-8").write(txt)
    print(f"export: ripped {n} items of {len(nets)} nets -> {dsn}")


def do_import(path, work, out):
    bd = Board(path)
    zones = [z for z in bd.b.Zones() if not z.GetIsRuleArea()]
    e0, u0, _ = drc(path, os.path.join(work, "before.rpt"))
    for t in list(bd.b.GetTracks()):
        bd.b.RemoveNative(t)
    t, v = bd.import_ses(os.path.join(work, "hr.ses"))
    bd.b.BuildConnectivity()
    filler = pcbnew.ZONE_FILLER(bd.b)
    filler.Fill(bd.b.Zones())
    tmp = os.path.join(work, "after.kicad_pcb")
    pcbnew.SaveBoard(tmp, bd.b)
    import shutil
    shutil.copy(path[:-len(".kicad_pcb")] + ".kicad_pro", tmp[:-len(".kicad_pcb")] + ".kicad_pro")
    e1, u1, blocks = drc(tmp, os.path.join(work, "after.rpt"))
    print(f"import: tracks {t} vias {v}; before errors {e0} unconnected {u0} -> after errors {e1} unconnected {u1}")
    for blk in blocks:
        if blk.startswith(ERR) or blk.startswith("[unconnected_items]"):
            print("   ", blk.replace("\n", " | ")[:200])
    if e1 <= e0 and u1 < u0:
        shutil.copy(tmp, out)
        print("saved", out)


if __name__ == "__main__":
    cmd, path, work = sys.argv[1:4]
    if cmd == "export":
        export(path, work, set(sys.argv[4].split(",")))
    else:
        do_import(path, work, sys.argv[4])
