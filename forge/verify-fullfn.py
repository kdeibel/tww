import sys, os, json, re, urllib.request, time
sys.path.insert(0, 'forge'); import forge
OLLAMA="http://127.0.0.1:11434"
def unload(m):
    try: urllib.request.urlopen(urllib.request.Request(OLLAMA+"/api/generate",
        data=json.dumps({"model":m,"keep_alive":0}).encode(),
        headers={"Content-Type":"application/json"}),timeout=60).read()
    except: pass
def gen(m,p):
    req=urllib.request.Request(OLLAMA+"/api/generate",
        data=json.dumps({"model":m,"prompt":p,"stream":False,"keep_alive":"5m",
        "options":{"temperature":0.2}}).encode(),headers={"Content-Type":"application/json"})
    return json.loads(urllib.request.urlopen(req,timeout=300).read())["response"]
def extract_body(out):
    out=re.sub(r"^```[a-z+]*\n?|```$","",out.strip(),flags=re.M).strip("\n")
    # if it's a full function (has a signature then a brace), take the inner {...}
    b=out.find("{"); e=out.rfind("}")
    if b!=-1 and e!=-1 and e>b:
        # only strip if there's a signature before the first brace (heuristic: '(' before '{')
        head=out[:b]
        if "(" in head or "::" in head:
            out=out[b+1:e]
    out=out.encode("latin-1","replace").decode("latin-1")
    return "\n".join("    "+ln if ln and not ln.startswith(" ") else ln for ln in out.splitlines())
allt={x["symbol"]:x for x in json.load(open("forge/targets.json"))}
unload("qwable:q8-fable")
for sym in ["battleSubActionNockBack__11daNpc_Ji1_cFv","DefaultRadius__11dCamParam_cFPf","dMeter_compassRotate__FP18fopMsgM_pane_classP18fopMsgM_pane_classf"]:
    t=allt[sym]
    p=forge.make_packet(t)+"\n\nWrite the corrected C++ function so MWCC emits the target asm. Output the function."
    t0=time.time(); raw=gen("soma-decomp:latest",p)
    body=extract_body(raw)
    score,msg=forge.attempt(t["src"],t["unit"],t["symbol"],body)
    print("%-26s base=%.2f%%  full-fn-adapter score=%s  (%s)  [%.0fs]"%(sym[:26],t["match"],score,str(msg)[:30],time.time()-t0))
unload("soma-decomp:latest")
