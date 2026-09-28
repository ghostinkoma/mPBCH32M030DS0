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
    print(f"{'経路':34s} {'設計A':>5s} {'R mΩ':>6s} {'損失W':>6s} {'w_eff':>6s} {'許容A':>6s} {'w1mm':>5s} {'許容A':>6s} {'超過mm²':>7s} {'ビア超過':>4s} 最大ピン  最狭 (1mm 平均)")
    worst = worst1 = 99
    for r in rows:
        w = r["I"] / r["j_far"] if r["j_far"] else 99
        ia = i_allow(w)
        w1 = r["I"] / r["j_far1"] if r.get("j_far1") else w       # 1mm 平均 (角の電流集中を除く)
        ia1 = i_allow(w1)
        pins = [p for p in r["pins"] if p[0].startswith("J")]
        mp = max((abs(p[1]) for p in pins), default=0)
        worst = min(worst, ia)
        worst1 = min(worst1, ia1)
        print(f"{r['name'][:34]:34s} {r['I']:5.0f} {r['R_mohm']:6.2f} {r['P_mW'] / 1000:6.2f} {w:6.2f} {ia:6.1f} {w1:5.2f} {ia1:6.1f} "
              f"{r['hot_mm2']:7.1f} {len(r['via_over']):4d} {mp:5.2f}  {r.get('j_far1_at', '')}")
    print(f"   最小の許容電流: 格子最大 {worst:.1f} A / 1mm 平均 {worst1:.1f} A")
