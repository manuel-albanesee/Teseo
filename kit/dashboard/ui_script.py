"""Client readonly: revisioni fissate, concorrenza controllata, testo inerte."""
SCRIPT = r"""
(() => {
 'use strict';
 const $ = id => document.getElementById(id);
 const token = new URLSearchParams(location.hash.slice(1)).get('session');
 history.replaceState(null, '', location.pathname);
 const element = (tag, text, parent) => {const el = document.createElement(tag); if(text !== undefined) el.textContent = text; if(parent) parent.append(el); return el;};
 // Remove one transport escaping layer, then use textContent even for Markdown.
 const plain = text => (text || '').replace(/&(amp|lt|gt);/g, (_, key) => ({amp:'&',lt:'<',gt:'>'})[key]);
 // A new vault/refresh invalidates every pending response. Graph and detail
 // counters additionally protect independent selections within that view.
 let csrf = '', epoch = 0, graphRequest = 0, detailRequest = 0, state = null;
 let nodes = [], edges = [], cursor = null, filters = {}, invalid = false, loadingGraph = false;
 async function api(path, data) {
   const headers = {'X-Teseo-Session':token}, options = {headers,cache:'no-store'};
   if(data !== undefined) {options.method='POST';headers['Content-Type']='application/json';if(csrf) headers['X-Teseo-CSRF']=csrf;options.body=JSON.stringify(data);}
   const response = await fetch(path, options); const body = await response.json();
   if(!response.ok) {const error = new Error(body.error?.message || 'Servizio non disponibile');error.code=body.error?.code;throw error;}
   return body;
 }
 function url(endpoint, parameters={}) {
   return '/api/v1/vaults/' + encodeURIComponent(state.vault_id) + '/' + endpoint + '?' + new URLSearchParams({generation:state.graph_generation,...parameters});
 }
 function failure(error) {
   if(error.code === 'revision_changed') {invalid=true;graphRequest++;detailRequest++;$('more').disabled=true;$('apply').disabled=true;
     $('notice').textContent='È disponibile una nuova generazione. La vista conserva i dati precedenti. Premi Aggiorna vista per caricare una revisione coerente.';
   } else $('notice').textContent=(error.code ? error.code + ': ' : 'Connessione non disponibile: ') + error.message + '. Riprova con Aggiorna vista.';
 }
 function nodeButton(parent, id) {const button=element('button',id,parent);button.type='button';button.addEventListener('click',()=>openNode(id));return button;}
 function relationList(parent, list) {
   for(const edge of list) {const li=element('li',undefined,parent);nodeButton(li,edge.source_id);element('span',' → '+edge.type+' → ',li);nodeButton(li,edge.target_id);}
 }
 function graphMap(list) {
   $('map').replaceChildren();
   if(!list.length) return;
   const visible=list.slice(0,12), positions=new Map();
   const svgElement=(tag,attrs,parent)=>{const el=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [key,value] of Object.entries(attrs))el.setAttribute(key,value);parent.append(el);return el;};
   const svg=svgElement('svg',{viewBox:'0 0 900 350',role:'group','aria-label':'Grafo diretto. Stessi nodi disponibili nella lista seguente.'},$('map'));
   const defs=svgElement('defs',{},svg), marker=svgElement('marker',{id:'arrow',viewBox:'0 0 10 10',refX:'9',refY:'5',markerWidth:'7',markerHeight:'7',orient:'auto-start-reverse'},defs);
   svgElement('path',{d:'M 0 0 L 10 5 L 0 10 z',fill:'#73827a'},marker);
   visible.forEach((node,i)=>{const angle=2*Math.PI*i/visible.length;positions.set(node.id,[450+345*Math.cos(angle),175+125*Math.sin(angle)]);});
   const links=edges.filter(edge=>positions.has(edge.source_id)&&positions.has(edge.target_id)).slice(0,80);
   for(const edge of links) {const a=positions.get(edge.source_id),b=positions.get(edge.target_id),distance=Math.hypot(b[0]-a[0],b[1]-a[1]);if(!distance)continue;
     const line=svgElement('line',{x1:a[0],y1:a[1],x2:b[0]-(b[0]-a[0])*17/distance,y2:b[1]-(b[1]-a[1])*17/distance,stroke:'#73827a','marker-end':'url(#arrow)'},svg);
     svgElement('title',{},line).textContent=edge.source_id+' → '+edge.type+' → '+edge.target_id;
   }
   for(const node of visible) {const [x,y]=positions.get(node.id),group=svgElement('g',{tabindex:'0',role:'button','aria-label':'Apri '+node.id},svg);
     svgElement('circle',{cx:x,cy:y,r:'29',fill:'transparent'},group);svgElement('circle',{cx:x,cy:y,r:'13',class:'dot'},group);const label=svgElement('text',{x:x,y:y+28,'text-anchor':'middle'},group);label.textContent=node.id.length>18?node.id.slice(0,16)+'…':node.id;
     svgElement('title',{},group).textContent=node.id;group.addEventListener('click',()=>openNode(node.id));group.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();openNode(node.id);}});
   }
   element('p','Il grafo scorre orizzontalmente su schermi stretti. Frecce: sorgente → destinazione. Disegno limitato a 12 nodi e 80 archi; etichette complete e tipi nelle liste.', $('map')).className='hint';
 }
 function renderGraph() {
   const query=$('search').value.toLocaleLowerCase('it'), list=nodes.filter(node=>(node.id+' '+(node.descrizione||'')).toLocaleLowerCase('it').includes(query));
   $('counts').textContent=nodes.length+' nodi e '+edges.length+' archi caricati · '+list.length+' nodi corrispondenti'+(cursor?' · Dati parziali: altre pagine disponibili.':' · Fine delle pagine per questi filtri.');
   $('nodes').replaceChildren();
   if(!list.length) element('li','Nessun nodo corrispondente. Modifica la ricerca o i filtri.', $('nodes'));
   for(const node of list) {const li=element('li',undefined,$('nodes'));const button=nodeButton(li,node.id);element('small',node.tipo || 'Tipo non dichiarato',button);}
   $('edges').replaceChildren();relationList($('edges'),edges);
   if(!edges.length) element('li','Nessuna relazione caricata per questi filtri.',$('edges'));
   $('more').hidden=!cursor;$('more').disabled=invalid||loadingGraph;graphMap(list);
 }
 async function loadGraph(more=false) {
   if(!state?.graph_generation || invalid || (more && loadingGraph))return;
   const run=epoch,request=++graphRequest;const parameters={limit:'50',...filters};if(more)parameters.cursor=cursor;
   loadingGraph=true;$('more').disabled=true;$('apply').disabled=true;$('counts').textContent='Caricamento del grafo…';
   try {const body=await api(url('graph',parameters));if(run!==epoch||request!==graphRequest)return;
     nodes=more?nodes.concat(body.nodes):body.nodes;edges=more?edges.concat(body.edges):body.edges;cursor=body.next_cursor;renderGraph();
   } catch(error) {if(run===epoch&&request===graphRequest){renderGraph();failure(error);}}
   finally {if(run===epoch&&request===graphRequest){loadingGraph=false;$('apply').disabled=invalid;$('more').disabled=invalid;}}
 }
 async function openNode(id) {
   if(!state?.graph_generation||invalid)return;
   const run=epoch,request=++detailRequest;
   $('detail').replaceChildren();element('h3',id,$('detail'));element('p','Caricamento del dettaglio…',$('detail'));$('detail').focus();
   try {const body=await api(url('nodes/'+encodeURIComponent(id)));if(run!==epoch||request!==detailRequest)return;
     const container=$('detail');container.replaceChildren();element('h3',body.node.id,container);element('p',body.node.path || 'Fonte senza documento wiki',container).className='hint';
     element('h4','Proprietà',container);const dl=element('dl',undefined,container);
     for(const [key,value] of Object.entries(body.properties)) {element('dt',key,dl);element('dd',typeof value==='string'?value:JSON.stringify(value),dl);}
     element('p','Alias: '+(body.aliases.join(', ')||'nessuno')+(body.aliases_truncated?' (lista parziale)':''),container);
     element('h4','Fonti',container);const sources=element('ul',undefined,container);for(const source of body.sources)nodeButton(element('li',undefined,sources),source);
     if(!body.sources.length)element('li','Nessuna fonte dichiarata.',sources);
     element('h4','Relazioni · sorgente → destinazione',container);relationList(element('ul',undefined,container),body.relations);
     if(body.sources_truncated||body.relations_truncated)element('p','Fonti o relazioni limitate ai primi 200 risultati.',container);
     element('h4','Testo della nota · Markdown come testo',container);element('pre',body.text===null?'Nessun testo associato.':plain(body.text),container);
   } catch(error) {if(run===epoch&&request===detailRequest){element('p','Dettaglio non disponibile: '+error.message,$('detail'));failure(error);}}
 }
 function renderOntology(body) {
   const container=$('ontology');container.replaceChildren();element('h3','Vocabolario e direzione',container);
   element('p','Tipi '+(body.types_source==='declared'?'dichiarati':'osservati e ricavati dai vincoli')+': '+(body.types.join(', ')||'nessuno'),container);
   for(const relation of body.relations) {const article=element('article',undefined,container);element('h4',relation.name,article);element('p',relation.from_types.join(', ')+' → '+relation.to_types.join(', '),article);element('p',relation.meaning||'Significato non dichiarato.',article);if(relation.example)element('p','Esempio: '+relation.example,article);}
   const details=element('details',undefined,container);element('summary','Schema completo · Markdown come testo',details);element('pre',plain(body.text),details);
 }
 function renderDiagnostics(body) {
   const container=$('diagnostics');container.replaceChildren();element('h3','Problemi della revisione pubblicata',container);
   element('p','La diagnostica non analizza le modifiche non ancora pubblicate nel grafo.',container).className='hint';
   const list=element('ul',undefined,container);for(const issue of body.issues)element('li',issue.severity+' · '+issue.code+' · '+issue.message+(issue.path?' · '+issue.path:''),list);
   if(!body.issues.length)element('li','Nessun problema rilevato nei controlli disponibili.',list);
   if(body.truncated)element('p','Elenco parziale: limite di diagnostica raggiunto.',container);
 }
 async function selectVault() {
   const run=++epoch;++graphRequest;++detailRequest;state=null;invalid=false;loadingGraph=false;nodes=[];edges=[];cursor=null;filters={};
   for(const id of ['type','relation','search','apply'])$(id).disabled=true;
   $('type').replaceChildren(new Option('Tutti i tipi',''));$('relation').replaceChildren(new Option('Tutte le relazioni',''));$('search').value='';
   for(const id of ['nodes','edges','map','ontology','diagnostics'])$(id).replaceChildren();
   $('detail').replaceChildren();element('h3','Dettaglio nodo',$('detail'));element('p','Seleziona un nodo dalla lista o dal grafo.',$('detail'));
   $('more').hidden=true;$('notice').textContent='';$('revision').textContent='';$('counts').textContent='Caricamento…';
   const id=$('vault').value;$('refresh').disabled=!id;if(!id){$('counts').textContent='Nessun dato caricato.';for(const view of ['ontology','diagnostics'])element('p','Collega un vault per consultare questa vista.',$(view));return;}
   $('root').textContent='Caricamento dello stato…';
   try {
     const status=await api('/api/v1/vaults/'+encodeURIComponent(id)+'/status');if(run!==epoch)return;state=status;
     $('root').textContent=status.path;$('revision').textContent='Contenuti: '+(status.content_revision||'non disponibili')+' · Generazione: '+(status.graph_generation||'non disponibile')+' · Stato operazioni: non disponibile';
     $('notice').textContent=(status.issues||[]).map(issue=>issue.code+': '+issue.message).join(' · ');
     if(!status.capabilities.graph){$('counts').textContent='Grafo non disponibile. È necessario un rebuild esplicito con il kit aggiornato; questa vista non modifica il vault.';element('p','Ontologia non disponibile senza una generazione del grafo.',$('ontology'));renderDiagnostics({issues:status.issues});return;}
     if(status.stale)$('notice').textContent+=' · Stai consultando la revisione pubblicata; le modifiche del vault non sono ancora nel grafo.';
     const pin=url('ontology'),diagnostics=url('diagnostics');
     const results=await Promise.allSettled([api(pin),api(diagnostics)]);if(run!==epoch)return;
     if(results[0].status==='fulfilled') {const ontology=results[0].value;renderOntology(ontology);
       for(const type of ontology.types)$('type').append(new Option(type,type));
       for(const relation of ontology.relations)$('relation').append(new Option(relation.name,relation.name));
     } else {element('p','Ontologia non disponibile: '+results[0].reason.message,$('ontology'));failure(results[0].reason);}
     if(results[1].status==='fulfilled')renderDiagnostics(results[1].value);else{element('p','Diagnostica non disponibile: '+results[1].reason.message,$('diagnostics'));failure(results[1].reason);}
     for(const key of ['type','relation','search','apply'])$(key).disabled=invalid;
     if(invalid)$('counts').textContent='Caricamento interrotto: aggiorna la vista per leggere la nuova generazione.';
     else await loadGraph();
   } catch(error){if(run===epoch){$('counts').textContent='Dati non disponibili.';failure(error);}}
 }
 async function refreshVaults(preferred) {
   const body=await api('/api/v1/vaults');const current=preferred||$('vault').value;
   $('vault').replaceChildren();for(const vault of body.vaults)$('vault').append(new Option(vault.path,vault.vault_id));
   if(!body.vaults.length)$('vault').append(new Option('Nessun vault collegato',''));
   if(body.vaults.some(v=>v.vault_id===current))$('vault').value=current;
   $('vault').disabled=!body.vaults.length;await selectVault();
 }
 $('vault').addEventListener('change',selectVault);$('refresh').addEventListener('click',selectVault);
 $('search').addEventListener('input',renderGraph);$('more').addEventListener('click',()=>loadGraph(true));
 $('filters').addEventListener('submit',event=>{event.preventDefault();if(invalid)return;filters={};if($('type').value)filters.type=$('type').value;if($('relation').value)filters.relation=$('relation').value;nodes=[];edges=[];cursor=null;renderGraph();loadGraph();});
 document.querySelectorAll('[data-view]').forEach(button=>button.addEventListener('click',()=>{for(const view of ['graph','ontology','diagnostics'])$(view).hidden=view!==button.dataset.view;document.querySelectorAll('[data-view]').forEach(item=>item.setAttribute('aria-pressed',String(item===button)));}));
 $('attach').addEventListener('submit',async event=>{event.preventDefault();$('connect').disabled=true;
   try {const vault=await api('/api/v1/vaults/attach',{path:$('path').value});await refreshVaults(vault.vault_id);$('message').textContent='Vault collegato. Nessun file modificato.';}
   catch(error){$('message').textContent=error.message;}finally{$('connect').disabled=false;}
 });
 (async()=>{if(!token){$('message').textContent='Sessione assente. Apri il collegamento completo stampato dal launcher.';return;}
   try {csrf=(await api('/api/v1/session',{})).csrf_token;await refreshVaults();$('connect').disabled=false;$('message').textContent='Servizio pronto · Sola lettura.';}
   catch(error){$('message').textContent=error.message;}
 })();
})();
"""
