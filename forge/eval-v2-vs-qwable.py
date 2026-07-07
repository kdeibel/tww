#!/usr/bin/env python3
"""Larger v2-vs-qwable head-to-head → a single match-rate percentage each.
30 attempt-able held-out near-misses (<=300b, >=85%, matchable-weighted; GX/TRK .c + C++).
Match = true 100% byte-identical (attempt()-objdiff gate). Run with the loop PAUSED.
"""
import json, os, re, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import forge

OLLAMA = "http://127.0.0.1:11434"
TRIES = 2
MODELS = ["soma-decomp-v2:latest", "qwable:q8-fable"]
HELDOUT = ['expandSceneBgmNum__11JAIZelBasicFUl', 'camera_delete__FP20camera_process_class',
 'GXSetNumTexGens', 'GXInitTlutObj', 'dMsg2_aimBrightness__Fv',
 'getNeedBufferSize__Q27JAInter9StreamLibFv', 'proc__9dDetect_cFv',
 'execute__19dPa_ripplePcallBackFP14JPABaseEmitterP15JPABaseParticle',
 'DefaultRadius__11dCamParam_cFPf', 'GXEnableTexOffsets',
 'dMeter_compassRotate__FP18fopMsgM_pane_classP18fopMsgM_pane_classf',
 'setDecodedBufferBlocks__Q27JAInter9StreamLibFUl', 'set_quake__9dDetect_cFPC4cXyz',
 'daMP_Set_PercentMovieVolume__Ff',
 '__ct__Q37JStudio3fvb17TObject_compositeFRCQ47JStudio3fvb4data13TParse_TBlock',
 '__ct__Q37JStudio3fvb16TObject_constantFRCQ47JStudio3fvb4data13TParse_TBlock',
 '__ct__Q37JStudio3fvb18TObject_transitionFRCQ47JStudio3fvb4data13TParse_TBlock',
 '__ct__Q37JStudio3fvb12TObject_listFRCQ47JStudio3fvb4data13TParse_TBlock',
 '__ct__Q37JStudio3fvb22TObject_list_parameterFRCQ47JStudio3fvb4data13TParse_TBlock',
 '__ct__Q37JStudio3fvb15TObject_hermiteFRCQ47JStudio3fvb4data13TParse_TBlock',
 'TRKDispatchMessage', 'GXSetArray', 'arrowRotate__15dOperate_wind_cFP18fopMsgM_pane_classs',
 '__GXSetVAT', 'dMsg2_textPosition__FP14sub_msg2_classUc', 'initHeap__8JAIBasicFv',
 '__SetSURegs', '__DecodePCM__Q27JAInter9StreamLibFv', 'TRK_fill_mem',
 'alloc__Q28JASystem11TDSPChannelFUlUl']

def unload(m):
    try:
        urllib.request.urlopen(urllib.request.Request(OLLAMA + "/api/generate",
            data=json.dumps({"model": m, "keep_alive": 0}).encode(),
            headers={"Content-Type": "application/json"}), timeout=60).read()
    except Exception:
        pass

def gen(model, prompt):
    req = urllib.request.Request(OLLAMA + "/api/generate",
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
    best = -1.0
    for i in range(TRIES):
        try:
            body = clean(gen(model, prompt))
        except Exception:
            break
        score, msg = forge.attempt(t["src"], t["unit"], t["symbol"], body)
        s = forge.num(score) if score is not None else -1
        best = max(best, s)
        if s == 100.0:
            return 100.0
        prompt += f"\n\nYour previous attempt scored {score}% ({msg}). Try a different phrasing."
    return best

def run_model(model, targets):
    print(f"\n=== {model} ===", flush=True)
    for m in MODELS:
        unload(m)
    res = {}
    for t in targets:
        t0 = time.time()
        best = eval_target(model, t)
        res[t["symbol"]] = best
        tag = "MATCH" if best >= 100 else ("err" if best < 0 else f"{best:.1f}%")
        print(f"  {tag:>7}  {t['symbol'][:44]:<44} [{time.time()-t0:.0f}s]", flush=True)
    unload(model)
    return res

def main():
    allt = {x["symbol"]: x for x in json.load(open(os.path.join(forge.ROOT, "forge", "targets.json")))}
    targets = [allt[s] for s in HELDOUT if s in allt]
    n = len(targets)
    print(f"v2 vs qwable — {n} held-out near-misses, {TRIES} tries, match=byte-identical", flush=True)
    results = {m: run_model(m, targets) for m in MODELS}
    print("\n=== RESULT ===")
    out = {"n": n, "results": results, "summary": {}}
    for m in MODELS:
        vals = [results[m][t["symbol"]] for t in targets]
        matched = sum(1 for v in vals if v >= 100)
        compiled = sum(1 for v in vals if v >= 0)
        mean = sum(max(v, 0.0) for v in vals) / n
        rate = 100.0 * matched / n
        print(f"{m:<24} match-rate {rate:5.1f}%  ({matched}/{n})   compiled {compiled}/{n}   mean-best {mean:.1f}%")
        out["summary"][m] = {"match_rate": round(rate, 1), "matched": matched,
                             "compiled": compiled, "mean_best": round(mean, 1)}
    # head-to-head: who uniquely matched what
    a, b = MODELS
    only_a = [s for s in results[a] if results[a][s] >= 100 and results[b][s] < 100]
    only_b = [s for s in results[b] if results[b][s] >= 100 and results[a][s] < 100]
    both = [s for s in results[a] if results[a][s] >= 100 and results[b][s] >= 100]
    print(f"\nboth matched: {len(both)}   only {a.split(':')[0]}: {only_a}   only {b.split(':')[0]}: {only_b}")
    out["head_to_head"] = {"both": both, "only_v2": only_a, "only_qwable": only_b}
    json.dump(out, open(os.path.join(forge.ROOT, "forge", "eval-v2-vs-qwable.json"), "w"), indent=1)
    print("\nwrote forge/eval-v2-vs-qwable.json")

if __name__ == "__main__":
    main()
