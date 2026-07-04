#!/usr/bin/env python3
"""Compact side-by-side function diff using objdiff-cli JSON output.
Usage: python tools/fndiff.py <unit> <symbol>
Prints original (target) vs current (base) assembly with mismatch markers.
This is a prototype piece of Decomp Forge."""
import json, subprocess, sys, os

def get_diff(unit, symbol, project="."):
    out = os.path.join("build", "fndiff.json")
    subprocess.run([
        os.path.join("build", "tools", "objdiff-cli.exe"),
        "diff", "-p", project, "-u", unit, symbol,
        "-o", out, "--format", "json",
    ], check=True, capture_output=True)
    with open(out) as f:
        return json.load(f)

def find_symbol(side, symbol):
    for sym in side.get("symbols", []):
        if sym.get("name") == symbol:
            return sym
    return None

def fmt_rows(sym):
    rows = []
    for ins in sym.get("instructions", []):
        i = ins.get("instruction", {})
        marker = " "
        dk = ins.get("diff_kind")
        if dk == "DIFF_ARG_MISMATCH":
            marker = "~"
        elif dk in ("DIFF_REPLACE", "DIFF_OP_MISMATCH"):
            marker = "!"
        elif dk == "DIFF_DELETE":
            marker = "<"
        elif dk == "DIFF_INSERT":
            marker = ">"
        rows.append((marker, i.get("formatted", ""), i.get("line_number")))
    return rows

def main():
    unit, symbol = sys.argv[1], sys.argv[2]
    d = get_diff(unit, symbol)
    left = find_symbol(d["left"], symbol)   # original game
    right = find_symbol(d["right"], symbol) # our build
    if not left or not right:
        print("symbol not found on both sides")
        sys.exit(1)
    print(f"match: {right.get('match_percent', 0):.2f}%")
    lrows, rrows = fmt_rows(left), fmt_rows(right)
    n = max(len(lrows), len(rrows))
    print(f"{'':1} {'ORIGINAL':<38} {'OURS':<38} {'src line'}")
    for i in range(n):
        lm, lf = (lrows[i][0], lrows[i][1]) if i < len(lrows) else (" ", "")
        rm, rf, ln = (rrows[i][0], rrows[i][1], rrows[i][2]) if i < len(rrows) else (" ", "", "")
        mark = lm if lm != " " else rm
        line = f" L{ln}" if ln else ""
        print(f"{mark} {lf:<38} {rf:<38}{line}")

if __name__ == "__main__":
    main()
