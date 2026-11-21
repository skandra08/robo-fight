"""Compare simulator results with known practice scores: python3 sim/calib.py out.json [metric]"""
import json, sys, statistics as st
PRACTICE = {"fa3e282": 2.75, "aee2114": 2.73, "b7b5c38": 2.65, "5e969f1": 2.5, "55f5015": 2.29, "9b820d1": 2.29,
            "79d9eeb": 2.17, "3cbee64": 2.15, "b4d6e37": 2.00, "481fed0": 2.81, "2e8b45e": 2.90}
def ranks(v):
    o = sorted(range(len(v)), key=lambda i: v[i]); r = [0.0] * len(v); i = 0
    while i < len(o):
        j = i
        while j + 1 < len(o) and v[o[j + 1]] == v[o[i]]: j += 1
        for k in range(i, j + 1): r[o[k]] = (i + j) / 2 + 1
        i = j + 1
    return r
def pear(a, b):
    ma, mb = st.mean(a), st.mean(b)
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b)) ** 0.5
d = json.load(open(sys.argv[1])); metric = sys.argv[2] if len(sys.argv) > 2 else "score"
cs = [c for c in d["summary"] if c[:7] in PRACTICE and d["summary"][c]["n"]]
real = [PRACTICE[c[:7]] for c in cs]; sim = [d["summary"][c][metric] for c in cs]
for c, r, s in sorted(zip(cs, real, sim), key=lambda x: -x[1]): print(f"{c[:7]} practice {r:.2f}  sim {metric} {s:.2f}")
pairs = [(i, j) for i in range(len(cs)) for j in range(i + 1, len(cs)) if real[i] != real[j]]
ok = sum(1 for i, j in pairs if (real[i] - real[j]) * (sim[i] - sim[j]) > 0)
print(f"spearman {pear(ranks(real), ranks(sim)):.2f}  pearson {pear(real, sim):.2f}  pairs right {ok}/{len(pairs)}")
