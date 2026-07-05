#!/usr/bin/env python3
"""Export decomp match data -> chat-SFT JSONL for the Soma (Unsloth) fine-tune
pipeline. This is the *training* path for qwable-as-decompiler — the corpus
ingestion that closes the learn-to-decomp flywheel.

Two data sources, both producing asm->C answer-key examples:

  1. HARVEST — every 100%-matched function in build/report.json whose C body is
     cleanly extractable (has the repo's `.text <mangled>` marker). The ~large
     warm-start set: the target's disassembly (model input) paired with the
     matched C source (target output).
  2. TRAJECTORIES — forge/attempt-log.jsonl, the live loop's attempts. MATCHED
     records become answer-key examples; the loop keeps writing these as it runs.
     (Non-match records stay in the jsonl for future DPO/RL — SFT wants positives.)

Format matches .autoloop/soma-buildout/shadow-corpus.jsonl exactly:
    {"messages": [{role, content}...], "meta": {...}}
so the existing Unsloth pipeline consumes it unchanged. Output is a SEPARATE
specialist dataset (Soma runs a FLEET of specialists, each gated by its own
metric) — it does NOT pollute the spine-selfopt training set.

  Output:  <ForgeEngine>/.unsloth-studio/data/decomp-sft.jsonl
  Usage:   python3 forge/export-sft.py                 # harvest + trajectories
           python3 forge/export-sft.py --harvest-limit 300   # bounded (fast, for testing)
           python3 forge/export-sft.py --no-harvest    # trajectories only (quick refresh)
"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import forge

def _forge_root(start):
    """Walk up from the decomp repo to the ForgeEngine root (the one holding the
    Unsloth data dir the training pipeline reads)."""
    d = start
    for _ in range(6):
        if os.path.isdir(os.path.join(d, ".unsloth-studio", "data")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return os.path.dirname(start)


FORGE_ROOT = _forge_root(forge.ROOT)  # ForgeEngine (Soma dev source)
OUT_DIR = os.path.join(FORGE_ROOT, ".unsloth-studio", "data")
OUT = os.path.join(OUT_DIR, "decomp-sft.jsonl")

SYS_PROMPT = (
    "You are a decompiler for the Nintendo GameCube (PowerPC, Metrowerks CodeWarrior "
    "MWCC 2.7 / Dolphin SDK 1.2.5n). Given a function's target assembly, output C "
    "source that MWCC compiles to byte-identical assembly. Match register allocation, "
    "instruction selection, and scheduling — not just behaviour. Output only C.")


def example(unit, symbol, asm, c, source):
    """One chat-SFT record: target asm in, matched C out."""
    user = ("Decompile this GameCube function to matching C.\n\n"
            "## Target assembly (%s)\n```\n%s\n```" % (symbol, asm.strip()))
    return {
        "messages": [
            {"role": "system", "content": SYS_PROMPT},
            {"role": "user", "content": user},
            {"role": "assistant", "content": c.strip()},
        ],
        "meta": {"source": source, "task": "decomp", "unit": unit,
                 "symbol": symbol, "score": 100},
    }


def harvest(limit=None):
    """All 100%-matched, source-extractable functions from the report."""
    if not os.path.exists(forge.REPORT):
        return []
    rep = json.load(open(forge.REPORT))
    out, n_units, n_noasm, n_nosrc = [], 0, 0, 0
    for u in rep.get("units", []):
        unit = u["name"]
        src = forge.unit_source(unit)
        if not src:
            continue
        matched = [f for f in u.get("functions", [])
                   if forge.num(f.get("fuzzy_match_percent")) == 100.0]
        if not matched:
            continue
        n_units += 1
        for f in matched:
            sym = f["name"]
            c = forge.get_function_source(src, sym)
            if not c:
                n_nosrc += 1
                continue  # SDK files lack the .text marker; skip
            asm = forge.fn_asm(unit, sym)
            if not asm:
                n_noasm += 1
                continue
            out.append(example(unit, sym, asm, c, "decomp-harvest"))
            if limit and len(out) >= limit:
                print("  harvest: hit limit %d (units scanned=%d)" % (limit, n_units))
                return out
    print("  harvest: %d pairs from %d units (skipped: no-src=%d no-asm=%d)"
          % (len(out), n_units, n_nosrc, n_noasm))
    return out


def trajectories():
    """MATCHED attempts from the live loop's trajectory log."""
    p = forge.ATTEMPT_LOG
    if not os.path.exists(p):
        return []
    out = []
    for line in open(p, encoding="utf-8"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        if not r.get("match"):
            continue
        asm = forge.fn_asm(r["unit"], r["symbol"])
        if not asm or not r.get("cand"):
            continue
        out.append(example(r["unit"], r["symbol"], asm, r["cand"], "decomp-trajectory"))
    print("  trajectories: %d matched examples" % len(out))
    return out


def main():
    do_harvest = "--no-harvest" not in sys.argv
    limit = None
    if "--harvest-limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--harvest-limit") + 1])

    recs = []
    if do_harvest:
        print("harvesting matched pairs from report.json ...")
        recs += harvest(limit)
    elif os.path.exists(OUT):
        # trajectory-only refresh (recurring hook): keep the prior harvest, don't clobber it
        recs += [json.loads(l) for l in open(OUT, encoding="utf-8") if l.strip()]
        print("  kept %d existing examples (--no-harvest)" % len(recs))
    print("reading matched trajectories ...")
    recs += trajectories()

    # dedup by symbol; a fresh trajectory match wins over the harvested copy
    by_sym = {}
    for r in recs:
        by_sym[r["meta"]["symbol"]] = r
    recs = list(by_sym.values())

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=True) + "\n")

    ntraj = sum(1 for r in recs if r["meta"]["source"] == "decomp-trajectory")
    print("\nwrote %d SFT examples -> %s" % (len(recs), OUT))
    print("  harvest=%d  trajectory=%d  (min for training: 200)"
          % (len(recs) - ntraj, ntraj))
    print("  ready:", len(recs) >= 200)


if __name__ == "__main__":
    main()
