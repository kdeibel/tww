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
# held-out attempt-able C++ near-misses (find_function_span resolves these; the SDK
# .c files do NOT resolve, so the local attempt() path can only test C++ game code).
# Balanced 82-99.5% spread; guaranteed not in the matched-answer-key SFT set.
HELDOUT = ["dMeter_compassRotate__FP18fopMsgM_pane_classP18fopMsgM_pane_classf",
           "daMP_Set_PercentMovieVolume__Ff",
           "diff__15J3DIndBlockFullFUl",
           "battleSubActionNockBack__11daNpc_Ji1_cFv",
           "__ct__Q37JStudio3fvb15TObject_hermiteFRCQ47JStudio3fvb4data13TParse_TBlock",
           "DefaultRadius__11dCamParam_cFPf",
           "arrowRotate__15dOperate_wind_cFP18fopMsgM_pane_classs",
           "enlagementSizeTextureCordCalc__15dMap_RoomInfo_cFPfPfPfPfffffff"]

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

def eval_target(model, t):
    packet = forge.make_packet(t)
    prompt = (packet + "\n\nWrite ONLY the new function body (the code between the outer "
              "braces, no signature, no braces, no markdown). Preserve any existing "
              "/* comments */ style. One best attempt.")
    best, note = forge.num(t.get("match")), "baseline"
    for i in range(TRIES):
        try:
            body = clean(gen(model, prompt))
        except Exception as e:
            note = f"gen-err:{e}"; break
        score, msg = forge.attempt(t["src"], t["unit"], t["symbol"], body)
        s = forge.num(score) if score is not None else -1
        if s > best:
            best, note = s, f"try{i+1}:{msg[:30]}"
        if s == 100.0:
            return 100.0, f"MATCH try{i+1}"
        prompt += f"\n\nYour previous attempt scored {score}% ({msg}). Try a different phrasing."
    return best, note

def run_model(model, targets):
    print(f"\n=== {model} ===", flush=True)
    unload("qwable:q8-fable"); unload("soma-decomp:latest")
    res = {}
    for t in targets:
        t0 = time.time()
        best, note = eval_target(model, t)
        res[t["symbol"]] = best
        print(f"  {best:6.2f}%  (base {t['match']:.2f}%)  {t['symbol']:<20} "
              f"{note}  [{time.time()-t0:.0f}s]", flush=True)
    unload(model)
    return res

def main():
    allt = {x["symbol"]: x for x in json.load(open(os.path.join(forge.ROOT, "forge", "targets.json")))}
    targets = [allt[s] for s in HELDOUT if s in allt]
    print(f"Held-out eval: {len(targets)} unmatched C near-misses, {TRIES} tries each")
    for t in targets:
        print(f"  base {t['match']:6.2f}%  {t['size']:4}b  {t['symbol']}")
    a = run_model("soma-decomp:latest", targets)
    b = run_model("qwable:q8-fable", targets)
    print("\n=== SUMMARY (best score per target) ===")
    print(f"{'symbol':<22}{'base':>8}{'soma-decomp':>14}{'qwable':>10}")
    for t in targets:
        s = t["symbol"]
        print(f"{s:<22}{t['match']:>7.2f}%{a[s]:>13.2f}%{b[s]:>9.2f}%")
    def summ(r):
        vals=list(r.values()); return sum(1 for v in vals if v>=100), sum(vals)/len(vals)
    am, amean = summ(a); bm, bmean = summ(b)
    print(f"\nsoma-decomp: {am}/{len(targets)} matched, mean-best {amean:.2f}%")
    print(f"qwable     : {bm}/{len(targets)} matched, mean-best {bmean:.2f}%")
    json.dump({"soma_decomp": a, "qwable": b, "targets": HELDOUT,
               "soma_matched": am, "qwable_matched": bm,
               "soma_mean": amean, "qwable_mean": bmean},
              open(os.path.join(forge.ROOT, "forge", "eval-soma-decomp.json"), "w"), indent=1)
    print("\nwrote forge/eval-soma-decomp.json")

if __name__ == "__main__":
    main()
