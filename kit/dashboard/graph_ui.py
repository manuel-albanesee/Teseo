"""Disegno del grafo: layout a forze, zoom e pan, colori per tipo, vicinato espandibile. Solo SVG e DOM, nessuna risorsa esterna."""
GRAPH_SCRIPT = r"""
 function createGraphView({element,onOpen}) {
   const NS='http://www.w3.org/2000/svg', W=900, H=460, MAX_NODES=2000, MAX_TICKS=400, LABELS_UP_TO=60, TREE_FROM=120, THETA2=0.81, FRAME_MS=30, PAINT_EVERY=120, CHUNK_MS=12, BUILD_SYNC=600, ARROWS_UP_TO=1500;
   let nodes=[], edges=[], positions=new Map(), view={x:0,y:0,k:1}, frame=0, lastPaint=0, building=0, temperature=0, cooling=0.96, ticks=0, marks=null, autofit=true;
   let svg=null, viewport=null, marker=null, linkEls=[], nodeEls=new Map(), status=null, radius=6;
   const host=()=>document.getElementById('map');
   const r1=value=>Math.round(value*10)/10;  // niente toFixed: a migliaia di attributi per fotogramma conta
   let paintedRadius=0, labelsShown=null, light=false;  // light: grafo grande, meno elementi accessori
   const svgEl=(tag,attrs,parent)=>{const el=document.createElementNS(NS,tag);for(const [key,value] of Object.entries(attrs))el.setAttribute(key,value);if(parent)parent.append(el);return el;};
   const edgeKey=edge=>edge.source_id+'\u0000'+edge.target_id+'\u0000'+edge.type;
   // Colore stabile per tipo: tinta dall'hash del nome, luminosità fissa per il contrasto con il bordo bianco.
   const color=tipo=>{if(!tipo)return '#6b7a74';let hue=0;for(const ch of String(tipo))hue=(hue*31+ch.charCodeAt(0))%360;return 'hsl('+hue+' 50% 36%)';};
   // Temperatura iniziale e raffreddamento: i grafi grandi partono più freddi e si raffreddano più lentamente, così i nodi lontani rientrano.
   function heat(divisor=1) {
     const big=nodes.length>300;temperature=Math.sqrt(W*H)/(big?12:6)/divisor;cooling=nodes.length>1000?0.97:big?0.985:0.96;ticks=0;
   }
   function seed(list,around) {
     const centre=around&&positions.get(around)||{x:W/2,y:H/2};
     // Spirale aurea dentro il riquadro (o attorno al nodo di partenza): partire fuori dall'area darebbe forze minuscole e un layout mai assestato.
     const frame=0.45*Math.min(W,H),total=Math.max(list.length,1);
     list.forEach((node,i)=>{if(!positions.has(node.id)){const radius=around?40*Math.sqrt(i+1):frame*Math.sqrt((i+1)/total),angle=i*2.399963;
       positions.set(node.id,{x:centre.x+radius*Math.cos(angle),y:centre.y+radius*Math.sin(angle),dx:0,dy:0});}});
   }
   // Quadtree di Barnes-Hut: i gruppi lontani si trattano come un solo nodo (massa e baricentro), così la repulsione costa
   // O(n log n) invece di O(n²) e il layout resta fluido fino a MAX_NODES.
   function place(node,p,depth) {
     const half=node.s/2,i=(p.x>=node.x+half?1:0)+(p.y>=node.y+half?2:0);
     if(!node.kids[i])node.kids[i]={x:node.x+(i&1?half:0),y:node.y+(i&2?half:0),s:half,mass:0,cx:0,cy:0,kids:null,p:null};
     insert(node.kids[i],p,depth+1);
   }
   function insert(node,p,depth) {
     if(node.mass===0){node.p=p;node.mass=1;node.cx=p.x;node.cy=p.y;return;}
     if(!node.kids){
       if(depth>=32){node.cx=(node.cx*node.mass+p.x)/(node.mass+1);node.cy=(node.cy*node.mass+p.y)/(node.mass+1);node.mass++;return;}  // punti quasi coincidenti
       const old=node.p;node.p=null;node.kids=[null,null,null,null];place(node,old,depth);
     }
     node.cx=(node.cx*node.mass+p.x)/(node.mass+1);node.cy=(node.cy*node.mass+p.y)/(node.mass+1);node.mass++;
     place(node,p,depth);
   }
   function quadtree(list) {
     let x0=Infinity,y0=Infinity,x1=-Infinity,y1=-Infinity;
     for(const p of list){if(p.x<x0)x0=p.x;if(p.y<y0)y0=p.y;if(p.x>x1)x1=p.x;if(p.y>y1)y1=p.y;}
     const root={x:x0,y:y0,s:Math.max(x1-x0,y1-y0)+1e-3,mass:0,cx:0,cy:0,kids:null,p:null};
     for(const p of list)insert(root,p,0);
     return root;
   }
   function push(node,p,k2) {
     if(node.mass===0||(node.p===p&&!node.kids))return;
     let dx=p.x-node.cx,dy=p.y-node.cy,d2=dx*dx+dy*dy;
     if(d2<0.01){dx=0.1;dy=0.1;d2=0.02;}
     if(!node.kids||node.s*node.s<THETA2*d2){const f=node.mass*k2/d2;p.dx+=dx*f;p.dy+=dy*f;return;}
     for(const child of node.kids)if(child)push(child,p,k2);
   }
   // Fruchterman-Reingold: repulsione k²/d fra tutti, attrazione d²/k lungo gli archi, gravità leggera, raffreddamento.
   function step() {
     const n=nodes.length,k=Math.sqrt(W*H/Math.max(n,1))*0.9,list=nodes.map(node=>positions.get(node.id));
     for(const p of list){p.dx=0;p.dy=0;}
     if(n>=TREE_FROM){const tree=quadtree(list);for(const p of list)push(tree,p,k*k);}
     else for(let i=0;i<n;i++)for(let j=i+1;j<n;j++){
       const a=list[i],b=list[j];let dx=a.x-b.x,dy=a.y-b.y,d2=dx*dx+dy*dy;
       if(d2<0.01){dx=(i%2?1:-1)*0.1;dy=0.1;d2=0.02;}
       const f=k*k/d2;a.dx+=dx*f;a.dy+=dy*f;b.dx-=dx*f;b.dy-=dy*f;
     }
     for(const edge of edges){const a=positions.get(edge.source_id),b=positions.get(edge.target_id);if(!a||!b)continue;
       const dx=a.x-b.x,dy=a.y-b.y,f=(Math.sqrt(dx*dx+dy*dy)||0.1)/k;a.dx-=dx*f;a.dy-=dy*f;b.dx+=dx*f;b.dy+=dy*f;}
     const gravity=0.05*Math.max(1,Math.sqrt(n/150));  // più nodi, più repulsione totale: la gravità cresce con loro
     for(const p of list){p.dx+=(W/2-p.x)*gravity;p.dy+=(H/2-p.y)*gravity;
       const d=Math.hypot(p.dx,p.dy)||0.1,move=Math.min(d,temperature);
       p.x=Math.min(2*W,Math.max(-W,p.x+p.dx/d*move));p.y=Math.min(2*H,Math.max(-H,p.y+p.dy/d*move));}  // argine contro le fughe, non un muro
     temperature*=cooling;
   }
   function paint() {
     for(const node of nodes){const p=positions.get(node.id),el=nodeEls.get(node.id);if(el)el.setAttribute('transform','translate('+r1(p.x)+' '+r1(p.y)+')');}
     for(const {edge,line} of linkEls){const a=positions.get(edge.source_id),b=positions.get(edge.target_id),d=Math.hypot(b.x-a.x,b.y-a.y)||1;
       line.setAttribute('x1',r1(a.x));line.setAttribute('y1',r1(a.y));
       line.setAttribute('x2',r1(b.x-(b.x-a.x)*radius*1.3/d));line.setAttribute('y2',r1(b.y-(b.y-a.y)*radius*1.3/d));}
   }
   function loop() {
     cancelAnimationFrame(frame);
     // Più passi per fotogramma finché c'è tempo (FRAME_MS), uno solo almeno: il browser resta reattivo anche a 2000 nodi.
     const run=()=>{
       const start=performance.now();let done=0;
       while(temperature>0.5&&ticks<MAX_TICKS&&(done===0||performance.now()-start<FRAME_MS)){step();ticks++;done++;}
       const moving=temperature>0.5&&ticks<MAX_TICKS;
       // Il calcolo è economico, il disegno di migliaia di elementi no: i grafi grandi si ridisegnano a intervalli, sempre all'ultimo passo.
       if(!moving||nodes.length<=TREE_FROM||start-lastPaint>=PAINT_EVERY){if(autofit)fit(true);paint();lastPaint=performance.now();}
       if(status)status.textContent=nodes.length+' nodi e '+edges.length+' archi · '+(moving?'layout in corso…':'layout assestato');
       if(moving)frame=requestAnimationFrame(run);
     };
     frame=requestAnimationFrame(run);
   }
   function applyView(skipPaint) {
     viewport.setAttribute('transform','translate('+r1(view.x)+' '+r1(view.y)+') scale('+view.k.toFixed(3)+')');
     // Dimensioni apparenti quasi costanti: nodi, etichette e frecce si adattano allo zoom (più piccole a distanza, più grandi da vicino).
     radius=Math.max(2,6/Math.pow(view.k,0.75));
     const labels=nodes.length<=LABELS_UP_TO||view.k>=1.8;
     if(Math.abs(radius-paintedRadius)>paintedRadius*0.04||labelsShown!==labels){
       paintedRadius=radius;labelsShown=labels;const size=(11/view.k).toFixed(2);
       for(const el of nodeEls.values()){el.querySelector('circle').setAttribute('r',r1(radius));
         const text=el.querySelector('text');if(text){text.setAttribute('visibility',labels?'visible':'hidden');text.setAttribute('font-size',size);text.setAttribute('y',r1(radius+12/view.k));}}
       if(marker){const arrow=r1(radius*1.6);marker.setAttribute('markerWidth',arrow);marker.setAttribute('markerHeight',arrow);}
     }
     if(!skipPaint)paint();
   }
   function zoom(factor,cx=W/2,cy=H/2) {
     autofit=false;
     const k=Math.min(6,Math.max(0.1,view.k*factor)),ratio=k/view.k;
     view.x=cx-(cx-view.x)*ratio;view.y=cy-(cy-view.y)*ratio;view.k=k;applyView();
   }
   // Adatta zoom e posizione al riquadro dei nodi: un layout a forze può essere più grande dell'area visibile.
   function fit(skipPaint) {
     if(!nodes.length||!viewport)return;
     let x0=Infinity,x1=-Infinity,y0=Infinity,y1=-Infinity;
     for(const node of nodes){const p=positions.get(node.id);x0=Math.min(x0,p.x);x1=Math.max(x1,p.x);y0=Math.min(y0,p.y);y1=Math.max(y1,p.y);}
     const pad=44,k=Math.min(6,Math.max(0.1,Math.min((W-2*pad)/Math.max(x1-x0,1),(H-2*pad)/Math.max(y1-y0,1))));
     view={k,x:W/2-k*(x0+x1)/2,y:H/2-k*(y0+y1)/2};applyView(skipPaint);
   }
   function tools(parent) {
     const bar=element('div',undefined,parent);bar.className='map-tools';
     const add=(text,label,action)=>{const button=element('button',text,bar);button.type='button';button.setAttribute('aria-label',label);button.addEventListener('click',action);return button;};
     add('+','Ingrandisci il disegno',()=>zoom(1.25));add('−','Riduci il disegno',()=>zoom(1/1.25));
     add('Reimposta vista','Reimposta zoom e posizione',()=>{autofit=true;fit();});
     add('Ricalcola layout','Ricalcola il layout a forze',()=>{autofit=true;heat();loop();});
     status=element('span','',bar);status.className='hint';status.setAttribute('role','status');
   }
   function legend(parent) {
     const types=[...new Set(nodes.map(node=>node.tipo||''))].sort();
     const list=element('ul',undefined,parent);list.className='legend';
     for(const tipo of types){const item=element('li',undefined,list),mark=svgEl('svg',{width:'12',height:'12','aria-hidden':'true'},item);
       svgEl('circle',{cx:'6',cy:'6',r:'6',fill:color(tipo)},mark);element('span',' '+(tipo||'Tipo non dichiarato'),item);}
   }
   function build(onBuilt) {
     cancelAnimationFrame(frame);
     const container=host();container.replaceChildren();
     svg=viewport=marker=status=null;linkEls=[];nodeEls=new Map();  // un disegno vuoto non deve lasciare elementi di quello precedente
     if(!nodes.length){building++;return;}
     tools(container);
     svg=svgEl('svg',{viewBox:'0 0 '+W+' '+H,role:'group','aria-label':'Grafo diretto. Stessi nodi disponibili nella lista accanto.'});  // staccato finché non è completo: un solo reflow
     marker=svgEl('marker',{id:'arrow',viewBox:'0 0 10 10',refX:'9',refY:'5',markerWidth:'6',markerHeight:'6',markerUnits:'userSpaceOnUse',orient:'auto-start-reverse'},svgEl('defs',{},svg));
     svgEl('path',{d:'M 0 0 L 10 5 L 0 10 z',fill:'#73827a'},marker);
     svgEl('rect',{x:'0',y:'0',width:W,height:H,fill:'transparent','data-background':'1'},svg);
     viewport=svgEl('g',{},svg);
     nodeEls=new Map();light=nodes.length>600;paintedRadius=0;labelsShown=null;linkEls=[];
     const total=edges.length+nodes.length,token=++building,arrows=edges.length<=ARROWS_UP_TO;
     const make=index=>{
       if(index<edges.length){const edge=edges[index],line=svgEl('line',{stroke:'#73827a','stroke-width':'1','vector-effect':'non-scaling-stroke',...(arrows?{'marker-end':'url(#arrow)'}:{})},viewport);
         if(!light)svgEl('title',{},line).textContent=edge.source_id+' → '+edge.type+' → '+edge.target_id;linkEls.push({edge,line});return;}
       const node=nodes[index-edges.length],group=svgEl('g',{tabindex:'0',role:'button','aria-label':'Apri '+node.id,'data-node':node.id},viewport);
       svgEl('circle',{r:'6',fill:color(node.tipo),stroke:'#fff','stroke-width':'1.5','vector-effect':'non-scaling-stroke',class:'node-dot'},group);
       svgEl('text',{y:'21','text-anchor':'middle','font-size':'11',fill:'#242b2c',visibility:'hidden'},group).textContent=node.id;
       if(!light)svgEl('title',{},group).textContent=node.id+(node.tipo?' · '+node.tipo:'');
       group.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();onOpen(node.id);}});
       nodeEls.set(node.id,group);
     };
     const finish=()=>{
       viewport.removeAttribute('visibility');
       pointers();applyView();paint();paintMarks();legend(container);
       element('p','Rotella o pulsanti per lo zoom, trascina lo sfondo per spostare, Invio su un nodo per aprirlo. Disegno limitato a '+MAX_NODES+' nodi'+(edges.length>ARROWS_UP_TO?' (frecce nascoste oltre '+ARROWS_UP_TO+' archi)':'')+'; etichette complete e tipi nelle liste.',container).className='hint';
       onBuilt();
     };
     // Il disegno si costruisce a blocchi tra un fotogramma e l'altro (staccato dal documento): nessun fotogramma lungo a 2000 nodi.
     viewport.setAttribute('visibility','hidden');container.append(svg);  // nel documento da subito (niente reflow finale di 6000 elementi), ma invisibile finché non è posizionato
     let done=0;
     const chunk=()=>{
       if(token!==building)return;
       const start=performance.now();
       while(done<total&&(done%50!==0||performance.now()-start<CHUNK_MS))make(done++);
       if(status)status.textContent='Costruzione del disegno… '+Math.round(100*done/total)+'%';
       if(done<total)requestAnimationFrame(chunk);else finish();
     };
     if(total<=BUILD_SYNC){for(;done<total;done++)make(done);finish();}else chunk();
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
     seed(nodes);view={x:0,y:0,k:1};marks=null;autofit=true;build(()=>{heat();loop();});
   }
   // Aggiunge nodi e archi al disegno senza ricominciare il layout da zero. Restituisce quanti nodi nuovi sono entrati.
   function expand(newNodes,newEdges,around) {
     const known=new Set(nodes.map(node=>node.id)),fresh=newNodes.filter(node=>!known.has(node.id)).slice(0,Math.max(0,MAX_NODES-nodes.length));
     const keys=new Set(edges.map(edgeKey));
     nodes=nodes.concat(fresh);const ids=new Set(nodes.map(node=>node.id));
     edges=edges.concat(newEdges.filter(edge=>ids.has(edge.source_id)&&ids.has(edge.target_id)&&!keys.has(edgeKey(edge))));
     seed(fresh,around);autofit=true;build(()=>{heat(2);loop();});
     return fresh.length;
   }
   return {render,expand,highlight,has:id=>nodes.some(node=>node.id===id),size:()=>nodes.length,max:MAX_NODES};
 }
"""
