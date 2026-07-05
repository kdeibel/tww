#!/usr/bin/env python3
"""Decomp Forge — AI-assisted function matcher for the TWW decompilation.

Commands:
  python forge/forge.py scan            regenerate report, build target list
  python forge/forge.py serve           start dashboard on http://localhost:7878
  python forge/forge.py diff <n>        show compact diff for target n
  python forge/forge.py packet <n>      print AI work packet for target n

The dashboard (forge/dashboard.html) is all buttons — no typing needed.
"""
import json, os, re, subprocess, sys, threading
from http.server import HTTPServer, BaseHTTPRequestHandler

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def _objdiff_binary():
    native = os.path.join(ROOT, "build", "tools", "objdiff-cli")
    if os.name != "nt" and os.path.exists(native):
        return native
    return native + ".exe"

OBJDIFF = _objdiff_binary()
# objdiff-cli v3 dropped `diff -o out --format json`; keep a 2.7.x binary for that.
_DIFF276 = os.path.join(ROOT, "build", "tools", "objdiff-cli-2.7.1")
OBJDIFF_DIFF = _DIFF276 if os.path.exists(_DIFF276) else OBJDIFF
REPORT = os.path.join(ROOT, "build", "report.json")
TARGETS = os.path.join(ROOT, "forge", "targets.json")
CONFIG = os.path.join(ROOT, "forge", "config.json")
PORT = 7878

DEFAULT_CONFIG = {
    "ollama_url": "http://localhost:11434",
    # Resolved through the Soma fleet (soma_fleet() below); this literal is the last-resort
    # fallback only. Forge processes run SOMA MODELS ONLY — operator rule, 2026-07-04.
    "ollama_model": "qwable:q8-fable",
    "max_function_size": 400,
    "min_match_percent": 50,
}

# ---------------------------------------------------------------- soma seam
# This loop is a Soma-conducted job: the model comes from the Soma fleet roster and
# lifecycle events land in the spine ledger. Loop still runs if the spine is down.

SOMA_SPN = os.environ.get("SOMA_SPINE_ENDPOINT", "http://127.0.0.1:7900")
_SOMA_FLEET_FALLBACK = {
    "mind": "qwythos:9b", "hands": "qwable:q8-fable",
    "hands_light": "qwable:q4-fable", "embed": "nomic-embed-text",
    "allowed_prefixes": ["qwythos", "qwable", "soma-engram", "nomic-embed-text"],
}

def _soma_token():
    try:
        with open(os.path.expanduser("~/Soma/.soma/controller.token")) as f:
            return f.read().strip()
    except Exception:
        return ""

def _spn_invoke(tool, args, confirm=None, timeout=8):
    import urllib.request
    body = {"args": args, "role": "maintainer", "mode": "supervised"}
    if confirm:
        body["confirm"] = confirm
    req = urllib.request.Request(
        SOMA_SPN.rstrip("/") + "/spn/tools/%s/invoke" % tool,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + _soma_token()})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())

def soma_fleet():
    """Fleet roster: spine tool if up, else ~/Soma/.soma/fleet.json, else builtins."""
    try:
        r = _spn_invoke("spn_fleet", {})
        f = r.get("result") or {}
        if f.get("hands"):
            return f
    except Exception:
        pass
    try:
        with open(os.path.expanduser("~/Soma/.soma/fleet.json")) as f:
            return {**_SOMA_FLEET_FALLBACK, **json.load(f)}
    except Exception:
        return dict(_SOMA_FLEET_FALLBACK)

def soma_allowed(model, fleet):
    return any(model.startswith(p) for p in
               (fleet.get("allowed_prefixes") or _SOMA_FLEET_FALLBACK["allowed_prefixes"]))

def soma_checkin(note):
    """Two-step confirm-gated ledger event. Best-effort: never blocks the loop."""
    try:
        r = _spn_invoke("spn_checkin", {"note": note, "scope": "tww"})
        tok = ((r.get("decision") or {}).get("confirm"))
        if tok:
            _spn_invoke("spn_checkin", {"note": note, "scope": "tww"}, confirm=tok)
        return True
    except Exception:
        return False

