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
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import forge

QUEUE = os.path.join(forge.ROOT, "forge", "queue")
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
    with open(LOG, "a") as f:
        f.write(line + "\n")


def gpu_busy():
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10).stdout.strip()
        return int(out.splitlines()[0]) > GPU_MAX_MB
    except Exception:
        return False


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
    log("pass start: %d targets, model=%s" % (len(targets), cfg["ollama_model"]))
    wins = 0
    for t in targets:
        key = t["symbol"]
        tries = state["tries"].get(key, 0)
        if tries >= MAX_ROUNDS_PER_SYMBOL or key in SKIP:
            continue
        while gpu_busy():
            log("GPU busy, waiting 120s")
            time.sleep(120)
        log("try #%d %6.2f%% %4db %s" % (tries + 1, t["match"], t["size"], t["demangled"][:70]))
        result = forge.ollama_attempt(t, cfg)
        for line in result:
            log("    " + line)
        state["tries"][key] = tries + 1
        if any("MATCHED" in l for l in result):
            wins += 1
            state["wins"].append(key)
            log("*** WIN %s (kept in working tree, needs review+commit)" % key)
        else:
            try:
                with open(os.path.join(QUEUE, key[:80] + ".md"), "w") as f:
                    f.write(forge.make_packet(t))
            except Exception as e:
                log("packet write failed: %s" % e)
        save_state(state)
    log("pass done: %d wins this pass, %d total" % (wins, len(state["wins"])))
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
