"use strict";
/* Reconductor Networks: local, Markdown-backed relationship workspaces. */
const $ = id => document.getElementById(id);
const state = {token:"",workspaceId:null,workspaces:[],view:null,graph:null,selected:null};
const text = value => value == null ? "" : String(value);
const cut = (v,n=80) => text(v).length>n ? text(v).slice(0,n-1)+"…" : text(v);
function node(tag,cls,value) {
  const e=document.createElement(tag);if(cls)e.className=cls;
  if(value!==undefined)e.textContent=text(value);
  return e;
}
function toast(message){
  const box=$("networkToast");box.textContent=message;box.hidden=false;
  clearTimeout(toast.timeout);toast.timeout=setTimeout(()=>box.hidden=true,5000);
}
async function api(url,body){
  const headers={Accept:"application/json"};
  if(body!==undefined){headers["Content-Type"]="application/json";headers["X-Reconductor-Token"]=state.token;}
  const response=await fetch(url,{method:body===undefined?"GET":"POST",headers,
    credentials:"same-origin",cache:"no-store",body:body===undefined?undefined:JSON.stringify(body)});
  const result=await response.json();
  if(!response.ok)throw Error(result.error||"Request failed");
  return result;
}
function dialogOpen(id){const dlg=$(id);dlg.querySelector("form").reset();dlg.querySelector(".error").textContent="";dlg.showModal();}
function formValues(id){
  const entries=new FormData($(id));
  return Object.fromEntries([...entries.entries()].map(([k,v])=>[k,text(v).trim()]));
}
function errorIn(id,message){$(id).querySelector(".error").textContent=message;}
async function workspaces(preferred){
  const response=await api("/api/network-workspaces");
  state.workspaces=response.workspaces||[];
  const list=$("workspaceList");list.replaceChildren();
  if(!state.workspaces.length)list.append(node("p","muted","No networks yet."));
  for(const item of state.workspaces){
    const b=node("button","workspace-choice"+(item.id===state.workspaceId?" selected":""));
    b.append(node("strong","",item.name),node("small","",
      item.people_count+" people · "+item.groups_count+" groups"));
    b.addEventListener("click",()=>selectWorkspace(item.id));list.append(b);
  }
  const next=preferred||state.workspaceId||state.workspaces[0]?.id;
  if(next && state.workspaces.some(w=>w.id===next))await selectWorkspace(next);
  else {state.workspaceId=null;state.view=null;state.graph=null;$("networkWelcome").hidden=false;$("networkView").hidden=true;}
}
async function selectWorkspace(id){
  try{
    const view=await api("/api/network-workspaces/"+encodeURIComponent(id));
    state.workspaceId=id;state.view=view;state.selected=null;
    $("networkWelcome").hidden=true;$("networkView").hidden=false;
    $("breadcrumb").textContent=cut(view.workspace.name,42);
    $("networkName").textContent=view.workspace.name;
    $("networkDescription").textContent=view.workspace.description||"Add people and groups, then connect them to reveal clusters.";
    $("peopleCount").textContent=view.nodes.filter(n=>n.kind==="person").length;
    $("groupsCount").textContent=view.nodes.filter(n=>n.kind==="group").length;
    $("edgesCount").textContent=view.edges.length;
    $("clustersCount").textContent=view.clusters.filter(c=>c.count>=2).length;
    document.querySelectorAll(".workspace-choice").forEach((b,i)=>
      b.classList.toggle("selected",state.workspaces[i]?.id===id));
    clusters(view);
    const old=$("networkCanvas"),fresh=old.cloneNode(false);old.replaceWith(fresh);
    state.graph=new NetworkGraph(fresh,view);
    requestAnimationFrame(()=>{state.graph.resize();state.graph.fit();});
    nodeList(view);
    inspector(null);
  }catch(e){toast(e.message);}
}
function clusters(view){
  const list=$("clusterList");list.replaceChildren();
  const shared=view.clusters.filter(c=>c.count>=2);
  if(!shared.length){
    list.append(node("p","muted","No shared group clusters yet. Connect at least two people to the same group, such as a workplace or church."));
    return;
  }
  for(const cluster of shared){
    const box=node("div","cluster-item");
    box.append(node("strong","",cluster.group_name),
      node("small","",cluster.count+" people connected to this "+cluster.kind));
    const members=cluster.members.map(id=>view.nodes.find(n=>n.id===id)?.label||"Unknown");
    box.append(node("small","",members.join(" · ")));
    list.append(box);
  }
}
function nodeList(view){
  const target=$("networkNodes");target.replaceChildren();
  if(!view.nodes.length)target.append(node("p","muted","Add your first person or group to begin."));
  for(const entry of view.nodes){
    const b=node("button","",entry.label+" · "+(entry.kind==="person"?"person":entry.group_kind));
    b.addEventListener("click",()=>state.graph.select(entry.id));target.append(b);
  }
}
function elementButton(label,handler,cls="outline full"){
  const button=node("button",cls,label);button.type="button";
  button.addEventListener("click",handler);return button;
}
function inspector(entry){
  const container=$("networkNodeDetails");container.replaceChildren();
  if(!entry){
    container.append(node("p","muted","Click any person or group on the map. You can edit a shared profile, see relationships, or open their other networks on request."));
    return;
  }
  container.append(node("div","node-type",entry.kind==="person"?"Shared person profile":entry.group_kind+" (workspace only)"),
    node("div","node-name",entry.label));
  if(entry.details)container.append(node("p","node-detail",entry.details));
  const selectedEdges=state.view.edges.filter(edge=>edge.source===entry.id||edge.target===entry.id);
  const relations=node("div","relation-list");relations.append(node("h3","","Connections in this workspace"));
  if(!selectedEdges.length)relations.append(node("p","", "No relationships added yet."));
  for(const edge of selectedEdges){
    const counterpart=edge.source===entry.id?edge.target:edge.source;
    const display=state.view.nodes.find(n=>n.id===counterpart)?.label||"Unknown node";
    const direction=edge.source===entry.id?" → ":" ← ";
    relations.append(node("p","",edge.type+direction+display+(edge.note?" · "+edge.note:"")));
  }
  container.append(relations);
  container.append(elementButton("＋ Connect this node",()=>{
    openLinkDialog(entry.id);
  }));
  if(entry.kind==="person"){
    container.append(elementButton("Edit shared profile",()=>openEditDialog(entry)));
    const membership=elementButton("Show other workspaces",async()=>{
      membership.disabled=true;
      try{
        const result=await api("/api/network-people/"+entry.id+"/memberships");
        const section=node("div","other-network-list");
        const others=result.memberships.filter(w=>w.id!==state.workspaceId);
        section.append(node("p","muted",others.length?"Other workspaces using this shared profile:":"This person is not in any other workspace."));
        for(const ws of others) section.append(elementButton(
          ws.name+" · Open workspace",()=>selectWorkspace(ws.id),""
        ));
        container.append(section);
        membership.textContent="Other workspaces shown";
      }catch(e){membership.disabled=false;toast(e.message);}
    });
    container.append(membership);
  }
}
function groupHash(input){
  let value=0;for(const char of input)value=(value*31+char.charCodeAt(0))>>>0;return value;
}
/* Deterministic layout: people orbit groups from explicitly entered links.
   This groups colleagues visually without creating invented person-person edges. */