def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG):
        with open(CONFIG) as f:
            cfg.update(json.load(f))
    fleet = soma_fleet()
    if not soma_allowed(cfg["ollama_model"], fleet):
        wanted = cfg["ollama_model"]
        cfg["ollama_model"] = fleet.get("hands") or _SOMA_FLEET_FALLBACK["hands"]
        cfg["model_note"] = "non-Soma model %r overridden to fleet hands %r" % (wanted, cfg["ollama_model"])
    return cfg

def num(x):
    return float(x) if x is not None else 0.0

def run(args, **kw):
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, **kw)

# ---------------------------------------------------------------- scan

def unit_source(unit):
    """Map a report unit name to its source file, e.g.
    framework/JSystem/JMessage/processor -> src/JSystem/JMessage/processor.cpp
    d_a_kb/d/actor/d_a_kb -> src/d/actor/d_a_kb.cpp"""
    parts = unit.split("/")
    tail = "/".join(parts[1:])
    for ext in (".cpp", ".c"):
        p = os.path.join(ROOT, "src", tail + ext)
        if os.path.exists(p):
            return "src/" + tail + ext
    return None

def scan():
    cfg = load_config()
    print("Generating report...")
    r = run([OBJDIFF, "report", "generate", "-o", REPORT])
    if r.returncode != 0:
        print(r.stderr[-500:]); sys.exit(1)
    with open(REPORT) as f:
        rep = json.load(f)
    targets = []
    for u in rep["units"]:
        m = u.get("measures", {})
        if num(m.get("total_code", 0)) == 0:
            continue
        src = unit_source(u["name"])
        if not src:
            continue
        for fn in u.get("functions", []):
            pct = num(fn.get("fuzzy_match_percent", 0))
            size = num(fn.get("size", 0))
            if pct >= 100 or size == 0:
                continue
            if size > cfg["max_function_size"] or pct < cfg["min_match_percent"]:
                continue
            targets.append({
                "unit": u["name"],
                "symbol": fn["name"],
                "demangled": fn.get("demangled_name", fn["name"]),
                "size": int(size),
                "match": round(pct, 2),
                "src": src,
                "unit_match": round(num(m.get("fuzzy_match_percent", 0)), 2),
            })
    # easiest first: already-close and small
    targets.sort(key=lambda t: (-t["match"], t["size"]))
    with open(TARGETS, "w") as f:
        json.dump(targets, f, indent=1)
    print(f"{len(targets)} candidate functions "
          f"(<= {cfg['max_function_size']} bytes, >= {cfg['min_match_percent']}% match)")
    for t in targets[:15]:
        print(f"  {t['match']:6.2f}%  {t['size']:4}b  {t['demangled'][:70]}")
    return targets

def load_targets():
    if not os.path.exists(TARGETS):
        return scan()
    with open(TARGETS) as f:
        return json.load(f)

# ---------------------------------------------------------------- diff

def obj_path(unit):
    tail = "/".join(unit.split("/")[1:])
    return os.path.join("build", "GZLE01", "src", tail + ".o").replace("/", os.sep)

def get_diff(unit, symbol):
    out = os.path.join(ROOT, "build", "fndiff.json")
    r = run([OBJDIFF_DIFF, "diff", "-p", ".", "-u", unit, symbol, "-o", out, "--format", "json"])
    if r.returncode != 0:
        return None
    with open(out) as f:
        return json.load(f)

def diff_rows(unit, symbol):
    d = get_diff(unit, symbol)
    if not d:
        return None, None
    def find(side):
        # objdiff-cli 2.7.x nests symbols under sections
        for sec in d[side].get("sections", []):
            if sec.get("kind") != "SECTION_TEXT":
                continue
            for s in sec.get("symbols", []):
                name = (s.get("symbol") or {}).get("name") or s.get("name")
                if name == symbol:
                    return s
        for s in d[side].get("symbols", []):
            if s.get("name") == symbol:
                return s
        return None
    left, right = find("left"), find("right")
    if not left:
        return None, None
    def rows(sym):
        out = []
        for ins in (sym or {}).get("instructions", []):
            i = ins.get("instruction", {})
            dk = ins.get("diff_kind", "")
            mark = {"DIFF_ARG_MISMATCH": "~", "DIFF_REPLACE": "!", "DIFF_OP_MISMATCH": "!",
                    "DIFF_DELETE": "<", "DIFF_INSERT": ">"}.get(dk, " ")
            out.append([mark, i.get("formatted", ""), i.get("line_number")])
        return out
    pct = right.get("match_percent", 0) if right else 0
    return {"match": pct, "orig": rows(left), "ours": rows(right)}, d

