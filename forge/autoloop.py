#!/usr/bin/env python3
"""Decomp Forge autoloop — local-model function matcher.

Runs forever, fully offline:
  1. scan targets (<=400b, >=50% fuzzy match)
  2. for each untried target, ask local Ollama for candidate bodies
     (forge.ollama_attempt: compile + objdiff gate, keeps ONLY 100% matches,
      auto-reverts everything else)
  3. wins stay in the working tree for human/cloud review + commit
  4. failures get their work packet written to forge/queue/ for cloud pickup

State in forge/autoloop-state.json (attempt counts per symbol, capped).
Log in forge/autoloop.log.
"""
import datetime
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import forge

QUEUE = os.path.join(forge.ROOT, "forge", "queue")
TICKET = os.path.expanduser("~/Soma/.autoloop/now-ticket.json")
LOG = os.path.join(forge.ROOT, "forge", "autoloop.log")
STATE = os.path.join(forge.ROOT, "forge", "autoloop-state.json")
MAX_ROUNDS_PER_SYMBOL = 2   # each round = 3 ollama attempts inside forge
# permanently unfixable at object level (dtk cannot reloc out-of-section literals)
SKIP = {"__OSThreadInit"}
PASS_SLEEP = 300            # seconds between full passes
GPU_MAX_MB = 11000          # skip work if something else is hogging VRAM


def log(msg):
    line = "[%s] %s" % (datetime.datetime.now().strftime("%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8", errors="replace") as f:
        f.write(line + "\n")


_ticket = {"source": "tww-decomp", "title": "TWW decomp autoloop", "state": "running",
           "detail": "", "item": "", "recent": [], "done": 0, "total": 0, "wins": 0, "queue": 0}


def ticket(**kw):
    """Publish live in-progress state for the Soma Core ticket panel."""
    _ticket.update(kw)
    _ticket["at"] = datetime.datetime.now().isoformat(timespec="seconds")
    try:
        _ticket["queue"] = len([f for f in os.listdir(QUEUE) if f.endswith(".md")])
    except Exception:
        pass
    try:
        tmp = TICKET + ".tmp"
        with open(tmp, "w") as f:
            json.dump(_ticket, f)
        os.replace(tmp, TICKET)
    except Exception:
        pass


def recent(line):
    _ticket["recent"] = (_ticket.get("recent") or [])[-5:] + [line]


def gpu_busy():
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10).stdout.strip()
        return int(out.splitlines()[0]) > GPU_MAX_MB
    except Exception:
        return False


def pool_blocked(t):
    """True when the function's code is already byte-perfect and only literal-pool
    symbol ordering differs (objdiff data_value view == 100%) — no source edit can
    improve it until the unit's other stubs are matched. Not a real target."""
    out = os.path.join(forge.ROOT, "build", "fndiff-loop.json")
    r = forge.run([forge.OBJDIFF_DIFF, "diff", "-p", ".", "-u", t["unit"], t["symbol"],
                   "-c", "functionRelocDiffs=data_value", "-o", out, "--format", "json"])
    if r.returncode != 0:
        return False
    try:
        with open(out) as f:
            d = json.load(f)
        for sec in d["right"].get("sections", []):
            if sec.get("kind") != "SECTION_TEXT":
                continue
            for s in sec.get("symbols", []):
                if ((s.get("symbol") or {}).get("name")) == t["symbol"]:
                    return s.get("match_percent") == 100.0
    except Exception:
        pass
    return False


PERMUTE_AT = 94.0           # near-miss threshold: hand the fn to decomp-permuter
PERMUTE_BUDGET = 600        # seconds per permuter run
_permuter = {"proc": None, "sym": None}


def maybe_permute(t, best_pct):
    """Near-miss hook: schedule a background decomp-permuter run (one at a time,
    CPU-only — no GPU contention). Candidates land in
    tools/permuter/scratch/<symbol>/output-* for review."""
    p = _permuter["proc"]
    if p is not None and p.poll() is None:
        return
    logf = open(os.path.join(forge.ROOT, "forge", "permuter.log"), "a")
    _permuter["proc"] = subprocess.Popen(
        [sys.executable, os.path.join(forge.ROOT, "forge", "permute-fn.py"),
         t["unit"], t["symbol"], "--run", str(PERMUTE_BUDGET)],
        stdout=logf, stderr=subprocess.STDOUT, cwd=forge.ROOT)
    _permuter["sym"] = t["symbol"]
    log("permuter scheduled (%ds budget): %s at %.2f%%" % (PERMUTE_BUDGET, t["symbol"], best_pct))
    recent("permuter: %s (%.1f%%)" % (t["demangled"][:40], best_pct))


