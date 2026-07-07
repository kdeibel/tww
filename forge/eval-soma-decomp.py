#!/usr/bin/env python3
"""Head-to-head eval: soma-decomp (fine-tuned specialist) vs qwable (fleet hands).
Held-out set = currently-UNMATCHED C near-misses (definitionally not in the SFT
answer-key set). Reuses forge's real packet->compile->objdiff-gate path via
forge.make_packet + forge.attempt. Run with the decomp loop PAUSED (attempt()
mutates + reverts the source tree; concurrent runs corrupt each other).

Prints per-target best score for each model, then match-count + mean-best summary.
"""
import json, os, re, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import forge

OLLAMA = "http://127.0.0.1:11434"
TRIES = 2
# held-out attempt-able near-misses — now includes GX/TRK .c (the .c apply-path fallback
# made these attempt-able; they're the specialist's TRAINED STRENGTH) plus C++ game code.
# Balanced 70-99.5% spread; all currently unmatched -> guaranteed not in the answer-key set.
MODELS = ["soma-decomp-v2:latest", "soma-decomp:latest", "qwable:q8-fable"]
HELDOUT = ["GXInitTlutObj", "__GXUpdateBPMask", "GXSetChanMatColor",
           "GXSetDispCopyDst", "GXSetChanCtrl",
           "dMeter_compassRotate__FP18fopMsgM_pane_classP18fopMsgM_pane_classf",
           "dMeter_xyBowLightAnime__FP15sub_meter_classi",
           "DefaultRadius__11dCamParam_cFPf",
           "isFmapClose__12dMenu_Fmap_cFv"]

def unload(model):
    try:
        urllib.request.urlopen(urllib.request.Request(
            OLLAMA + "/api/generate",
            data=json.dumps({"model": model, "keep_alive": 0}).encode(),
            headers={"Content-Type": "application/json"}), timeout=60).read()
    except Exception:
        pass

