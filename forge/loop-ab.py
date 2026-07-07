#!/usr/bin/env python3
"""Loop-faithful A/B: soma-decomp-v2 vs qwable as the loop's PROPOSER.
3 tries per target (matches autoloop's ollama_attempt), 40 held-out near-misses.
Per model measures the full loop-value signal:
  matched   = direct 100% byte-identical (immediate loop win)
  perm_elig = best >= PERMUTE_AT(94) on a .c unit -> the loop would trigger the permuter
              (the only model-dependent path to a permuter win: reach 94% to fire it)
  compiled  = produced any compilable candidate
  mean_best = mean best objdiff-2.7.1 candidate score
Run with the loop PAUSED (attempt() mutates+reverts the tree).
"""
import json, os, re, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import forge

OLLAMA = "http://127.0.0.1:11434"
TRIES = 3
PERMUTE_AT = 94.0
MODELS = ["soma-decomp-v2:latest", "qwable:q8-fable"]
SYMS = json.load(open("/tmp/claude-1000/-var-home-Kenny-Documents-ForgeEngine-ideas-tww/"
                      "537eff15-1269-4470-a418-985350aa97ef/scratchpad/ab-syms.json"))

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
        isc = t["src"].endswith(".c")
        tag = ("MATCH" if best >= 100 else
               ("PERM94" if (best >= PERMUTE_AT and isc) else
                ("err" if best < 0 else f"{best:.0f}%")))
        print(f"  {tag:>7}  {'C ' if isc else 'C++'} {t['symbol'][:40]:<40} [{time.time()-t0:.0f}s]", flush=True)
    unload(model)
    return res

def main():
    allt = {x["symbol"]: x for x in json.load(open(os.path.join(forge.ROOT, "forge", "targets.json")))}
    targets = [allt[s] for s in SYMS if s in allt]
    n = len(targets)
    print(f"Loop A/B — {n} targets, {TRIES} tries (loop-faithful), match=byte-identical", flush=True)
    results = {m: run_model(m, targets) for m in MODELS}

    print("\n=== RESULT ===")
    out = {"n": n, "tries": TRIES, "results": results, "summary": {}, "perm_elig_c": {}}
    for m in MODELS:
        matched = [t["symbol"] for t in targets if results[m][t["symbol"]] >= 100]
        perm = [t["symbol"] for t in targets
                if results[m][t["symbol"]] >= PERMUTE_AT and results[m][t["symbol"]] < 100
                and t["src"].endswith(".c")]
        compiled = sum(1 for t in targets if results[m][t["symbol"]] >= 0)
        mean = sum(max(results[m][t["symbol"]], 0.0) for t in targets) / n
        print(f"{m:<24} matched {len(matched)}/{n}  perm94-triggers {len(perm)}  "
              f"compiled {compiled}/{n}  mean-best {mean:.1f}%")
        out["summary"][m] = {"matched": len(matched), "matched_syms": matched,
                             "perm_triggers": len(perm), "compiled": compiled,
                             "mean_best": round(mean, 1)}
        out["perm_elig_c"][m] = perm
    json.dump(out, open(os.path.join(forge.ROOT, "forge", "loop-ab.json"), "w"), indent=1)
    print("\nwrote forge/loop-ab.json")

if __name__ == "__main__":
    main()
