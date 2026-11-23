"use strict";
const $ = id => document.getElementById(id);
const state={token:"",tools:[],selected:new Set(),job:null,timer:null,lastEvent:0};
const text=x=>x==null?"":String(x);
const el=(tag,cls,value)=>{const element=document.createElement(tag);if(cls)element.className=cls;if(value!==undefined)element.textContent=text(value);return element;};
async function api(path,body){
 const headers={Accept:"application/json"};
 if(body!==undefined){headers["Content-Type"]="application/json";headers["X-Reconductor-Token"]=state.token;}
 const result=await fetch(path,{method:body===undefined?"GET":"POST",headers,body:body===undefined?undefined:JSON.stringify(body),credentials:"same-origin",cache:"no-store"});
 let data;try{data=await result.json();}catch{throw Error("Invalid local server response.");}
 if(!result.ok)throw Error(data.error||"Request failed");
 return data;
}
function notify(message){const toast=$("toolToast");toast.textContent=message;toast.hidden=false;clearTimeout(notify.timer);notify.timer=setTimeout(()=>toast.hidden=true,6000);}
function updateSelection(){
 const chosen=state.tools.filter(t=>state.selected.has(t.id));
 $("selectedCount").textContent=chosen.length+" selected";
 $("installReview").textContent=chosen.length?chosen.map(t=>t.title+" — "+t.method+" — "+t.package).join("\n"):"Select one or more missing tools above.";
 $("installReview").style.whiteSpace="pre-wrap";
 const can=chosen.length>0 && $("toolConsent").checked && $("toolConfirm").value==="INSTALL" && !state.job;
 $("installSelected").disabled=!can;
}
function startupStatusLabel(status){
 const labels={
  ready:"READY · STARTUP CHECK PASSED",
  detected:"DETECTED · UNTESTED",
  broken:"STARTUP FAILED",
  warning:"CHECK INCONCLUSIVE",
  missing:"MISSING",
  manual:"MANUAL INSTALL",
  "built-in":"BUILT IN"
 };
 return labels[status]||String(status).toUpperCase();
}
function applyBadge(badge,status){
 badge.className="tool-status "+status;
 badge.textContent=startupStatusLabel(status);
}
function card(tool){
 const root=el("article","tool-entry");
 const row=el("div","tool-entry-header");
 const badge=el("span","tool-status");applyBadge(badge,tool.status);
 row.append(el("div","tool-entry-title",tool.title),badge);
 root.append(row,el("p","",tool.description));
 root.append(el("div","tool-meta","Install method: "+({
   "pipx":"isolated Python package (pipx)",
   "managed-git":"official stable source in a private venv",
   "manual-apt":"system package: administrator action",
   "built-in":"included with Reconductor"
 }[tool.method]||tool.method)));
 if(tool.path)root.append(el("div","tool-meta","Executable: "+tool.path));
 if(tool.note)root.append(el("p","tool-note",tool.note));
 if(tool.auto_install){
  const label=el("label","tool-pick");
  const checkbox=el("input");checkbox.type="checkbox";checkbox.checked=state.selected.has(tool.id);
  checkbox.disabled=Boolean(state.job);
  checkbox.addEventListener("change",()=>{
    if(checkbox.checked)state.selected.add(tool.id);else state.selected.delete(tool.id);
    updateSelection();
  });
  label.append(checkbox,el("span","","Select for installation"));root.append(label);
 }
 const footer=el("div","tool-entry-footer");
 if(tool.method!=="built-in"){
  const check=el("button","","Test startup");check.type="button";check.disabled=!tool.path||Boolean(state.job);
  const result=el("pre","tool-test-output");result.hidden=true;
  check.addEventListener("click",async()=>{
   check.disabled=true;result.hidden=false;result.textContent="Testing executable help command (no research request)…";
   try{
    const report=await api("/api/tools/check",{tool:tool.id});
    tool.status=report.status;
    tool.startup_check={status:report.status,message:report.message};
    applyBadge(badge,report.status);
    result.textContent=report.status.toUpperCase()+"\n"+report.message;
   }catch(error){result.textContent="Error: "+error.message;}
   finally{check.disabled=false;}
  });
  footer.append(check);
  const link=el("a","","Official source");link.href=tool.url;link.target="_blank";link.rel="noopener noreferrer";footer.append(link);
  root.append(footer,result);
 }else{
  const link=el("a","","About the service");link.href=tool.url;link.target="_blank";link.rel="noopener noreferrer";footer.append(link);root.append(footer);
 }
 if(tool.startup_check && tool.startup_check.status!=="ready"){
  root.append(el("p","tool-note","Last startup check: "+tool.startup_check.status+". Use Test startup to check again."));
 }
 if(tool.method==="manual-apt"){
  root.append(el("p","tool-note","Manual command on Debian: sudo apt install "+tool.package+". Reconductor will not request sudo credentials from this page."));
 }
 return root;
}
async function refresh(){
 const response=await api("/api/tools");state.tools=response.tools||[];
 const ids=new Set(state.tools.filter(t=>t.auto_install).map(t=>t.id));
 state.selected=new Set([...state.selected].filter(id=>ids.has(id)));
 const place=$("toolCatalog");place.replaceChildren();
 for(const item of state.tools)place.append(card(item));
 updateSelection();
}
function renderEvents(job){
 const events=job.events||[],log=$("installLog");
 if(events.length<state.lastEvent){log.textContent="";state.lastEvent=0;}
 for(let i=state.lastEvent;i<events.length;i++){
  const entry=events[i],message=entry.message||entry.kind;
  log.textContent+=(i?"\n":"")+"["+(entry.id||"system")+"] "+message;
 }
 state.lastEvent=events.length;log.scrollTop=log.scrollHeight;
}
async function poll(){
 if(!state.job)return;
 try{
  const response=await api("/api/tools/jobs/"+encodeURIComponent(state.job));
  const job=response.job;
  renderEvents(job);
  $("progressState").textContent=job.status;
  if(job.status==="running")return;
  clearInterval(state.timer);state.timer=null;state.job=null;
  const results=$("installOutcome");results.replaceChildren();
  for(const item of job.results||[]){
   results.append(el("div","tool-result "+item.state,item.id+" — "+item.state+": "+item.message));
  }
  if(job.error)results.append(el("div","tool-result failed",job.error));
  $("toolConsent").checked=false;$("toolConfirm").value="";
  await refresh();updateSelection();
 }catch(error){notify(error.message);}
}
async function install(){
 const selected=[...state.selected];
 if(!selected.length||!$("toolConsent").checked||$("toolConfirm").value!=="INSTALL")return;
 $("installError").textContent="";
 $("installSelected").disabled=true;
 try{
  const res=await api("/api/tools/install",{
   tools:selected,acknowledge_changes:true,confirm:"INSTALL"
  });
  state.job=res.job_id;state.lastEvent=0;
  $("installProgress").hidden=false;$("installLog").textContent="";$("installOutcome").replaceChildren();
  $("progressState").textContent="running";
  await refresh();
  await poll();
  if(state.job)state.timer=setInterval(poll,1600);
 }catch(error){$("installError").textContent=error.message;state.job=null;updateSelection();}
}
(async()=>{
 try{
  state.token=(await api("/api/session")).token;
  $("refreshTools").addEventListener("click",()=>refresh().catch(e=>notify(e.message)));
  $("toolConsent").addEventListener("change",updateSelection);
  $("toolConfirm").addEventListener("input",updateSelection);
  $("installSelected").addEventListener("click",install);
  await refresh();
 }catch(error){$("toolCatalog").replaceChildren(el("p","error",error.message));}
})();