# ---------------------------------------------------------------- source editing

def find_function_span(text, symbol):
    """Locate function body via the repo's '.text <mangled>' comment convention.
    Returns (body_start, body_end) — the span between '{' and its closing '\n}'."""
    m = re.search(r"/\*[^*]*\.text\s+" + re.escape(symbol) + r"\s*\*/", text)
    if not m:
        return None
    brace = text.index("{", m.end())
    end = text.index("\n}", brace)
    return brace + 1, end

def get_function_source(src_rel, symbol):
    p = os.path.join(ROOT, src_rel)
    with open(p, newline="", encoding="latin-1") as f:
        text = f.read()
    span = find_function_span(text, symbol)
    if not span:
        return None
    # include the signature line for context
    sig_start = text.rfind("\n", 0, text.rfind("{", 0, span[0]))
    return text[sig_start + 1: span[1] + 2].replace("\r\n", "\n")

def attempt(src_rel, unit, symbol, new_body):
    """Replace function body, rebuild, score. Keeps change only on 100% match.
    Returns (score, message)."""
    p = os.path.join(ROOT, src_rel)
    with open(p, newline="", encoding="latin-1") as f:
        original = f.read()
    span = find_function_span(original, symbol)
    if not span:
        return None, "function comment marker not found"
    if not new_body.startswith("\n"):
        new_body = "\n" + new_body
    if not new_body.endswith("\n"):
        new_body += "\n"
    candidate = original[:span[0]] + new_body + original[span[1] + 1:]
    try:
        with open(p, "w", newline="", encoding="latin-1") as f:
            f.write(candidate)
        r = run(["ninja", obj_path(unit)])
        if r.returncode != 0:
            with open(p, "w", newline="", encoding="latin-1") as f:
                f.write(original)
            return None, "compile error:\n" + (r.stdout + r.stderr)[-600:]
        d, _ = diff_rows(unit, symbol)
        score = d["match"] if d else 0
        if score == 100.0:
            return 100.0, "MATCHED — change kept"
        with open(p, "w", newline="", encoding="latin-1") as f:
            f.write(original)
        run(["ninja", obj_path(unit)])  # restore object too
        return score, "not a match — source restored"
    except Exception as e:
        with open(p, "w", newline="", encoding="latin-1") as f:
            f.write(original)
        return None, f"error: {e} — source restored"

# ---------------------------------------------------------------- work packet

def make_packet(t):
    d, _ = diff_rows(t["unit"], t["symbol"])
    src = get_function_source(t["src"], t["symbol"]) or "(source not found)"
    lines = [
        "# Decomp match task",
        f"Function: {t['demangled']}",
        f"Mangled: {t['symbol']}",
        f"File: {t['src']}   Current match: {t['match']}%   Size: {t['size']} bytes",
        "",
        "## Current C++ (must be rewritten so MWCC 2.7 emits EXACTLY the original asm)",
        "```cpp", src.rstrip(), "```",
        "",
        "## Target assembly (original game)  |  Our current assembly",
        "```",
    ]
    if d:
        orig, ours = d["orig"], d["ours"]
        n = max(len(orig), len(ours))
        for i in range(n):
            l = orig[i][1] if i < len(orig) else ""
            mk = (orig[i][0] if i < len(orig) else " ") or " "
            r2 = ours[i][1] if i < len(ours) else ""
            lines.append(f"{mk} {l:<36} | {r2}")
    lines += ["```", "",
        "## Known tricks (docs/regalloc.md, docs/decompiling.md)",
        "- regswap: pointer temps, declaration order, avoid reassigning (use `p + 1` not `p++`)",
        "- ~75% match usually means a missing inline (check JGadget/JUT/fopAcM helpers)",
        "- if/else vs ternary generate different branches; case order must follow asm",
        "- check zeldaret/tp for the same function — engine code is shared",
    ]
    return "\n".join(lines)

# ---------------------------------------------------------------- ollama

