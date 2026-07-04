#!/usr/bin/env python3
"""Try multiple source phrasings for one function, report match % for each.
Prototype of Decomp Forge's retry loop.
Usage: python tools/try_variants.py"""
import subprocess, sys, json, os

SRC = "src/JSystem/JMessage/processor.cpp"
UNIT = "framework/JSystem/JMessage/processor"
SYMBOL = "process_branch___Q28JMessage18TSequenceProcessorFPQ28JMessage18TSequenceProcessorUl"
OBJ = r"build\GZLE01\src\JSystem\JMessage\processor.o"
SIG = "bool TSequenceProcessor::process_branch_(TSequenceProcessor* proc, u32 choice) {"

VARIANTS = {
"plain": """    /* Nonmatching */
    BranchCallBackWork* work = (BranchCallBackWork*) &proc->mStatusData.mCallBackWork;
    return process_setMessage_code_(proc->mControl, ((u32*)work->mTable)[choice]);""",
"const_table": """    /* Nonmatching */
    BranchCallBackWork* work = (BranchCallBackWork*) &proc->mStatusData.mCallBackWork;
    return process_setMessage_code_(proc->mControl, ((const u32*)work->mTable)[choice]);""",
"deref_add": """    /* Nonmatching */
    BranchCallBackWork* work = (BranchCallBackWork*) &proc->mStatusData.mCallBackWork;
    return process_setMessage_code_(proc->mControl, *((u32*)work->mTable + choice));""",
"table_temp": """    /* Nonmatching */
    BranchCallBackWork* work = (BranchCallBackWork*) &proc->mStatusData.mCallBackWork;
    const u32* table = (const u32*)work->mTable;
    return process_setMessage_code_(proc->mControl, table[choice]);""",
"int_choice": """    /* Nonmatching */
    BranchCallBackWork* work = (BranchCallBackWork*) &proc->mStatusData.mCallBackWork;
    return process_setMessage_code_(proc->mControl, ((u32*)work->mTable)[(int)choice]);""",
"parse_inline": """    /* Nonmatching */
    BranchCallBackWork* work = (BranchCallBackWork*) &proc->mStatusData.mCallBackWork;
    return process_setMessage_code_(proc->mControl, JGadget::binary::TParseValue<JGadget::binary::TParseValue_endian_big_<u32> >::parse((const u32*)work->mTable + choice));""",
"code_temp_only": """    /* Nonmatching */
    BranchCallBackWork* work = (BranchCallBackWork*) &proc->mStatusData.mCallBackWork;
    u32 code = ((u32*)work->mTable)[choice];
    return process_setMessage_code_(proc->mControl, code);""",
}

with open(SRC, newline="") as f:
    ORIGINAL = f.read()

def set_body(body):
    start = ORIGINAL.index(SIG) + len(SIG)
    end = ORIGINAL.index("\n}", start)
    new = ORIGINAL[:start] + "\n" + body + ORIGINAL[end:]
    with open(SRC, "w", newline="") as f:
        f.write(new)

def restore():
    with open(SRC, "w", newline="") as f:
        f.write(ORIGINAL)

def build_and_score():
    r = subprocess.run(["ninja", OBJ], capture_output=True, text=True)
    if r.returncode != 0:
        return None, (r.stdout + r.stderr)[-300:]
    out = os.path.join("build", "fndiff.json")
    subprocess.run([os.path.join("build","tools","objdiff-cli.exe"), "diff", "-p", ".",
                    "-u", UNIT, SYMBOL, "-o", out, "--format", "json"],
                   check=True, capture_output=True)
    with open(out) as f:
        d = json.load(f)
    for sym in d["right"]["symbols"]:
        if sym.get("name") == SYMBOL:
            return sym.get("match_percent", 0), None
    return None, "symbol missing"

try:
    for name, body in VARIANTS.items():
        set_body(body)
        score, err = build_and_score()
        if score is None:
            print(f"{name:<20} BUILD FAILED: {err}")
        else:
            print(f"{name:<20} {score:.2f}%")
            if score == 100.0:
                print(f"*** MATCHED with variant '{name}' — leaving it in place ***")
                sys.exit(0)
    restore()
    print("no match found — original restored")
finally:
    if sys.exc_info()[0] not in (None, SystemExit):
        restore()
        print("(exception — original restored)")
