DASHBOARD_HTML = r"""<!doctype html>
<html lang="pl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>OSA Repo Closer</title>
  <style>
    :root{color-scheme:dark;--bg:#070b12;--panel:#0d1420;--line:#243247;--text:#eaf2ff;--muted:#8fa4bf;--ok:#67f7b1;--warn:#ffd166;--bad:#ff6b7a}
    *{box-sizing:border-box} body{margin:0;background:radial-gradient(circle at top,#111c2d,#070b12 42%);font:15px/1.45 system-ui,sans-serif;color:var(--text)}
    main{max-width:920px;margin:auto;padding:18px}.brand{display:flex;justify-content:space-between;gap:12px;align-items:center;margin-bottom:16px}
    h1{font-size:24px;margin:0}.badge{border:1px solid var(--line);padding:6px 10px;border-radius:999px;color:var(--ok);font-weight:700}
    .grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}@media(max-width:720px){.grid{grid-template-columns:1fr}}
    .card{background:rgba(13,20,32,.94);border:1px solid var(--line);border-radius:16px;padding:16px;box-shadow:0 14px 40px #0005}
    label{display:block;color:var(--muted);font-size:12px;margin:10px 0 5px}input,textarea{width:100%;background:#080d15;border:1px solid var(--line);color:var(--text);border-radius:10px;padding:11px}
    textarea{min-height:82px;resize:vertical}button{width:100%;margin-top:14px;border:0;border-radius:12px;padding:13px;font-weight:800;background:linear-gradient(90deg,#48d597,#6aa8ff);color:#04100c}
    button:disabled{opacity:.5}.state{font-size:30px;font-weight:900;letter-spacing:.02em;margin:10px 0}.muted{color:var(--muted)}
    .bar{height:10px;border-radius:999px;background:#111a27;overflow:hidden;margin:12px 0}.bar>div{height:100%;width:0;background:linear-gradient(90deg,#48d597,#6aa8ff);transition:.25s}
    pre{white-space:pre-wrap;word-break:break-word;background:#080d15;border:1px solid var(--line);padding:12px;border-radius:10px;max-height:360px;overflow:auto}
    a{color:#8cc5ff}.kv{display:grid;grid-template-columns:120px 1fr;gap:5px 10px}.danger{color:var(--bad)}.good{color:var(--ok)}
  </style>
</head>
<body>
<main>
  <div class="brand"><div><h1>OSA REPO CLOSER</h1><div class="muted">jedna zgoda → fix → test → PR → CI → merge → closure</div></div><div class="badge">ACTUAL AGENT</div></div>
  <div class="grid">
    <section class="card">
      <h2>Nowy closure</h2>
      <label>API token</label><input id="token" type="password" autocomplete="off" placeholder="MAINTENANCE_API_TOKEN">
      <label>Repo URL</label><input id="repo" placeholder="https://github.com/OWNER/REPO">
      <label>Branch</label><input id="branch" value="main">
      <label>Cel</label><textarea id="goal" placeholder="Domknij repo do zweryfikowanego stanu."></textarea>
      <label>Dozwolone pliki (JSON)</label><textarea id="files">["*"]</textarea>
      <label>Komendy weryfikacyjne (JSON)</label><textarea id="commands">[["python","-m","pytest","-q"]]</textarea>
      <label>CI wait (sekundy)</label><input id="ciwait" type="number" value="180" min="0" max="900">
      <label><input id="nodeploy" type="checkbox" checked style="width:auto"> Zakończ po merge bez deployu</label>
      <button id="run">URUCHOM CLOSURE</button>
      <div id="error" class="danger"></div>
    </section>
    <section class="card">
      <h2>Stan agenta</h2>
      <div id="state" class="state">IDLE</div>
      <div class="bar"><div id="progress"></div></div>
      <div class="kv">
        <div class="muted">Run</div><div id="runid">—</div>
        <div class="muted">PR</div><div id="pr">—</div>
        <div class="muted">Merge SHA</div><div id="merge">—</div>
        <div class="muted">Weryfikacja</div><div id="verify">—</div>
      </div>
      <label>Evidence / wynik</label><pre id="output">{}</pre>
    </section>
  </div>
</main>
<script>
const steps=["CREATED","MAPPING","AUDITING","PLANNING","AWAITING_FIX_APPROVAL","FIXING","REVIEWING","AWAITING_PR_APPROVAL","PUBLISHING_PR","PR_OPEN","MERGING","MERGED","COMPLETED"];
const q=id=>document.getElementById(id);
function render(data){
  const state=data.state||"UNKNOWN"; q("state").textContent=state; q("runid").textContent=data.run_id||"—";
  q("merge").textContent=data.merge_sha||"—"; q("verify").textContent=data.verification_summary||data.failure_reason||"—";
  q("pr").innerHTML=data.pr_url?'<a target="_blank" rel="noreferrer" href="'+data.pr_url+'">'+data.pr_url+'</a>':"—";
  let idx=steps.indexOf(state); if(state==="BLOCKED"||state==="FAILED") idx=Math.max(0,steps.indexOf("PR_OPEN"));
  q("progress").style.width=((Math.max(0,idx)/(steps.length-1))*100)+"%";
  q("state").className="state "+(state==="COMPLETED"?"good":(state==="FAILED"||state==="BLOCKED"?"danger":""));
  q("output").textContent=JSON.stringify(data,null,2);
}
q("run").onclick=async()=>{
  q("error").textContent=""; q("run").disabled=true; q("state").textContent="RUNNING";
  try{
    const payload={
      repo_url:q("repo").value.trim(),branch:q("branch").value.trim()||"main",goal:q("goal").value.trim(),
      allowed_files:JSON.parse(q("files").value),allowed_commands:JSON.parse(q("commands").value),
      ci_wait_seconds:Number(q("ciwait").value||180),close_without_deploy:q("nodeploy").checked
    };
    const res=await fetch("/closures",{method:"POST",headers:{"Content-Type":"application/json","Authorization":"Bearer "+q("token").value},body:JSON.stringify(payload)});
    const data=await res.json(); if(!res.ok) throw new Error(data.detail||JSON.stringify(data)); render(data);
  }catch(e){q("error").textContent=String(e.message||e);q("state").textContent="ERROR"}
  finally{q("run").disabled=false}
};
</script>
</body>
</html>
"""
