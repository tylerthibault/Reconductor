"use strict";
const $ = id => document.getElementById(id);
const s = {token:"",cases:[],id:null,data:null,tab:"overview",graph:null,job:null,timer:null,from:null,relation:"possible association"};
const palette={subject:"#69adfc",person:"#69adfc",clue:"#51d6b4",lead:"#f7bb74",finding:"#aa98f6"};
const txt=x=>x==null?"":String(x);
const short=(x,n=80)=>txt(x).length>n?txt(x).slice(0,n-1)+"…":txt(x);
function el(tag,cls,value){const e=document.createElement(tag);if(cls)e.className=cls;if(value!==undefined)e.textContent=txt(value);return e;}
function flash(t){const e=$("toast");e.textContent=t;e.hidden=false;clearTimeout(flash.timer);flash.timer=setTimeout(()=>e.hidden=true,5000);}
async function api(path,body){
 const headers={Accept:"application/json"};if(body!==undefined){headers["Content-Type"]="application/json";headers["X-Reconductor-Token"]=s.token;}
 const r=await fetch(path,{method:body===undefined?"GET":"POST",headers,body:body===undefined?undefined:JSON.stringify(body),credentials:"same-origin",cache:"no-store"});
 let data;try{data=await r.json();}catch{throw Error("Invalid local server response");}if(!r.ok)throw Error(data.error||"Request failed");return data;
}
async function cases(wanted){
 const result=await api("/api/cases");s.cases=result.cases||[];
 const list=$("caseList");list.replaceChildren();
 if(!s.cases.length)list.append(el("p","empty","No saved cases yet."));
 s.cases.forEach(c=>{
  const b=el("button","case-option"+(s.id===c.id?" active":""));
  b.append(el("strong","",short(c.target||"Untitled",44)));
  const foot=el("small");foot.append(el("span","",c.depth),el("span","",c.status));b.append(foot);
  b.addEventListener("click",()=>choose(c.id));list.append(b);
 });
 const id=wanted||s.id||(s.cases.length?s.cases[0].id:null);
 if(id&&s.cases.some(c=>c.id===id))await choose(id);
 else{$("workspace").hidden=true;$("welcome").hidden=false;s.id=null;}
}
async function choose(id){
 try{
  const d=await api("/api/cases/"+encodeURIComponent(id));s.id=id;s.data=d;s.from=null;
  $("welcome").hidden=true;$("workspace").hidden=false;
  document.querySelectorAll(".case-option").forEach((x,i)=>x.classList.toggle("active",s.cases[i]?.id===id));
  $("breadcrumbCase").textContent=short(d.case.target||"Case",36);
  $("caseId").textContent="CASE / "+d.case.id;
  $("caseTitle").textContent=d.case.target||"Investigation";
  let date="Unknown";if(d.case.created_at){const dt=new Date(d.case.created_at);if(!isNaN(dt.getTime()))date=dt.toLocaleString();}
  $("caseDate").textContent=date;$("caseDepth").textContent=txt(d.case.depth).toUpperCase()+" DEPTH";
  $("caseStatus").textContent=d.case.status||"Unknown";$("caseStatus").classList.toggle("complete",d.case.status==="completed");
  $("mTools").textContent=(d.case.steps||[]).length;$("mFindings").textContent=d.findings.length;$("mLeads").textContent=(d.case.leads||[]).length;
  overview(d);evidence(d);const oldCanvas=$("graph"),newCanvas=oldCanvas.cloneNode(false);oldCanvas.replaceWith(newCanvas);s.graph=new Graph(newCanvas,d.graph);graphNodes();inspector(null);tab(s.tab);
 }catch(e){flash(e.message);}
}
function tab(name){
 s.tab=name;["overview","graph","evidence"].forEach(k=>$("tab-"+k).hidden=(name!==k));
 document.querySelectorAll(".tab").forEach(b=>{b.classList.toggle("active",b.dataset.tab===name);b.setAttribute("aria-selected",String(b.dataset.tab===name));});
 if(name==="graph"&&s.graph)requestAnimationFrame(()=>{s.graph.resize();s.graph.fit();});
}
function overview(d){
 $("findingsCount").textContent=d.findings.length+" parsed observations";
 const found=$("findingsList");found.replaceChildren();
 if(!d.findings.length)found.append(el("p","empty","No recognizable structured findings yet. Review the tool outputs under Evidence & tools."));
 d.findings.forEach(f=>{
  const row=el("div","finding"),icon=el("div","finding-icon",f.url?"↗":"◇"),copy=el("div");
  copy.append(el("strong","",f.type||"Observation"),el("div","value",f.value));
  copy.append(el("small","",f.tool+" · "+f.evidence+" · Unverified"));
  if(f.url&&/^https?:\/\//i.test(f.url)){
   const a=el("a","","Open original source");a.href=f.url;a.target="_blank";a.rel="noreferrer noopener";copy.append(document.createTextNode("  "),a);
  }row.append(icon,copy);found.append(row);
 });
 const clues=$("clueList");clues.replaceChildren();
 (d.case.clues||[{kind:d.case.target_type,value:d.case.target}]).forEach(c=>{
  const it=el("div","item");it.append(el("strong","",txt(c.kind).toUpperCase()),el("span","",c.value));clues.append(it);
 });
 if(d.case.location)clues.append(el("div","item","Location: "+d.case.location));
 const cv=$("coverageList");cv.replaceChildren();
 const coverage=d.case.coverage||{digital_footprint:"Legacy scan: not recorded",business_records:"Not searched",property_records:"Not searched",court_records:"Not searched"};
 Object.entries(coverage).forEach(([key,value])=>{const it=el("div","item");it.append(el("strong","",key.replaceAll("_"," ")),el("small","",value));cv.append(it);});
 const issues=$("issueList");issues.replaceChildren();const bad=d.steps.filter(x=>x.state!=="completed");
 if(!bad.length)issues.append(el("div","item","No tool failures recorded."));
 bad.forEach(step=>{const it=el("div","item failure");it.append(el("strong","",step.tool+": "+step.state),el("small","",short(step.stderr||"No diagnostic output captured.",230)));issues.append(it);});
}
function evidence(d){
 const list=$("toolList");list.replaceChildren();if(!d.steps.length)list.append(el("div","empty","No tool executions recorded."));
 d.steps.forEach((step,i)=>{
  const row=el("div","tool"),head=el("div","tool-head");
  head.append(el("strong","",String(i+1)+". "+step.tool+(step.clue?" · "+short(step.clue,60):"")));
  head.append(el("span","tool-state "+step.state,step.state+" · exit "+(step.exit_code??"—")+" · "+(step.duration_seconds??"?")+"s"));
  const details=el("details"),summary=el("summary","","Show captured stdout and errors");
  details.append(summary,el("p","muted","Standard output — "+(step.stdout_file||"")),el("pre","",step.stdout||"(no stdout)"),
   el("p","muted","Error output — "+(step.stderr_file||"")),el("pre","",step.stderr||"(no stderr)"));
  row.append(head,details);list.append(row);
 });
}
function graphNodes(){
 const area=$("graphNodeList");area.replaceChildren();if(!s.graph)return;
 s.graph.nodes.slice(0,100).forEach(n=>{const b=el("button","",short(n.label,50));b.addEventListener("click",()=>{s.graph.select(n.id);$("nodeDetails").scrollIntoView({block:"nearest",behavior:"smooth"});});area.append(b);});
}
function inspector(n){
 const target=$("nodeDetails");target.replaceChildren();
 if(!n){target.append(el("p","muted","Select a node to inspect it or create a relationship. Add person nodes with the + Person button."));return;}
 target.append(el("div","node-kind",n.kind+" · "+n.status),el("div","name",n.label));
 if(n.tool)target.append(el("p","muted","Tool: "+n.tool));
 if(n.evidence)target.append(el("p","muted","Evidence file: "+n.evidence));
 if(n.note)target.append(el("p","muted",n.note));
 if(n.url&&/^https?:\/\//i.test(n.url)){const a=el("a","","Open external source");a.href=n.url;a.target="_blank";a.rel="noopener noreferrer";target.append(a);}
 target.append(el("p","muted",s.from?"Linking from "+short(s.graph.map.get(s.from)?.label,35)+". Select another node to finish.":"Choose a connection type, click Connect, then select a second node."));
 const label=el("label","","Connection type");const sel=el("select");
 ["possible association","public association","known contact"].forEach(value=>{const o=el("option","",value);o.value=value;o.selected=s.relation===value;sel.append(o);});
 sel.addEventListener("change",()=>s.relation=sel.value);label.append(sel);target.append(label);
 const b=el("button","outline full",s.from===n.id?"Cancel connection":"Connect from this node");
 b.addEventListener("click",()=>{s.from=s.from===n.id?null:n.id;inspector(n);if(s.from)flash("Now select a second node.");});target.append(b);
}
async function saveLink(from,to){
 if(from===to){s.from=null;return;}
 try{const id=s.id;await api("/api/cases/"+encodeURIComponent(id)+"/links",{source:from,target:to,label:s.relation});
  await cases(id);tab("graph");flash("Connection saved as a user-entered association, not an identity verification.");
 }catch(e){flash(e.message);}
}
class Graph{
 constructor(canvas,graph){
  this.canvas=canvas;this.ctx=canvas.getContext("2d");this.nodes=(graph.nodes||[]).map(n=>({...n,x:0,y:0}));
  this.map=new Map(this.nodes.map(n=>[n.id,n]));this.edges=graph.edges||[];this.zoom=1;this.pan={x:0,y:0};this.selected=null;this.drag=null;
  const groups={subject:[],clue:[],lead:[],finding:[],person:[]};
  this.nodes.forEach(n=>(groups[n.kind]||groups.finding).push(n));
  function ring(group,radius,offset){
   group.forEach((n,i)=>{const ring=Math.floor(i/24);const segment=i%24;const count=Math.min(24,group.length-ring*24);
    const theta=(segment/Math.max(count,1))*2*Math.PI+offset+ring*.25;
    n.x=Math.cos(theta)*(radius+ring*95);n.y=Math.sin(theta)*(radius+ring*95);});
  }
  ring(groups.clue,115,0);ring(groups.lead,220,-.3);ring(groups.finding,345,.2);ring(groups.person,200,2.7);
  groups.subject.forEach((n,i)=>{n.x=i*40;n.y=0;});this.events();
 }
 resize(){const b=this.canvas.getBoundingClientRect();this.w=b.width||600;this.h=b.height||525;this.dpr=window.devicePixelRatio||1;this.canvas.width=Math.floor(this.w*this.dpr);this.canvas.height=Math.floor(this.h*this.dpr);this.draw();}
 fit(){if(!this.w)this.resize();const maxX=Math.max(170,...this.nodes.map(n=>Math.abs(n.x)+60));const maxY=Math.max(150,...this.nodes.map(n=>Math.abs(n.y)+45));this.zoom=Math.max(.16,Math.min(1,(this.w-80)/2/maxX,(this.h-120)/2/maxY));this.pan={x:0,y:0};this.draw();}
 world(e){const r=this.canvas.getBoundingClientRect();return{x:(e.clientX-r.left-this.w/2-this.pan.x)/this.zoom,y:(e.clientY-r.top-this.h/2-this.pan.y)/this.zoom};}
 hit(e){const p=this.world(e);let best=null,d=24/this.zoom;this.nodes.forEach(n=>{const dist=Math.hypot(p.x-n.x,p.y-n.y);if(dist<d){d=dist;best=n;}});return best;}
 select(id){const n=this.map.get(id);if(!n)return;if(s.from&&s.from!==id){const old=s.from;s.from=null;saveLink(old,id);return;}this.selected=id;this.draw();inspector(n);}
 events(){
  this.canvas.addEventListener("pointerdown",e=>{const n=this.hit(e);this.drag={node:n,sx:e.clientX,sy:e.clientY,x:n?n.x:this.pan.x,y:n?n.y:this.pan.y,moved:false};this.canvas.setPointerCapture(e.pointerId);});
  this.canvas.addEventListener("pointermove",e=>{if(!this.drag)return;const dx=e.clientX-this.drag.sx,dy=e.clientY-this.drag.sy;if(Math.abs(dx)+Math.abs(dy)>5)this.drag.moved=true;if(this.drag.node){this.drag.node.x=this.drag.x+dx/this.zoom;this.drag.node.y=this.drag.y+dy/this.zoom;}else{this.pan.x=this.drag.x+dx;this.pan.y=this.drag.y+dy;}this.draw();});
  this.canvas.addEventListener("pointerup",()=>{const d=this.drag;this.drag=null;if(d&&!d.moved&&d.node)this.select(d.node.id);});
  this.canvas.addEventListener("pointercancel",()=>this.drag=null);
  this.canvas.addEventListener("wheel",e=>{e.preventDefault();this.zoom=Math.max(.17,Math.min(3,this.zoom*(e.deltaY<0?1.1:.9)));this.draw();},{passive:false});
 }
 draw(){if(!this.ctx||!this.w)return;const c=this.ctx;c.setTransform(this.dpr,0,0,this.dpr,0,0);c.clearRect(0,0,this.w,this.h);
  c.save();c.translate(this.w/2+this.pan.x,this.h/2+this.pan.y);c.scale(this.zoom,this.zoom);
  this.edges.forEach(edge=>{const a=this.map.get(edge.source),b=this.map.get(edge.target);if(!a||!b)return;
   c.beginPath();c.moveTo(a.x,a.y);c.lineTo(b.x,b.y);c.strokeStyle=edge.status==="user_added"?"#5ad6cb99":"#52749685";
   c.lineWidth=edge.status==="user_added"?1.8:1.1;c.setLineDash(edge.status==="unverified"?[5,7]:[]);c.stroke();});
  c.setLineDash([]);this.nodes.forEach(n=>{const active=this.selected===n.id,color=palette[n.kind]||"#a8b8cd",r=n.kind==="subject"?15:n.kind==="person"?12:n.kind==="clue"?10:8;
   c.beginPath();c.arc(n.x,n.y,r+(active?6:0),0,Math.PI*2);c.fillStyle="#60a8f322";c.fill();
   c.beginPath();c.arc(n.x,n.y,r,0,Math.PI*2);c.fillStyle=color;c.shadowBlur=active?20:6;c.shadowColor=color;c.fill();c.shadowBlur=0;
   c.strokeStyle="#0e1624";c.lineWidth=2;c.stroke();c.font=(active||n.kind==="subject"?"bold ":"")+"11px system-ui,sans-serif";c.fillStyle=active?"#fff":"#a9bed4";c.textAlign="center";c.fillText(short(n.label,26),n.x,n.y+r+16);
  });c.restore();
 }
}
function openNew(){$("newForm").reset();$("planPreview").hidden=true;$("executionControls").hidden=true;$("formError").textContent="";$("newDialog").showModal();}
function formData(){const f=new FormData($("newForm"));const v=k=>txt(f.get(k)).trim();return{
 names:v("name")?[v("name")]:[],usernames:v("username")?[v("username")]:[],
 emails:v("email")?[v("email")]:[],domains:v("domain")?[v("domain")]:[],
 location:v("location")||null,depth:v("depth")||"medium"};}
async function pollJob(){
 if(!s.job)return;try{const r=await api("/api/jobs/"+s.job),j=r.job;
  if(j.status==="running"){const e=j.events&&j.events.length?j.events[j.events.length-1]:null;$("jobBar").hidden=false;$("jobLabel").textContent="Investigation running";
   $("jobDetail").textContent=!e?"Preparing research tools…":e.event==="heartbeat"?e.tool+" · "+Math.round(e.elapsed)+"s elapsed":e.event==="step_started"?"Starting "+e.tool:e.event==="step_finished"?e.tool+" · "+e.state:e.event==="lead_discovered"?"Unverified "+e.kind+" lead found":"Case initialized";
  }else{clearInterval(s.timer);s.timer=null;s.job=null;$("jobBar").hidden=true;if(j.case_id)await cases(j.case_id);flash(j.status==="finished"?"Investigation finished. Review findings and errors.":"Investigation failed: "+(j.error||"Unknown error"));}
 }catch(e){flash(e.message);}
}
function setup(){
 ["newCase","welcomeNew","newCaseTop"].forEach(id=>$(id).addEventListener("click",openNew));
 $("refreshCases").addEventListener("click",()=>cases().catch(e=>flash(e.message)));
 $("closeDialog").addEventListener("click",()=>$("newDialog").close());$("closePerson").addEventListener("click",()=>$("personDialog").close());
 document.querySelectorAll(".tab").forEach(b=>b.addEventListener("click",()=>tab(b.dataset.tab)));
 $("previewButton").addEventListener("click",async()=>{try{$("formError").textContent="";const p=await api("/api/preview",formData());$("planPreview").textContent=p.plan;$("planPreview").hidden=false;$("executionControls").hidden=false;}catch(e){$("formError").textContent=e.message;}});
 $("newForm").addEventListener("input",event=>{
  // Confirmation controls belong to the form, but editing them doesn't change the research plan.
  if(event.target.closest("#executionControls"))return;
  // Changing the clues or depth invalidates the preview and requires fresh consent.
  $("planPreview").hidden=true;
  $("executionControls").hidden=true;
  $("networkAck").checked=false;
  $("runConfirm").value="";
 });
 $("newForm").addEventListener("submit",event=>event.preventDefault());
 $("startButton").addEventListener("click",async()=>{if(!$("networkAck").checked||$("runConfirm").value!=="RUN"){$("formError").textContent="Acknowledge network exposure and type RUN.";return;}
  try{const r=await api("/api/jobs",Object.assign(formData(),{acknowledge_exposure:true,confirm:"RUN"}));s.job=r.job_id;$("newDialog").close();$("jobBar").hidden=false;await pollJob();s.timer=setInterval(pollJob,1600);}catch(e){$("formError").textContent=e.message;}
 });
 $("fitGraph").addEventListener("click",()=>s.graph?.fit());
 $("addPerson").addEventListener("click",()=>{$("personForm").reset();$("personError").textContent="";$("personDialog").showModal();});
 $("personForm").addEventListener("submit",async e=>{e.preventDefault();const f=new FormData($("personForm"));try{const id=s.id;await api("/api/cases/"+encodeURIComponent(id)+"/people",{name:txt(f.get("name")),note:txt(f.get("note"))});$("personDialog").close();await cases(id);tab("graph");flash("Person node added locally.");}catch(err){$("personError").textContent=err.message;}});
 $("jobDismiss").addEventListener("click",()=>$("jobBar").hidden=true);window.addEventListener("resize",()=>{if(!$("tab-graph").hidden)s.graph?.resize();});
}
(async()=>{try{const x=await api("/api/session");s.token=x.token;setup();await cases();}catch(e){$("caseList").replaceChildren(el("p","error","Local server error: "+e.message));}})();