def load_state():
    if os.path.exists(STATE):
        with open(STATE) as f:
            return json.load(f)
    return {"tries": {}, "wins": []}


def save_state(state):
    with open(STATE, "w") as f:
        json.dump(state, f, indent=1)


def one_pass():
    state = load_state()
    cfg = forge.load_config()
    targets = forge.scan()
    todo = [t for t in targets
            if state["tries"].get(t["symbol"], 0) < MAX_ROUNDS_PER_SYMBOL and t["symbol"] not in SKIP]
    log("pass start: %d targets (%d to try), model=%s" % (len(targets), len(todo), cfg["ollama_model"]))
    if cfg.get("model_note"):
        log("SOMA: " + cfg["model_note"])
    forge.soma_checkin("TWW autoloop pass start: %d targets (%d to try), model=%s%s"
                       % (len(targets), len(todo), cfg["ollama_model"],
                          " [" + cfg["model_note"] + "]" if cfg.get("model_note") else ""))
    ticket(state="running", total=len(todo), done=0, wins=len(state["wins"]),
           detail="model %s · %d targets" % (cfg["ollama_model"], len(todo)))
    wins = 0
    for n, t in enumerate(todo):
        key = t["symbol"]
        tries = state["tries"].get(key, 0)
        while os.path.exists(os.path.join(forge.ROOT, "forge", "PAUSE")):
            ticket(state="paused (forge/PAUSE flag)")
            time.sleep(15)
        while gpu_busy():
            log("GPU busy, waiting 120s")
            ticket(state="waiting-gpu")
            time.sleep(120)
        if pool_blocked(t):
            log("pool-blocked (code already exact, literal pool awaits unit stubs): %s" % t["demangled"][:70])
            state["tries"][key] = MAX_ROUNDS_PER_SYMBOL
            save_state(state)
            ticket(done=n + 1)
            continue
        log("try #%d %6.2f%% %4db %s" % (tries + 1, t["match"], t["size"], t["demangled"][:70]))
        ticket(state="matching", done=n, item="%s (%db, %.2f%%)" % (t["demangled"][:60], t["size"], t["match"]))
        try:
            result = forge.ollama_attempt(t, cfg)
        except Exception as e:
            result = ["attempt crashed: %r" % e]
        for line in result:
            log("    " + line)
            recent(("%s: " % t["demangled"][:28]) + line.strip()[:90])
        state["tries"][key] = tries + 1
        if any("MATCHED" in l for l in result):
            wins += 1
            state["wins"].append(key)
            log("*** WIN %s (kept in working tree, needs review+commit)" % key)
            ticket(wins=len(state["wins"]))
        else:
            best = max([float(m.group(1)) for l in result
                        for m in [re.search(r"attempt \d+: ([\d.]+)%", l)] if m] or [0.0])
            best = max(best, forge.num(t.get("match")))
            if best >= PERMUTE_AT:
                maybe_permute(t, best)
            try:
                with open(os.path.join(QUEUE, key[:80] + ".md"), "w") as f:
                    f.write(forge.make_packet(t))
            except Exception as e:
                log("packet write failed: %s" % e)
        save_state(state)
        ticket(done=n + 1)
    log("pass done: %d wins this pass, %d total" % (wins, len(state["wins"])))
    forge.soma_checkin("TWW autoloop pass done: %d wins this pass, %d total matched" % (wins, len(state["wins"])))
    ticket(state="idle (between passes)", item="", detail="next pass in %ds" % PASS_SLEEP)
    return wins


if __name__ == "__main__":
    os.makedirs(QUEUE, exist_ok=True)
    log("=== autoloop boot (pid %d) ===" % os.getpid())
    while True:
        try:
            one_pass()
        except KeyboardInterrupt:
            log("interrupted, exiting")
            break
        except Exception as e:
            log("pass error: %r" % e)
        time.sleep(PASS_SLEEP)
