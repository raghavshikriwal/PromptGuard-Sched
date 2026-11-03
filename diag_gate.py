"""Print each job's LLM proposal vs final allocation from a gate database.

python diag_gate.py gate_qwen_trial.db
"""

import json
import sqlite3
import sys


def fmt(xs: list[float | None]) -> str:
    return " ".join("None" if x is None else f"{x:.3f}" for x in xs)


con = sqlite3.connect(sys.argv[1])
rows = con.execute(
    "select llm_candidate, ilp_allocation, dominant_entitlement, allocated_share "
    "from schedule_decisions order by created_at"
).fetchall()

print(f"{len(rows)} decisions\n")
print(
    "job | LLM proposal (cpu mem disk net) | final shares (cpu mem disk net)"
    " | entitlement -> share"
)
zero_final = 0
for i, (cand, alloc, ent, share) in enumerate(rows):
    cand, alloc = json.loads(cand), json.loads(alloc)
    p = cand["proposal"]
    prop = [p.get(k) for k in ("cpu_share", "mem_share", "disk_share", "net_share")]
    fin = [alloc["allocated_shares"].get(k) for k in ("cpu", "mem_gb", "disk_gb", "net_mbps")]
    zero_final += any(v is not None and v < 1e-3 for v in fin)
    print(f"{i:>3} | {fmt(prop)} | {fmt(fin)} | {float(ent):.3f} -> {float(share):.3f}")

print(f"\njobs with some final share < 0.001: {zero_final}/{len(rows)}")
print("\nraw response of job 0:\n", json.loads(rows[0][0])["raw_response"])
