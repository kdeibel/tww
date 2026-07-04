#!/usr/bin/env python3
"""Variant tester for TSequenceProcessor::process — full body replacements."""
import subprocess, sys, json, os

SRC = "src/JSystem/JMessage/processor.cpp"
UNIT = "framework/JSystem/JMessage/processor"
SYMBOL = "process__Q28JMessage18TSequenceProcessorFPCc"
OBJ = r"build\GZLE01\src\JSystem\JMessage\processor.o"
SIG = "const char* TSequenceProcessor::process(const char* stop) {"

PROLOG = """    /* Nonmatching */
    do {
        switch (mStatus) {
        case kStatus_Normal:
            break;
        case kStatus_Jump:
            if (!on_jump_isReady())
                return mCurrent;

            mStatus = kStatus_Normal;
            if (mStatusData.mCallBack(this))
                on_jump(mControl->getMessageEntry(), mControl->getMessageData_begin());
            break;
        case kStatus_Branch:
            {
"""
EPILOG = """            }
            break;
        }

        if (mCurrent == stop) {
            on_end();
            return NULL;
        }

        if (!on_isReady())
            return mCurrent;
    } while (process_character_());

    return NULL;"""

BRANCH_BLOCKS = {
"work_after_rt": """                u32 rt = on_branch_queryResult();
                BranchCallBackWork* work = (BranchCallBackWork*) &mStatusData.mCallBackWork;

                if (rt > 0xFFFF) {
                    switch (rt) {
                    case -1:
                        return mCurrent;
                    case -2:
                        mStatus = kStatus_Normal;
                        break;
                    }
                } else {
                    mStatus = kStatus_Normal;
                    if (rt < work->mTarget && mStatusData.mCallBack(this))
                        on_branch(mControl->getMessageEntry(), mControl->getMessageData_begin());
                }""",
"rt_decl_hoisted": """                u32 rt;
                BranchCallBackWork* work = (BranchCallBackWork*) &mStatusData.mCallBackWork;
                rt = on_branch_queryResult();

                if (rt > 0xFFFF) {
                    switch (rt) {
                    case -1:
                        return mCurrent;
                    case -2:
                        mStatus = kStatus_Normal;
                        break;
                    }
                } else {
                    mStatus = kStatus_Normal;
                    if (rt < work->mTarget && mStatusData.mCallBack(this))
                        on_branch(mControl->getMessageEntry(), mControl->getMessageData_begin());
                }""",
"s32_rt": """                BranchCallBackWork* work = (BranchCallBackWork*) &mStatusData.mCallBackWork;
                s32 rt = on_branch_queryResult();

                if ((u32)rt > 0xFFFF) {
                    switch (rt) {
                    case -1:
                        return mCurrent;
                    case -2:
                        mStatus = kStatus_Normal;
                        break;
                    }
                } else {
                    mStatus = kStatus_Normal;
                    if ((u32)rt < work->mTarget && mStatusData.mCallBack(this))
                        on_branch(mControl->getMessageEntry(), mControl->getMessageData_begin());
                }""",
"const_rt": """                BranchCallBackWork* work = (BranchCallBackWork*) &mStatusData.mCallBackWork;
                const u32 rt = on_branch_queryResult();

                if (rt > 0xFFFF) {
                    switch (rt) {
                    case -1:
                        return mCurrent;
                    case -2:
                        mStatus = kStatus_Normal;
                        break;
                    }
                } else {
                    mStatus = kStatus_Normal;
                    if (rt < work->mTarget && mStatusData.mCallBack(this))
                        on_branch(mControl->getMessageEntry(), mControl->getMessageData_begin());
                }""",
"work_in_else": """                u32 rt = on_branch_queryResult();

                if (rt > 0xFFFF) {
                    switch (rt) {
                    case -1:
                        return mCurrent;
                    case -2:
                        mStatus = kStatus_Normal;
                        break;
                    }
                } else {
                    BranchCallBackWork* work = (BranchCallBackWork*) &mStatusData.mCallBackWork;
                    mStatus = kStatus_Normal;
                    if (rt < work->mTarget && mStatusData.mCallBack(this))
                        on_branch(mControl->getMessageEntry(), mControl->getMessageData_begin());
                }""",
}

with open(SRC, newline="") as f:
    ORIGINAL = f.read()

def set_body(block):
    start = ORIGINAL.index(SIG) + len(SIG)
    end = ORIGINAL.index("\n}", start)
    new = ORIGINAL[:start] + "\n" + PROLOG + block + "\n" + EPILOG + ORIGINAL[end:]
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
    for name, block in BRANCH_BLOCKS.items():
        set_body(block)
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