function layoutGraph(view){
  const nodes=view.nodes||[], groups=nodes.filter(n=>n.kind==="group");
  const people=nodes.filter(n=>n.kind==="person");
  const result={};
  const families=groups.filter(g=>g.group_kind==="family");
  const centerpiece=families[0]||groups[0]||null;
  const otherGroups=groups.filter(g=>g!==centerpiece);
  if(centerpiece)result[centerpiece.id]={x:0,y:0};
  otherGroups.forEach((g,i)=>{
    const theta=2*Math.PI*i/Math.max(otherGroups.length,1)-Math.PI/2;
    result[g.id]={x:Math.cos(theta)*360,y:Math.sin(theta)*305};
  });
  const neighbors=new Map();
  for(const group of groups)neighbors.set(group.id,[]);
  const byPerson=new Map();
  for(const edge of view.edges||[]){
    const group=groups.find(g=>g.id===edge.source||g.id===edge.target);
    const person=people.find(p=>p.id===edge.source||p.id===edge.target);
    if(group&&person){
      neighbors.get(group.id).push(person.id);
      if(!byPerson.has(person.id))byPerson.set(person.id,[]);
      if(!byPerson.get(person.id).includes(group.id))byPerson.get(person.id).push(group.id);
    }
  }
  let unconnected=0;
  for(const person of people){
    const affiliations=byPerson.get(person.id)||[];
    if(!affiliations.length){
      const theta=unconnected++*2.3999632;
      const r=500+Math.sqrt(unconnected)*24;
      result[person.id]={x:Math.cos(theta)*r,y:Math.sin(theta)*r};
    }else if(affiliations.length===1){
      const groupId=affiliations[0],center=result[groupId];
      const linked=[...new Set(neighbors.get(groupId))].sort();
      const index=linked.indexOf(person.id);
      const angle=2*Math.PI*index/Math.max(linked.length,1)-Math.PI/3;
      result[person.id]={x:center.x+Math.cos(angle)*134,y:center.y+Math.sin(angle)*112};
    }else{
      const centers=affiliations.map(id=>result[id]);
      const mean={x:centers.reduce((a,b)=>a+b.x,0)/centers.length,
                  y:centers.reduce((a,b)=>a+b.y,0)/centers.length};
      const angle=(groupHash(person.id)%360)*Math.PI/180;
      result[person.id]={x:mean.x+Math.cos(angle)*50,y:mean.y+Math.sin(angle)*50};
    }
  }
  // Manually moved nodes override the automatic placement in this workspace only.
  for(const [id,pos] of Object.entries(view.positions||{})){
    if(result[id] && Number.isFinite(pos.x) && Number.isFinite(pos.y)) result[id]={x:pos.x,y:pos.y};
  }
  return result;
}
class NetworkGraph {
  constructor(canvas,view){
    this.canvas=canvas;this.ctx=canvas.getContext("2d");this.view=view;
    const positions=layoutGraph(view);
    this.nodes=view.nodes.map(n=>({...n,...(positions[n.id]||{x:0,y:0})}));
    this.byId=new Map(this.nodes.map(n=>[n.id,n]));
    this.edges=view.edges;this.scale=1;this.pan={x:0,y:0};this.selected=null;this.drag=null;
    this.events();
  }
  resize(){
    const box=this.canvas.getBoundingClientRect();this.width=box.width||750;this.height=box.height||600;
    this.dpr=window.devicePixelRatio||1;
    this.canvas.width=Math.ceil(this.width*this.dpr);this.canvas.height=Math.ceil(this.height*this.dpr);
    this.draw();
  }
  fit(){
    if(!this.width)this.resize();
    if(!this.nodes.length){this.scale=1;this.pan={x:0,y:0};this.draw();return;}
    const minX=Math.min(...this.nodes.map(n=>n.x-90)),maxX=Math.max(...this.nodes.map(n=>n.x+90));
    const minY=Math.min(...this.nodes.map(n=>n.y-85)),maxY=Math.max(...this.nodes.map(n=>n.y+85));
    this.scale=Math.max(.2,Math.min(1.4,(this.width-80)/(maxX-minX),(this.height-120)/(maxY-minY)));
    this.pan={x:-(minX+maxX)/2*this.scale,y:-(minY+maxY)/2*this.scale};this.draw();
  }
  coords(e){
    const box=this.canvas.getBoundingClientRect();
    return {x:(e.clientX-box.left-this.width/2-this.pan.x)/this.scale,
            y:(e.clientY-box.top-this.height/2-this.pan.y)/this.scale};
  }
  hit(e){
    const point=this.coords(e);let best=null,range=65/this.scale;
    for(const entry of this.nodes){
      const dist=Math.hypot(entry.x-point.x,entry.y-point.y);
      if(dist<range){range=dist;best=entry;}
    }return best;
  }
  select(id){
    const selected=this.byId.get(id);if(!selected)return;
    this.selected=id;this.draw();inspector(selected);
  }
  events(){
    this.canvas.addEventListener("pointerdown",e=>{
      const selected=this.hit(e);this.drag={node:selected,fromX:e.clientX,fromY:e.clientY,
        x:selected?selected.x:this.pan.x,y:selected?selected.y:this.pan.y,moved:false};
      this.canvas.setPointerCapture(e.pointerId);
    });
    this.canvas.addEventListener("pointermove",e=>{
      if(!this.drag)return;
      const dx=e.clientX-this.drag.fromX,dy=e.clientY-this.drag.fromY;
      if(Math.abs(dx)+Math.abs(dy)>6)this.drag.moved=true;
      if(this.drag.node){
        this.drag.node.x=this.drag.x+dx/this.scale;this.drag.node.y=this.drag.y+dy/this.scale;
      }else{this.pan={x:this.drag.x+dx,y:this.drag.y+dy};}
      this.draw();
    });
    this.canvas.addEventListener("pointerup",async()=>{
      const drag=this.drag;this.drag=null;if(!drag)return;
      if(drag.node&&!drag.moved)this.select(drag.node.id);
      if(drag.node&&drag.moved){
        try{
          await api("/api/network-workspaces/"+state.workspaceId+"/positions",
            {node_id:drag.node.id,x:drag.node.x,y:drag.node.y});
        }catch(e){toast("Could not save position: "+e.message);}
      }
    });
    this.canvas.addEventListener("pointercancel",()=>this.drag=null);
    this.canvas.addEventListener("wheel",e=>{
      e.preventDefault();this.scale=Math.max(.16,Math.min(3,this.scale*(e.deltaY<0?1.13:.88)));this.draw();
    },{passive:false});
  }
  draw(){
    if(!this.ctx||!this.width)return;
    const ctx=this.ctx;ctx.setTransform(this.dpr,0,0,this.dpr,0,0);
    ctx.clearRect(0,0,this.width,this.height);
    ctx.save();ctx.translate(this.width/2+this.pan.x,this.height/2+this.pan.y);ctx.scale(this.scale,this.scale);
    for(const edge of this.edges){
      const a=this.byId.get(edge.source),b=this.byId.get(edge.target);
      if(!a||!b)continue;
      ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.strokeStyle="#728caeb5";
      ctx.lineWidth=1.7;ctx.stroke();
      if(this.scale>.5){
        const mx=(a.x+b.x)/2,my=(a.y+b.y)/2;
        ctx.font="10px system-ui";ctx.textAlign="center";
        const label=cut(edge.type,18),w=ctx.measureText(label).width+13;
        ctx.fillStyle="#102238";ctx.fillRect(mx-w/2,my-8,w,16);
        ctx.fillStyle="#a9c4df";ctx.fillText(label,mx,my+4);
      }
    }
    for(const entry of this.nodes){
      const chosen=this.selected===entry.id;
      if(entry.kind==="group"){
        const w=154,h=45;
        ctx.fillStyle=chosen?"#246658":"#184b46";
        ctx.strokeStyle=chosen?"#d4fff3":"#63c7b4";ctx.lineWidth=chosen?2.7:1.6;
        ctx.beginPath();ctx.roundRect(entry.x-w/2,entry.y-h/2,w,h,12);
        ctx.fill();ctx.stroke();
        ctx.textAlign="center";ctx.fillStyle="#eafff9";ctx.font="bold 13px system-ui";
        ctx.fillText(cut(entry.label,19),entry.x,entry.y-1);
        ctx.fillStyle="#9bd9c9";ctx.font="10px system-ui";ctx.fillText(entry.group_kind,entry.x,entry.y+14);
      }else{
        ctx.beginPath();ctx.arc(entry.x,entry.y,24,0,Math.PI*2);
        ctx.fillStyle=chosen?"#4a91db":"#244d7a";ctx.fill();
        ctx.strokeStyle=chosen?"#d8ecff":"#83beff";ctx.lineWidth=chosen?3:1.8;ctx.stroke();
        ctx.fillStyle="#ecf6ff";ctx.textAlign="center";ctx.font="bold 14px system-ui";
        ctx.fillText(text(entry.label).split(/\s+/).map(w=>w[0]).slice(0,2).join("").toUpperCase(),entry.x,entry.y+5);
        ctx.fillStyle=chosen?"#fff":"#c3d8ef";ctx.font="12px system-ui";
        ctx.fillText(cut(entry.label,23),entry.x,entry.y+42);
      }
    }
    ctx.restore();
  }
}
async function openReuse(){
  try{
    const all=(await api("/api/network-people")).people||[];
    const present=new Set(state.view?.workspace.people||[]);
    const unused=all.filter(p=>!present.has(p.id));
    if(!unused.length){toast("No unused shared profiles yet. Add a new person first.");return;}
    const select=$("existingSelect");select.replaceChildren();
    for(const person of unused){
      const option=node("option","",person.name);option.value=person.id;select.append(option);
    }
    dialogOpen("existingDialog");
  }catch(e){toast(e.message);}
}
function openLinkDialog(fromId){
  if(!state.view||state.view.nodes.length<2){toast("Add at least two people or groups first.");return;}
  dialogOpen("linkDialog");
  for(const id of ["linkSource","linkTarget"]){
    const select=$(id);select.replaceChildren();
    for(const person of state.view.nodes){
      const option=node("option","",person.label+(person.kind==="group"?" · group":" · person"));
      option.value=person.id;select.append(option);
    }
  }
  if(fromId)$("linkSource").value=fromId;
  const target=state.view.nodes.find(n=>n.id!==$("linkSource").value);
  if(target)$("linkTarget").value=target.id;
}
function openEditDialog(person){
  dialogOpen("editDialog");
  const form=$("editForm");
  form.elements.namedItem("name").value=person.label;
  form.elements.namedItem("details").value=person.details||"";
  form.dataset.personId=person.id;
}
function connectForms(){
  for(const dialog of document.querySelectorAll("dialog")){
    dialog.querySelector(".close-modal").addEventListener("click",()=>dialog.close());
  }
  const handlers=[
    ["workspaceForm",async vals=>{
      const result=await api("/api/network-workspaces",vals);
      $("workspaceDialog").close();await workspaces(result.workspace.id);
    }],
    ["personForm",async vals=>{
      await api("/api/network-workspaces/"+state.workspaceId+"/people",vals);
      $("personDialog").close();await workspaces(state.workspaceId);
    }],
    ["existingForm",async vals=>{
      await api("/api/network-workspaces/"+state.workspaceId+"/members",vals);
      $("existingDialog").close();await workspaces(state.workspaceId);
    }],
    ["groupForm",async vals=>{
      await api("/api/network-workspaces/"+state.workspaceId+"/groups",vals);
      $("groupDialog").close();await workspaces(state.workspaceId);
    }],
    ["linkForm",async vals=>{
      await api("/api/network-workspaces/"+state.workspaceId+"/links",vals);
      $("linkDialog").close();await workspaces(state.workspaceId);
    }],
    ["editForm",async vals=>{
      await api("/api/network-people/"+$("editForm").dataset.personId,vals);
      $("editDialog").close();await workspaces(state.workspaceId);
      toast("Shared person profile updated across all workspaces.");
    }],
  ];
  for(const [id,action] of handlers){
    $(id).addEventListener("submit",async e=>{
      e.preventDefault();const submit=$(id).querySelector('button[type="submit"]');
      submit.disabled=true;$(id).querySelector(".error").textContent="";
      try{await action(formValues(id));}catch(error){errorIn(id,error.message);}
      finally{submit.disabled=false;}
    });
  }
}
function bind(){
  for(const id of ["newWorkspace","welcomeCreate"])$(id).addEventListener("click",()=>dialogOpen("workspaceDialog"));
  $("refreshWorkspaces").addEventListener("click",()=>workspaces().catch(e=>toast(e.message)));
  $("addPerson").addEventListener("click",()=>dialogOpen("personDialog"));
  $("reusePerson").addEventListener("click",openReuse);
  $("addGroup").addEventListener("click",()=>dialogOpen("groupDialog"));
  $("addLink").addEventListener("click",()=>openLinkDialog());
  $("fitNetwork").addEventListener("click",()=>state.graph?.fit());
  window.addEventListener("resize",()=>{if(state.graph){state.graph.resize();state.graph.fit();}});
  connectForms();
}
(async()=>{
  try{
    const session=await api("/api/session");state.token=session.token;bind();await workspaces();
  }catch(error){
    $("workspaceList").replaceChildren(node("p","error","Unable to open local network storage: "+error.message));
  }
})();