def gen(model, prompt):
    req = urllib.request.Request(
        OLLAMA + "/api/generate",
        data=json.dumps({"model": model, "prompt": prompt, "stream": False,
                         "keep_alive": "5m", "options": {"temperature": 0.2}}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=420) as r:
        return json.loads(r.read())["response"]

def clean(body):
    body = re.sub(r"^```[a-z+]*\n?|```$", "", body.strip(), flags=re.M).strip("\n")
    body = body.encode("latin-1", "replace").decode("latin-1")
    return "\n".join("    " + ln if ln and not ln.startswith(" ") else ln
                     for ln in body.splitlines())

def base271(t):
    """The CURRENT source body's own attempt()-objdiff-2.7.1 score — the in-system baseline.
    attempt()'s 2.7.1 % runs lower than the v3 report %, so candidates must be compared against
    THIS, not t['match'] (v3). Splice the current body back; the score is the near-miss floor
    each model must beat. Cached per (src,symbol)."""
    key = (t["src"], t["symbol"])
    if key not in _base_cache:
        p = os.path.join(forge.ROOT, t["src"])
        original = open(p, newline="", encoding="latin-1").read()
        span = forge.find_function_span(original, t["symbol"])
        body = original[span[0]:span[1] + 1] if span else ""
        score, _ = forge.attempt(t["src"], t["unit"], t["symbol"], body) if span else (None, "")
        _base_cache[key] = forge.num(score) if score is not None else -1.0
    return _base_cache[key]

_base_cache = {}

def eval_target(model, t):
    packet = forge.make_packet(t)
    prompt = (packet + "\n\nWrite ONLY the new function body (the code between the outer "
              "braces, no signature, no braces, no markdown). Preserve any existing "
              "/* comments */ style. One best attempt.")
    best, note = -1.0, "no-compile"   # best CANDIDATE 2.7.1 score (comparable across models)
    for i in range(TRIES):
        try:
            body = clean(gen(model, prompt))
        except Exception as e:
            note = f"gen-err:{e}"; break
        score, msg = forge.attempt(t["src"], t["unit"], t["symbol"], body)
        s = forge.num(score) if score is not None else -1
        if s > best:
            best, note = s, f"try{i+1}:{msg[:26]}"
        if s == 100.0:
            return 100.0, f"MATCH try{i+1}"
        prompt += f"\n\nYour previous attempt scored {score}% ({msg}). Try a different phrasing."
    return best, note

def run_model(model, targets):
    print(f"\n=== {model} ===", flush=True)
    for m in MODELS:
        unload(m)
    res = {}
    for t in targets:
        t0 = time.time()
        best, note = eval_target(model, t)
        res[t["symbol"]] = best
        kind = "C " if t["src"].endswith(".c") else "C++"
        b271 = base271(t)
        comp = "compile-err" if best < 0 else f"{best:6.2f}%"
        print(f"  [{kind}] {comp:>11}  (floor {b271:.2f}%)  {t['symbol'][:36]:<36} "
              f"{note}  [{time.time()-t0:.0f}s]", flush=True)
    unload(model)
    return res

def main():
    allt = {x["symbol"]: x for x in json.load(open(os.path.join(forge.ROOT, "forge", "targets.json")))}
    targets = [allt[s] for s in HELDOUT if s in allt]
    print(f"Held-out 3-way eval: {len(targets)} unmatched near-misses (GX/TRK .c + C++), "
          f"{TRIES} tries each\nmodels: {', '.join(MODELS)}")
    print("computing in-system (2.7.1) baselines ...", flush=True)
    for t in targets:
        kind = "C " if t["src"].endswith(".c") else "C++"
        print(f"  [{kind}] floor {base271(t):6.2f}%  (v3 {t['match']:.2f}%)  {t['size']:4}b  {t['symbol']}",
              flush=True)
    results = {m: run_model(m, targets) for m in MODELS}

    # scoring: candidates + floor are all attempt()-objdiff-2.7.1 (comparable). matched = true
    # 100 (byte-identical .o). improved = best candidate beat the current-body floor. compiled =
    # produced any compilable candidate. mean-best over compiled (-1/no-compile floored to 0).
    print("\n=== SUMMARY (all scores objdiff-2.7.1; matched=byte-identical) ===")
    hdr = f"{'symbol':<30}{'floor':>7}" + "".join(f"{m.split(':')[0][:15]:>16}" for m in MODELS)
    print(hdr)
    for t in targets:
        s = t["symbol"]; fl = base271(t)
        row = f"{s[:30]:<30}{fl:>6.2f}%"
        for m in MODELS:
            v = results[m][s]
            mark = "*" if v >= 100 else ("+" if v > fl + 0.01 else (" " if v >= 0 else "x"))
            cell = "  err" if v < 0 else f"{v:6.2f}%"
            row += f"{cell:>15}{mark}"
        print(row)

    def summ(m):
        vals = [results[m][t["symbol"]] for t in targets]
        matched = sum(1 for v in vals if v >= 100)
        improved = sum(1 for t in targets if results[m][t["symbol"]] > base271(t) + 0.01)
        compiled = sum(1 for v in vals if v >= 0)
        mean = sum(max(v, 0.0) for v in vals) / len(vals)
        return matched, improved, compiled, mean
    print(f"\n{'model':<24}{'matched':>9}{'improved':>10}{'compiled':>10}{'mean-best':>11}")
    out = {"targets": HELDOUT, "floors": {t["symbol"]: base271(t) for t in targets},
           "results": results, "summary": {}}
    for m in MODELS:
        mt, im, cp, mn = summ(m)
        n = len(targets)
        print(f"{m:<24}{mt:>6}/{n}{im:>7}/{n}{cp:>7}/{n}{mn:>10.2f}%")
        out["summary"][m] = {"matched": mt, "improved": im, "compiled": cp, "mean_best": round(mn, 2)}
    json.dump(out, open(os.path.join(forge.ROOT, "forge", "eval-soma-decomp.json"), "w"), indent=1)
    print("\nwrote forge/eval-soma-decomp.json")

if __name__ == "__main__":
    main()
