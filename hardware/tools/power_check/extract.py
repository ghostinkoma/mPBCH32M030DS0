# 指定ネットの銅形状 (層ごとのポリゴン) とビア・パッド情報を JSON に書き出す (pcbnew, chroot 側で実行)
import pcbnew, sys, json
path, nets, out = sys.argv[1], sys.argv[2].split(","), sys.argv[3]
b = pcbnew.LoadBoard(path)
T = pcbnew.ToMM
LAY = {pcbnew.F_Cu: "F", pcbnew.B_Cu: "B"}
def polys(ps):
    res = []
    for i in range(ps.OutlineCount()):
        o = ps.Outline(i)
        chains = [[(T(o.CPoint(k).x), T(o.CPoint(k).y)) for k in range(o.PointCount())]]
        for h in range(ps.HoleCount(i)):
            hh = ps.Hole(i, h)
            chains.append([(T(hh.CPoint(k).x), T(hh.CPoint(k).y)) for k in range(hh.PointCount())])
        res.append(chains)
    return res
data = {}
for n in nets:
    d = {"F": [], "B": [], "vias": [], "pads": [], "segs": {"F": [], "B": []}}
    for t in b.GetTracks():
        if t.GetNetname() != n: continue
        if t.GetClass() == "PCB_VIA":
            d["vias"].append((T(t.GetPosition().x), T(t.GetPosition().y), T(t.GetDrillValue()), T(t.GetWidth())))
        else:
            L = t.GetLayer()
            assert t.GetClass() == "PCB_TRACK", t.GetClass()
            if L in LAY:
                d["segs"][LAY[L]].append((T(t.GetStart().x), T(t.GetStart().y), T(t.GetEnd().x), T(t.GetEnd().y), T(t.GetWidth())))
    for z in b.Zones():
        if z.GetNetname() != n or z.GetIsRuleArea(): continue
        for L, k in LAY.items():
            if z.IsOnLayer(L):
                d[k] += polys(z.GetFilledPolysList(L))
    for f in b.GetFootprints():
        for p in f.Pads():
            if p.GetNetname() != n: continue
            pd = {"ref": f.GetReference(), "num": p.GetNumber(), "tht": p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH,
                  "drill": T(p.GetDrillSize().x), "x": T(p.GetPosition().x), "y": T(p.GetPosition().y), "poly": {}}
            for L, k in LAY.items():
                if p.IsOnLayer(L):
                    ps = p.GetEffectivePolygon()
                    pd["poly"][k] = polys(ps); d[k] += polys(ps)
            d["pads"].append(pd)
    data[n] = d
mask = {"F": [], "B": []}      # はんだを盛るレジスト開口 (PCB_SHAPE の多角形)
for d in b.GetDrawings():
    if d.GetLayer() in (pcbnew.F_Mask, pcbnew.B_Mask) and d.GetClass() == "PCB_SHAPE" and d.GetShape() == pcbnew.SHAPE_T_POLY:
        mask["F" if d.GetLayer() == pcbnew.F_Mask else "B"] += polys(d.GetPolyShape())
eb = b.GetBoardEdgesBoundingBox()
json.dump({"W": T(eb.GetRight()), "H": T(eb.GetBottom()), "nets": data, "mask": mask}, open(out, "w"))
print("wrote", out, {n: (len(v["F"]), len(v["B"]), len(v["vias"]), len(v["pads"])) for n, v in data.items()})
