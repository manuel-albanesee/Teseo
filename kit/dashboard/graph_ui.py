"""Disegno del grafo: layout a forze, zoom e pan, colori per tipo, vicinato espandibile. Solo SVG e DOM, nessuna risorsa esterna."""
GRAPH_SCRIPT = r"""
 function createGraphView({element,onOpen}) {
   const NS='http://www.w3.org/2000/svg', W=900, H=460, MAX_NODES=500, MAX_TICKS=400, LABELS_UP_TO=60;
   let nodes=[], edges=[], positions=new Map(), view={x:0,y:0,k:1}, frame=0, temperature=0, ticks=0, marks=null, autofit=true;
   let svg=null, viewport=null, marker=null, linkEls=[], nodeEls=new Map(), status=null, radius=6;
   const host=()=>document.getElementById('map');
   const svgEl=(tag,attrs,parent)=>{const el=document.createElementNS(NS,tag);for(const [key,value] of Object.entries(attrs))el.setAttribute(key,value);if(parent)parent.append(el);return el;};
   const edgeKey=edge=>edge.source_id+'\u0000'+edge.target_id+'\u0000'+edge.type;
   // Colore stabile per tipo: tinta dall'hash del nome, luminosità fissa per il contrasto con il bordo bianco.
   const color=tipo=>{if(!tipo)return '#6b7a74';let hue=0;for(const ch of String(tipo))hue=(hue*31+ch.charCodeAt(0))%360;return 'hsl('+hue+' 50% 36%)';};
   function seed(list,around) {
     const centre=around&&positions.get(around)||{x:W/2,y:H/2};
     list.forEach((node,i)=>{if(!positions.has(node.id)){const radius=(around?40:14)*Math.sqrt(i+1),angle=i*2.399963;
       positions.set(node.id,{x:centre.x+radius*Math.cos(angle),y:centre.y+radius*Math.sin(angle),dx:0,dy:0});}});
   }
   // Fruchterman-Reingold: repulsione k²/d fra tutti, attrazione d²/k lungo gli archi, gravità leggera, raffreddamento.
   function step() {
     const n=nodes.length,k=Math.sqrt(W*H/Math.max(n,1))*0.9,list=nodes.map(node=>positions.get(node.id));
     for(const p of list){p.dx=0;p.dy=0;}
     for(let i=0;i<n;i++)for(let j=i+1;j<n;j++){
       const a=list[i],b=list[j];let dx=a.x-b.x,dy=a.y-b.y,d2=dx*dx+dy*dy;
       if(d2<0.01){dx=(i%2?1:-1)*0.1;dy=0.1;d2=0.02;}
       const f=k*k/d2;a.dx+=dx*f;a.dy+=dy*f;b.dx-=dx*f;b.dy-=dy*f;
     }
     for(const edge of edges){const a=positions.get(edge.source_id),b=positions.get(edge.target_id);if(!a||!b)continue;
       const dx=a.x-b.x,dy=a.y-b.y,f=(Math.sqrt(dx*dx+dy*dy)||0.1)/k;a.dx-=dx*f;a.dy-=dy*f;b.dx+=dx*f;b.dy+=dy*f;}
     for(const p of list){p.dx+=(W/2-p.x)*0.05;p.dy+=(H/2-p.y)*0.05;
       const d=Math.hypot(p.dx,p.dy)||0.1,move=Math.min(d,temperature);p.x+=p.dx/d*move;p.y+=p.dy/d*move;}
     temperature*=0.96;
   }
   function paint() {
     for(const node of nodes){const p=positions.get(node.id),el=nodeEls.get(node.id);if(el)el.setAttribute('transform','translate('+p.x.toFixed(1)+' '+p.y.toFixed(1)+')');}
     for(const {edge,line} of linkEls){const a=positions.get(edge.source_id),b=positions.get(edge.target_id),d=Math.hypot(b.x-a.x,b.y-a.y)||1;
       line.setAttribute('x1',a.x.toFixed(1));line.setAttribute('y1',a.y.toFixed(1));
       line.setAttribute('x2',(b.x-(b.x-a.x)*radius*1.3/d).toFixed(1));line.setAttribute('y2',(b.y-(b.y-a.y)*radius*1.3/d).toFixed(1));}
   }
   function loop() {
     cancelAnimationFrame(frame);
     const perFrame=nodes.length>250?1:3;
     const run=()=>{
       for(let i=0;i<perFrame&&temperature>0.5&&ticks<MAX_TICKS;i++){step();ticks++;}
       paint();if(autofit)fit();
       const moving=temperature>0.5&&ticks<MAX_TICKS;
       if(status)status.textContent=nodes.length+' nodi e '+edges.length+' archi · '+(moving?'layout in corso…':'layout assestato');
       if(moving)frame=requestAnimationFrame(run);
     };
     frame=requestAnimationFrame(run);
   }
   function applyView() {
     viewport.setAttribute('transform','translate('+view.x.toFixed(1)+' '+view.y.toFixed(1)+') scale('+view.k.toFixed(3)+')');
     // Dimensioni apparenti quasi costanti: nodi, etichette e frecce si adattano allo zoom (più piccole a distanza, più grandi da vicino).
     radius=Math.max(2,6/Math.pow(view.k,0.75));
     const labels=nodes.length<=LABELS_UP_TO||view.k>=1.8,size=(11/view.k).toFixed(2);
     for(const el of nodeEls.values()){el.querySelector('circle').setAttribute('r',radius.toFixed(2));
       const text=el.querySelector('text');text.setAttribute('visibility',labels?'visible':'hidden');text.setAttribute('font-size',size);text.setAttribute('y',(radius+12/view.k).toFixed(2));}
     if(marker){const arrow=(radius*1.6).toFixed(2);marker.setAttribute('markerWidth',arrow);marker.setAttribute('markerHeight',arrow);}
     paint();
   }
   function zoom(factor,cx=W/2,cy=H/2) {
     autofit=false;
     const k=Math.min(6,Math.max(0.1,view.k*factor)),ratio=k/view.k;
     view.x=cx-(cx-view.x)*ratio;view.y=cy-(cy-view.y)*ratio;view.k=k;applyView();
   }
   // Adatta zoom e posizione al riquadro dei nodi: un layout a forze può essere più grande dell'area visibile.
   function fit() {
     if(!nodes.length||!viewport)return;
     let x0=Infinity,x1=-Infinity,y0=Infinity,y1=-Infinity;
     for(const node of nodes){const p=positions.get(node.id);x0=Math.min(x0,p.x);x1=Math.max(x1,p.x);y0=Math.min(y0,p.y);y1=Math.max(y1,p.y);}
     const pad=44,k=Math.min(6,Math.max(0.1,Math.min((W-2*pad)/Math.max(x1-x0,1),(H-2*pad)/Math.max(y1-y0,1))));
     view={k,x:W/2-k*(x0+x1)/2,y:H/2-k*(y0+y1)/2};applyView();
   }
   function tools(parent) {
     const bar=element('div',undefined,parent);bar.className='map-tools';
     const add=(text,label,action)=>{const button=element('button',text,bar);button.type='button';button.setAttribute('aria-label',label);button.addEventListener('click',action);return button;};
     add('+','Ingrandisci il disegno',()=>zoom(1.25));add('−','Riduci il disegno',()=>zoom(1/1.25));
     add('Reimposta vista','Reimposta zoom e posizione',()=>{autofit=true;fit();});
     add('Ricalcola layout','Ricalcola il layout a forze',()=>{autofit=true;temperature=Math.sqrt(W*H)/6;ticks=0;loop();});
     status=element('span','',bar);status.className='hint';status.setAttribute('role','status');
   }
   function legend(parent) {
     const types=[...new Set(nodes.map(node=>node.tipo||''))].sort();
     const list=element('ul',undefined,parent);list.className='legend';
     for(const tipo of types){const item=element('li',undefined,list),mark=svgEl('svg',{width:'12',height:'12','aria-hidden':'true'},item);
       svgEl('circle',{cx:'6',cy:'6',r:'6',fill:color(tipo)},mark);element('span',' '+(tipo||'Tipo non dichiarato'),item);}
   }
   function build() {
     const container=host();container.replaceChildren();
     svg=viewport=marker=status=null;linkEls=[];nodeEls=new Map();  // un disegno vuoto non deve lasciare elementi di quello precedente
     if(!nodes.length)return;
     tools(container);
     svg=svgEl('svg',{viewBox:'0 0 '+W+' '+H,role:'group','aria-label':'Grafo diretto. Stessi nodi disponibili nella lista accanto.'},container);
     marker=svgEl('marker',{id:'arrow',viewBox:'0 0 10 10',refX:'9',refY:'5',markerWidth:'6',markerHeight:'6',markerUnits:'userSpaceOnUse',orient:'auto-start-reverse'},svgEl('defs',{},svg));
     svgEl('path',{d:'M 0 0 L 10 5 L 0 10 z',fill:'#73827a'},marker);
     svgEl('rect',{x:'0',y:'0',width:W,height:H,fill:'transparent','data-background':'1'},svg);
     viewport=svgEl('g',{},svg);
     linkEls=edges.map(edge=>{const line=svgEl('line',{stroke:'#73827a','stroke-width':'1','vector-effect':'non-scaling-stroke','marker-end':'url(#arrow)'},viewport);
       svgEl('title',{},line).textContent=edge.source_id+' → '+edge.type+' → '+edge.target_id;return {edge,line};});
     nodeEls=new Map();
     for(const node of nodes){
       const group=svgEl('g',{tabindex:'0',role:'button','aria-label':'Apri '+node.id,'data-node':node.id},viewport);
       svgEl('circle',{r:'6',fill:color(node.tipo),stroke:'#fff','stroke-width':'1.5','vector-effect':'non-scaling-stroke',class:'node-dot'},group);
       svgEl('text',{y:'21','text-anchor':'middle','font-size':'11',fill:'#242b2c'},group).textContent=node.id;
       svgEl('title',{},group).textContent=node.id+(node.tipo?' · '+node.tipo:'');
       group.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();onOpen(node.id);}});
       nodeEls.set(node.id,group);
     }
     pointers();applyView();paint();paintMarks();legend(container);
     element('p','Rotella o pulsanti per lo zoom, trascina lo sfondo per spostare, Invio su un nodo per aprirlo. Disegno limitato a '+MAX_NODES+' nodi; etichette complete e tipi nelle liste.',container).className='hint';
   }
   function pointers() {
     let drag=null;
     svg.addEventListener('wheel',event=>{event.preventDefault();const box=svg.getBoundingClientRect();
       zoom(event.deltaY<0?1.15:1/1.15,(event.clientX-box.left)*W/box.width,(event.clientY-box.top)*H/box.height);},{passive:false});
     svg.addEventListener('pointerdown',event=>{drag={x:event.clientX,y:event.clientY,vx:view.x,vy:view.y,moved:false,node:event.target.closest('[data-node]')?.dataset.node};svg.setPointerCapture(event.pointerId);});
     svg.addEventListener('pointermove',event=>{if(!drag)return;const box=svg.getBoundingClientRect(),dx=event.clientX-drag.x,dy=event.clientY-drag.y;
       if(Math.hypot(dx,dy)>4)drag.moved=true;if(drag.moved){autofit=false;view.x=drag.vx+dx*W/box.width;view.y=drag.vy+dy*H/box.height;applyView();}});
     const finish=event=>{if(drag&&!drag.moved&&drag.node&&event.type==='pointerup')onOpen(drag.node);drag=null;};
     svg.addEventListener('pointerup',finish);svg.addEventListener('pointercancel',finish);
   }
   function paintMarks() {
     for(const [id,group] of nodeEls){const dot=group.querySelector('circle'),on=!marks||marks.nodes.has(id);
       dot.setAttribute('stroke',marks&&on?'#b46100':'#fff');dot.setAttribute('stroke-width',marks&&on?'3.5':'1.5');group.setAttribute('opacity',on?'1':'0.3');}
     for(const {edge,line} of linkEls){const on=!marks||marks.edges.has(edgeKey(edge));
       line.setAttribute('stroke',marks&&on?'#b46100':'#73827a');line.setAttribute('stroke-width',marks&&on?'2.5':'1');line.setAttribute('opacity',on?'1':'0.2');}
   }
   // Evidenzia nodi e archi (per esempio una catena causale); highlight(null) toglie l'evidenza.
   function highlight(nodeIds,edgeList) {
     marks=nodeIds?{nodes:new Set(nodeIds),edges:new Set((edgeList||[]).map(edgeKey))}:null;
     if(svg)paintMarks();
   }
   function render(list,edgeList,max=200) {
     const limit=Math.max(12,Math.min(MAX_NODES,Number(max)||200));
     nodes=list.slice(0,limit);const ids=new Set(nodes.map(node=>node.id));
     edges=edgeList.filter(edge=>ids.has(edge.source_id)&&ids.has(edge.target_id)).slice(0,limit*4);
     for(const id of [...positions.keys()])if(!ids.has(id))positions.delete(id);
     seed(nodes);view={x:0,y:0,k:1};marks=null;autofit=true;build();
     temperature=Math.sqrt(W*H)/6;ticks=0;loop();
   }
   // Aggiunge nodi e archi al disegno senza ricominciare il layout da zero. Restituisce quanti nodi nuovi sono entrati.
   function expand(newNodes,newEdges,around) {
     const known=new Set(nodes.map(node=>node.id)),fresh=newNodes.filter(node=>!known.has(node.id)).slice(0,Math.max(0,MAX_NODES-nodes.length));
     const keys=new Set(edges.map(edgeKey));
     nodes=nodes.concat(fresh);const ids=new Set(nodes.map(node=>node.id));
     edges=edges.concat(newEdges.filter(edge=>ids.has(edge.source_id)&&ids.has(edge.target_id)&&!keys.has(edgeKey(edge))));
     seed(fresh,around);autofit=true;build();temperature=Math.sqrt(W*H)/12;ticks=0;loop();
     return fresh.length;
   }
   return {render,expand,highlight,has:id=>nodes.some(node=>node.id===id),size:()=>nodes.length,max:MAX_NODES};
 }
"""
