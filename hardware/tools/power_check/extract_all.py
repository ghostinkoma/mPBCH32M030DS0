import pcbnew, json, sys
b = pcbnew.LoadBoard(sys.argv[1]); T = pcbnew.ToMM
LAY = {pcbnew.F_Cu: "F", pcbnew.B_Cu: "B"}
def polys(ps):
    res = []
    for i in range(ps.OutlineCount()):
        o = ps.Outline(i)
        ch = [[(T(o.CPoint(k).x), T(o.CPoint(k).y)) for k in range(o.PointCount())]]
        for h in range(ps.HoleCount(i)):
            hh = ps.Hole(i, h); ch.append([(T(hh.CPoint(k).x), T(hh.CPoint(k).y)) for k in range(hh.PointCount())])
        res.append(ch)
    return res
segs, vias, pads, zones = [], [], [], []
for t in b.GetTracks():
    if t.GetClass() == "PCB_VIA":
        vias.append((t.GetNetname(), T(t.GetPosition().x), T(t.GetPosition().y), T(t.GetWidth())))
    elif t.GetLayer() in LAY:
        segs.append((t.GetNetname(), LAY[t.GetLayer()], T(t.GetStart().x), T(t.GetStart().y), T(t.GetEnd().x), T(t.GetEnd().y), T(t.GetWidth())))
for f in b.GetFootprints():
    for p in f.Pads():
        ls = [k for L, k in LAY.items() if p.IsOnLayer(L)]
        pads.append((p.GetNetname(), f.GetReference(), p.GetNumber(), ls, polys(p.GetEffectivePolygon())))
for z in b.Zones():
    for L, k in LAY.items():
        if z.IsOnLayer(L):
            zones.append((z.GetNetname(), k, polys(z.GetFilledPolysList(L))))
eb = b.GetBoardEdgesBoundingBox()
json.dump({"W": T(eb.GetRight()), "H": T(eb.GetBottom()), "segs": segs, "vias": vias, "pads": pads, "zones": zones}, open(sys.argv[2], "w"))
print(len(segs), len(vias), len(pads), len(zones))
