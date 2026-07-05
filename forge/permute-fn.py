#!/usr/bin/env python3
"""Set up a decomp-permuter scratch for one function and (optionally) run it.

Usage: python3 forge/permute-fn.py <unit> <symbol> [--run SECONDS]
Example:
  python3 forge/permute-fn.py framework/dolphin/gx/GXTev GXSetTevColorOp --run 600

Builds tools/permuter/scratch/<symbol>/ with:
  base.c      the unit's full source (permuter mutates the named function)
  target.o    dtk-extracted original object
  compile.sh  exact mwcc command for the unit (from compile_commands.json)
  settings.toml
"""
import json, os, re, shlex, shutil, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "forge"))
import forge

def main():
    unit, symbol = sys.argv[1], sys.argv[2]
    run_secs = 0
    if "--run" in sys.argv:
        run_secs = int(sys.argv[sys.argv.index("--run") + 1])
    src = forge.unit_source(unit)
    if not src:
        sys.exit("no source for unit " + unit)
    tail = "/".join(unit.split("/")[1:])
    target_o = os.path.join(ROOT, "build", "GZLE01", "obj", tail + ".o")
    if not os.path.exists(target_o):
        sys.exit("no target obj " + target_o)

    # exact compile command for this unit (from ninja, not the clangd shim)
    our_o = "build/GZLE01/src/" + tail + ".o"
    r = subprocess.run(["ninja", "-t", "commands", our_o], capture_output=True, text=True, cwd=ROOT)
    cmd = None
    for line in r.stdout.splitlines():
        if "mwcceppc" in line and (src in line or src.replace("/", "\\") in line):
            cmd = line.split("&&")[0].strip()
            break
    if not cmd:
        sys.exit("no mwcc command found via ninja for " + our_o)
    # normalize: compile stdin-name to $1, output to $2
    parts = shlex.split(cmd)
    out = []
    skip = False
    for i, a in enumerate(parts):
        if skip: skip = False; continue
        if a == "-c": skip = False
        if a.replace("\\\\", "/").endswith(src):
            out.append('"$1"'); continue
        if a == "-o":
            # permuter invokes: compile.sh <input.c> -o <output.o>
            out.append(a); out.append('"$3"'); skip = True; continue
        out.append(shlex.quote(a))
    scratch = os.path.join(ROOT, "tools", "permuter", "scratch", symbol[:60])
    os.makedirs(scratch, exist_ok=True)
    # permuter needs a self-contained (preprocessed) base.c — it re-runs host
    # `cpp -nostdinc` which can't see the project include dirs. Preprocess with
    # the real mwcc (-E) so target macros/defines are exact.
    pre = []
    skip = False
    for a in parts:
        if skip: skip = False; continue
        if a == "-c": pre.append("-E"); continue
        if a == "-o": skip = True; continue
        pre.append(a)
    # tree is byte-preserving latin-1 (Japanese literals) — never decode as utf-8
    r = subprocess.run(pre, capture_output=True, cwd=ROOT)
    out = r.stdout.decode("latin-1")
    if r.returncode != 0 or not out.strip():
        sys.exit("mwcc -E preprocess failed:\n" + r.stderr.decode("latin-1")[-2000:])
    # permuter re-runs host cpp on base.c and decodes utf-8; squash every high
    # byte to '?' (1:1 width, string-literal sizes preserved)
    out = "".join(c if ord(c) < 128 else "?" for c in out)
    with open(os.path.join(scratch, "base.c"), "w") as f:
        f.write(out.replace("\r\n", "\n"))
    shutil.copy(target_o, os.path.join(scratch, "target.o"))
    with open(os.path.join(scratch, "compile.sh"), "w") as f:
        f.write("#!/bin/sh\ncd %s\n%s\n" % (shlex.quote(ROOT), " ".join(out)))
    os.chmod(os.path.join(scratch, "compile.sh"), 0o755)
    objdump = os.path.join(ROOT, "build", "binutils", "powerpc-eabi-objdump")
    with open(os.path.join(scratch, "settings.toml"), "w") as f:
        f.write('func_name = "%s"\ncompiler_type = "mwcc"\n' % symbol)
        # permuter's scorer defaults to a PATH powerpc-eabi-objdump; point it at
        # the dtk-bundled one (arch default args must be repeated — they're
        # dropped when objdump_command is set)
        f.write('objdump_command = "%s -dr -EB -mpowerpc -M broadway"\n' % objdump)
    print("scratch ready:", scratch)
    if run_secs:
        subprocess.run([sys.executable, os.path.join(ROOT, "tools", "permuter", "permuter.py"),
                        scratch, "--stop-on-zero", "--better-only"],
                       timeout=run_secs, cwd=os.path.join(ROOT, "tools", "permuter"))

if __name__ == "__main__":
    try:
        main()
    except subprocess.TimeoutExpired:
        print("permuter time budget reached")