def ollama_attempt(t, cfg):
    """Ask local Ollama for candidate bodies, try each. Returns log list."""
    import urllib.request
    packet = make_packet(t)
    prompt = (packet + "\n\nWrite ONLY the new function body (the code between the outer "
              "braces, no signature, no braces, no markdown). Preserve any existing "
              "/* comments */ style. One best attempt.")
    log = []
    for i in range(3):
        try:
            req = urllib.request.Request(
                cfg["ollama_url"].rstrip("/") + "/api/generate",
                data=json.dumps({"model": cfg["ollama_model"], "prompt": prompt,
                                 "stream": False}).encode(),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=300) as resp:
                body = json.loads(resp.read())["response"]
        except Exception as e:
            return log + [f"Ollama unavailable: {e}"]
        body = re.sub(r"^```[a-z+]*\n?|```$", "", body.strip(), flags=re.M).strip("\n")
        # Source tree is byte-preserving latin-1; model output is arbitrary unicode
        # (it echoes Japanese literals from packets). Chars >255 would explode the
        # latin-1 write in attempt() — replace them, the compiler rejects them anyway.
        body = body.encode("latin-1", "replace").decode("latin-1")
        body = body.encode("latin-1", errors="replace").decode("latin-1")
        body = "\n".join("    " + ln if ln and not ln.startswith(" ") else ln
                         for ln in body.splitlines())
        score, msg = attempt(t["src"], t["unit"], t["symbol"], body)
        log.append(f"attempt {i+1}: {score if score is not None else 'ERR'}% — {msg}")
        if score == 100.0:
            return log
        prompt += (f"\n\nYour previous attempt scored {score}% ({msg}). "
                   "Analyze the difference and try a different phrasing.")
    return log

# ---------------------------------------------------------------- progress

def project_progress():
    if not os.path.exists(REPORT):
        return {}
    with open(REPORT) as f:
        rep = json.load(f)
    m = rep.get("measures", {})
    return {
        "matched_percent": round(num(m.get("fuzzy_match_percent", 0)), 2),
        "matched_code": int(num(m.get("matched_code", 0))),
        "total_code": int(num(m.get("total_code", 0))),
        "matched_functions": int(num(m.get("matched_functions", 0))),
        "total_functions": int(num(m.get("total_functions", 0))),
    }

# ---------------------------------------------------------------- server

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            with open(os.path.join(ROOT, "forge", "dashboard.html"), "rb") as f:
                return self._send(200, f.read(), "text/html; charset=utf-8")
        if self.path == "/api/state":
            return self._send(200, {"progress": project_progress(),
                                    "targets": load_targets()[:60],
                                    "config": load_config()})
        m = re.match(r"/api/diff\?i=(\d+)", self.path)
        if m:
            t = load_targets()[int(m.group(1))]
            d, _ = diff_rows(t["unit"], t["symbol"])
            return self._send(200, {"target": t, "diff": d,
                                    "source": get_function_source(t["src"], t["symbol"])})
        m = re.match(r"/api/packet\?i=(\d+)", self.path)
        if m:
            t = load_targets()[int(m.group(1))]
            return self._send(200, {"packet": make_packet(t)})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        ln = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(ln) or b"{}") if ln else {}
        if self.path == "/api/scan":
            return self._send(200, {"targets": scan()[:60],
                                    "progress": project_progress()})
        if self.path == "/api/attempt":
            t = load_targets()[int(payload["i"])]
            score, msg = attempt(t["src"], t["unit"], t["symbol"], payload["body"])
            return self._send(200, {"score": score, "message": msg})
        if self.path == "/api/ollama":
            t = load_targets()[int(payload["i"])]
            log = ollama_attempt(t, load_config())
            return self._send(200, {"log": log})
        self._send(404, {"error": "not found"})

def serve():
    if not os.path.exists(TARGETS):
        scan()
    print(f"Decomp Forge dashboard: http://localhost:{PORT}")
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()

# ---------------------------------------------------------------- cli

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "serve"
    if cmd == "scan":
        scan()
    elif cmd == "serve":
        serve()
    elif cmd == "diff":
        t = load_targets()[int(sys.argv[2])]
        d, _ = diff_rows(t["unit"], t["symbol"])
        print(f"{t['demangled']}  match={d['match']:.2f}%")
        n = max(len(d["orig"]), len(d["ours"]))
        for i in range(n):
            l = d["orig"][i][1] if i < len(d["orig"]) else ""
            mk = (d["orig"][i][0] if i < len(d["orig"]) else " ") or " "
            r = d["ours"][i][1] if i < len(d["ours"]) else ""
            print(f"{mk} {l:<38} {r}")
    elif cmd == "packet":
        print(make_packet(load_targets()[int(sys.argv[2])]))
    else:
        print(__doc__)
