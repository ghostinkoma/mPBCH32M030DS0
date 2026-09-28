"""res_*.jsonl から, 経路ごとの許容連続電流 (IPC-2221 外層 1oz, ΔT 20°C) を出す.
w_eff = I / j_far (パッド口元 0.5mm を除いた最大電流密度から求めた等価幅) → その幅で流せる電流."""
import json
import sys


def i_allow(w_mm, dT=20, t_mil=1.378):
    A = w_mm / 0.0254 * t_mil
    return 0.048 * dT ** 0.44 * A ** 0.725


for k in sys.argv[1:]:
    rows = [json.loads(l) for l in open(f"res_{k}.jsonl")]
    print(f"== {k}")
    print(f"{'経路':34s} {'設計A':>5s} {'R mΩ':>6s} {'損失W':>6s} {'w_eff':>6s} {'許容A':>6s} {'超過mm²':>7s} {'ビア超過':>4s} 最大ピン")
    worst = 99
    for r in rows:
        w = r["I"] / r["j_far"] if r["j_far"] else 99
        ia = i_allow(w)
        pins = [p for p in r["pins"] if p[0].startswith("J")]
        mp = max((abs(p[1]) for p in pins), default=0)
        worst = min(worst, ia * (1 if r["I"] >= 5 else 1))
        print(f"{r['name'][:34]:34s} {r['I']:5.0f} {r['R_mohm']:6.2f} {r['P_mW'] / 1000:6.2f} {w:6.2f} {ia:6.1f} {r['hot_mm2']:7.1f} "
              f"{len(r['via_over']):4d} {mp:5.2f}")
    print(f"   最小の許容電流: {worst:.1f} A")
