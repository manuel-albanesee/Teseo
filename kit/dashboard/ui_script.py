"""Workbench: consultazione e proposte ontologia, contenuti sempre inerti."""
from .ontology_ui import EDITOR_SCRIPT
from .skill_ui import SKILL_SCRIPT
from .shared_ui import SHARED_SCRIPT
from .sync_ui import SYNC_SCRIPT
from .graph_ui import GRAPH_SCRIPT
from .node_ui import NODE_SCRIPT
from .admin_ui import ADMIN_SCRIPT
SCRIPT = r"""
(() => {
 'use strict';
""" + EDITOR_SCRIPT + SKILL_SCRIPT + SHARED_SCRIPT + SYNC_SCRIPT + GRAPH_SCRIPT + NODE_SCRIPT + ADMIN_SCRIPT + r"""
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
 let stopping = false, operationPoll = 0, vocabulary = {relations:[], types:[]}, bulkLoading = false;
 const pendingRebuild = new Map();
 async function api(path, data, extraHeaders={}) {
   const headers = {'X-Teseo-Session':token,...extraHeaders}, options = {headers,cache:'no-store'};
   if(data !== undefined) {options.method='POST';headers['Content-Type']='application/json';if(csrf) headers['X-Teseo-CSRF']=csrf;options.body=JSON.stringify(data);}
   const response = await fetch(path, options); const body = await response.json();
   if(!response.ok) {const error = new Error(body.error?.message || 'Servizio non disponibile');error.code=body.error?.code;error.details=body.error?.details;throw error;}
   return body;
 }
 const editor=createOntologyEditor({api,plain,element,getEpoch:()=>epoch,stopped:()=>stopping,onOperation:(vault,id)=>watchOperation(vault,id)});
 const skills=createSkillPanel({api,element,getEpoch:()=>epoch,getVault:()=>$('vault').value,stopped:()=>stopping,onOperation:(vault,id)=>watchOperation(vault,id),reload:()=>$('list-operations').click()});
 const shared=createSharedPanel({api,element,getEpoch:()=>epoch,getVault:()=>$('vault').value,stopped:()=>stopping,reload:()=>$('list-operations').click()});
 const graphView=createGraphView({element,onOpen:id=>openNode(id)});
 const nodeTools=createNodeTools({api,element,plain,url:(endpoint,parameters)=>url(endpoint,parameters),getState:()=>state,getVault:()=>$('vault').value,getEpoch:()=>epoch,
   stopped:()=>stopping,graphView,getVocabulary:()=>({...vocabulary,nodes:nodes.map(node=>node.id)}),onOperation:(vault,id)=>watchOperation(vault,id)});
 const admin=createAdminPanel({api,element,getEpoch:()=>epoch,getVault:()=>$('vault').value,getState:()=>state,getNodes:()=>nodes.map(node=>node.id),stopped:()=>stopping,
   onAdopted:vaultId=>refreshVaults(vaultId),onOperation:(vault,id)=>watchOperation(vault,id)});
 const sync=createSyncPanel({api,element,getEpoch:()=>epoch,getVault:()=>$('vault').value,stopped:()=>stopping});
 $('skill-dispatch').addEventListener('click',async()=>{const vault=$('vault').value;if(!vault||stopping)return;try{await api('/api/v1/vaults/'+encodeURIComponent(vault)+'/dispatch',{});if(vault===$('vault').value)$('list-operations').click();}catch(error){$('operation').textContent=error.code+': '+error.message;}});
 $('list-operations').addEventListener('click',async()=>{
   const vault=$('vault').value,run=epoch;if(!vault||stopping)return;
   const root='/api/v1/vaults/'+encodeURIComponent(vault),container=$('operation-list');container.replaceChildren();
   element('p','Lettura del journal…',container);
   try{const body=await api(root+'/operations');if(run!==epoch)return;container.replaceChildren();
     if(!body.operations.length)element('p','Nessuna operazione registrata.',container);
     if(body.truncated)element('p','Visualizzate le ultime 50 operazioni.',container);
     for(const item of body.operations){const section=element('section',undefined,container);element('p',item.operation_id+' · '+item.kind+' · '+item.state,section);
       skills.render(item,section);
       if(item.error)element('p',item.error.code+' · '+item.error.message,section);
       if(['ontology_apply','graph_edit'].includes(item.kind)&&item.state==='recovery_required'){
         element('p','Recovery manuale non protetto: sospendi editor/hook e verifica base, candidato e backup. Un conflitto estraneo blocca il recovery.',section);
         const input=element('input',undefined,section);input.type='checkbox';input.id='recover-'+item.operation_id;
         const label=element('label','Ho sospeso gli scrittori esterni e revisionato lo stato dei file e dei backup.',section);label.htmlFor=input.id;
         for(const [action,text]of [['finish','Completa candidato'],['rollback','Ripristina base']]){const button=element('button',text,section);button.type='button';button.disabled=!body.live_content_revision;
           button.addEventListener('click',async()=>{if(!input.checked){element('p','Conferma prima la sospensione e la revisione.',section);return;}button.disabled=true;
             try{const job=await api(root+'/operations/'+encodeURIComponent(item.operation_id)+'/recover',{action,mode:'manual_paused',external_writers_paused:true,semantic_reviewed:true},{'If-Match':'"'+body.live_content_revision+'"'});if(run===epoch)watchOperation(vault,job.operation_id);}
             catch(error){if(run===epoch)element('p',error.code+': '+error.message+' · Rileggi le operazioni prima di riprovare.',section);}
           });}
       }
     }
   }catch(error){if(run===epoch)element('p','Operazioni non disponibili: '+error.message,container);}
 });
 function url(endpoint, parameters={}) {
   return '/api/v1/vaults/' + encodeURIComponent(state.vault_id) + '/' + endpoint + '?' + new URLSearchParams({generation:state.graph_generation,...parameters});
 }
 function failure(error) {
   if(error.code === 'revision_changed') {invalid=true;graphRequest++;detailRequest++;$('more').disabled=true;$('apply').disabled=true;
     $('notice').textContent='È disponibile una nuova generazione. La vista conserva i dati precedenti. Premi Aggiorna vista per caricare una revisione coerente.';
   } else $('notice').textContent=(error.code ? error.code + ': ' : 'Connessione non disponibile: ') + error.message + '. Riprova con Aggiorna vista.';
 }

 async function watchOperation(vaultId, identifier) {
   const run=epoch, poll=++operationPoll;let unavailable=0;
   $('rebuild').disabled=true;
   while(run===epoch && poll===operationPoll && !stopping) {
     try {
       const job=await api('/api/v1/vaults/'+encodeURIComponent(vaultId)+'/operations/'+encodeURIComponent(identifier));unavailable=0;
       if(run!==epoch || poll!==operationPoll || stopping)return;
       const terminal=['succeeded','rolled_back','failed','cancelled','blocked_external_change','recovery_required'].includes(job.state)&&!(job.kind==='graph_edit'&&job.publication?.state==='pending');  // la pubblicazione automatica segue l'apply: si continua a leggere finché non ha un esito
       $('operation').textContent=(job.kind==='rebuild'?'Rebuild ':job.kind==='graph_edit'?'Modifica del grafo ':'Operazione note ')+identifier+' · '+job.state;
       if(['succeeded','rolled_back'].includes(job.state))$('operation').textContent+=' · Completato. File cambiati: '+(job.checkpoint?.changed_files||[]).join(', ')+'. Premi Aggiorna vista per caricare la generazione pubblicata.';
       if(job.state==='recovery_required')$('operation').textContent+=' · Conserva base, candidato e backup. Sospendi gli editor e scegli recovery esplicito; nessun rollback automatico.';
       if(job.publication)$('operation').textContent+=' · Pubblicazione: '+job.publication.state+(job.publication.message?' ('+job.publication.message+')':'');
       if(job.error)$('operation').textContent+=' · '+job.error.code+': '+job.error.message+' '+(job.error.details||[]).join(' · ')+' · Correggi il problema e aggiorna la vista prima di riprovare.';
       if(terminal){$('rebuild').disabled=!state?.capabilities.rebuild;return;}
     } catch(error) {
       // Journal momentaneamente occupato da una scrittura (503 ritentabile): qualche altro tentativo prima di arrendersi.
       if(error.code==='operation_unavailable' && ++unavailable<=20){await new Promise(resolve=>setTimeout(resolve,1200));continue;}
       if(run===epoch && poll===operationPoll && !stopping)$('operation').textContent='Stato rebuild '+identifier+' non disponibile: '+error.message+'. Premi Aggiorna vista per riprendere il controllo.';
       return;
     }
     await new Promise(resolve=>setTimeout(resolve,1200));
   }
 }
 $('rebuild').addEventListener('click',async()=>{
   if(!state?.capabilities.rebuild || stopping)return;
   const run=epoch, vaultId=state.vault_id;
   let payload=pendingRebuild.get(vaultId);
   if(!payload){payload={idempotency_key:crypto.randomUUID(),expected_content_revision:state.live_content_revision};pendingRebuild.set(vaultId,payload);}
   $('rebuild').disabled=true;$('operation').textContent='Richiesta rebuild… Le note e i DB personali restano invariati.';
   try {
     const job=await api('/api/v1/vaults/'+encodeURIComponent(vaultId)+'/rebuild',payload);pendingRebuild.delete(vaultId);
     if(run===epoch && !stopping)watchOperation(vaultId,job.operation_id);
   } catch(error) {
     if(error.code)pendingRebuild.delete(vaultId);
     if(run===epoch && !stopping){$('operation').textContent=(error.code?'Richiesta rebuild rifiutata: ':'Esito della richiesta non confermato: ')+error.message+'. Riprova per recuperare il job oppure aggiorna la vista.';$('rebuild').disabled=false;}
   }
 });
 $('shutdown').addEventListener('click',async()=>{
   $('shutdown').disabled=true;
   try {
     await api('/api/v1/shutdown',{});stopping=true;++epoch;++operationPoll;
     document.querySelectorAll('button,input,select,textarea').forEach(control=>control.disabled=true);
     $('message').textContent='Arresto richiesto. Il processo attende la chiusura dei rebuild; controlla il terminale prima di chiuderlo.';
   } catch(error){$('message').textContent='Arresto non confermato: '+error.message+'. Riprova oppure usa Ctrl+C nel terminale.';$('shutdown').disabled=false;}
 });
 function nodeButton(parent, id) {const button=element('button',id,parent);button.type='button';button.addEventListener('click',()=>openNode(id));return button;}
 function relationList(parent, list) {
   for(const edge of list) {const li=element('li',undefined,parent);nodeButton(li,edge.source_id);element('span',' → '+edge.type+' → ',li);nodeButton(li,edge.target_id);}
 }
 function graphMap(list) {graphView.render(list,edges,Number($('map-limit').value)||200);}
 function renderGraph() {
   const query=$('search').value.toLocaleLowerCase('it'), list=nodes.filter(node=>(node.id+' '+(node.descrizione||'')).toLocaleLowerCase('it').includes(query));
   $('counts').textContent=nodes.length+' nodi e '+edges.length+' archi caricati · '+list.length+' nodi corrispondenti'+(cursor?' · Dati parziali: altre pagine disponibili.':' · Fine delle pagine per questi filtri.');
   $('nodes').replaceChildren();
   if(!list.length) element('li','Nessun nodo corrispondente. Modifica la ricerca o i filtri.', $('nodes'));
   for(const node of list) {const li=element('li',undefined,$('nodes'));const button=nodeButton(li,node.id);element('small',node.tipo || 'Tipo non dichiarato',button);}
   $('edges').replaceChildren();relationList($('edges'),edges);
   if(!edges.length) element('li','Nessuna relazione caricata per questi filtri.',$('edges'));
   $('more').hidden=!cursor;$('load-all').hidden=!cursor;$('more').disabled=invalid||loadingGraph;$('load-all').disabled=invalid||loadingGraph;if(!bulkLoading)graphMap(list);
 }
 // Carica pagina dopo pagina fino al limite di nodi del disegno (o alla fine dei dati): per grafi grandi senza cento clic.
 async function loadAll() {
   const run=epoch;
   bulkLoading=true;  // il disegno si ricostruisce una volta sola alla fine, non a ogni pagina
   const limit=Math.min(2000,Math.max(12,Number($('map-limit').value)||200));
   try{while(cursor&&!invalid&&run===epoch&&!loadingGraph&&(nodes.length<limit||edges.length<limit*4))await loadGraph(true);}
   finally{bulkLoading=false;if(run===epoch)renderGraph();}
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
     nodeTools.mount(container,body);
     element('h4','Testo della nota · Markdown come testo',container);element('pre',body.text===null?'Nessun testo associato.':plain(body.text),container);
   } catch(error) {if(run===epoch&&request===detailRequest){element('p','Dettaglio non disponibile: '+error.message,$('detail'));failure(error);}}
 }
 function renderOntology(body) {
   const container=$('ontology-published');container.replaceChildren();element('h3','Vocabolario pubblicato · sorgente → destinazione',container);
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
   admin.exportInto(container);
 }
 async function selectVault() {
   if(stopping)return;
   editor.reset();
   admin.reset();
   skills.reset();
   shared.reset();
   sync.reset();
   $('operation-list').replaceChildren();
   ++operationPoll;$('rebuild').disabled=true;$('operation').textContent='';
   const run=++epoch;++graphRequest;++detailRequest;state=null;invalid=false;loadingGraph=false;nodes=[];edges=[];cursor=null;filters={};
   for(const id of ['type','relation','author','search','map-limit','apply'])$(id).disabled=true;
   vocabulary={relations:[],types:[]};$('author').replaceChildren(new Option('Tutti gli autori',''));
   $('type').replaceChildren(new Option('Tutti i tipi',''));$('relation').replaceChildren(new Option('Tutte le relazioni',''));$('search').value='';
   for(const id of ['nodes','edges','map','ontology-published','diagnostics'])$(id).replaceChildren();
   $('detail').replaceChildren();element('h3','Dettaglio nodo',$('detail'));element('p','Seleziona un nodo dalla lista o dal grafo.',$('detail'));
   $('more').hidden=true;$('notice').textContent='';$('revision').textContent='';$('counts').textContent='Caricamento…';
   const id=$('vault').value;$('refresh').disabled=!id;if(!id){$('counts').textContent='Nessun dato caricato.';for(const view of ['ontology-published','diagnostics'])element('p','Collega un vault per consultare questa vista.',$(view));return;}
   $('root').textContent='Caricamento dello stato…';
   try {
     const status=await api('/api/v1/vaults/'+encodeURIComponent(id)+'/status');if(run!==epoch)return;state=status;
     $('root').textContent=status.path;$('revision').textContent='Contenuti: '+(status.content_revision||'non disponibili')+' · Generazione: '+(status.graph_generation||'non disponibile')+' · Job di questo servizio: '+(status.busy?'rebuild attivo':'nessuno');
     $('rebuild').disabled=!status.capabilities.rebuild || !!status.busy;
     editor.mount(status);
     admin.mount(status);
     skills.mount(status);
     shared.mount(status);
     sync.mount(status);
     if(status.active_operation_id)watchOperation(id,status.active_operation_id);
     else if(!status.capabilities.rebuild)$('operation').textContent='Rebuild non disponibile per questo formato. I vault legacy restano in sola lettura.';
     $('notice').textContent=(status.issues||[]).map(issue=>issue.code+': '+issue.message).join(' · ');
     if(!status.capabilities.graph){$('counts').textContent='Grafo non disponibile. È necessario un rebuild esplicito con il kit aggiornato; questa vista non modifica il vault.';element('p','Vocabolario pubblicato non disponibile senza grafo. La preview usa la base corrente.',$('ontology-published'));renderDiagnostics({issues:status.issues});return;}
     if(status.stale)$('notice').textContent+=' · Stai consultando la revisione pubblicata; le modifiche del vault non sono ancora nel grafo.';
     const pin=url('ontology'),diagnostics=url('diagnostics');
     const results=await Promise.allSettled([api(pin),api(diagnostics),api(url('authors'))]);if(run!==epoch)return;
     if(results[0].status==='fulfilled') {const ontology=results[0].value;renderOntology(ontology);vocabulary={relations:ontology.relations.map(item=>item.name),types:ontology.types};
       for(const type of ontology.types)$('type').append(new Option(type,type));
       for(const relation of ontology.relations)$('relation').append(new Option(relation.name,relation.name));
     } else {element('p','Ontologia pubblicata non disponibile: '+results[0].reason.message,$('ontology-published'));failure(results[0].reason);}
     if(results[1].status==='fulfilled')renderDiagnostics(results[1].value);else{element('p','Diagnostica non disponibile: '+results[1].reason.message,$('diagnostics'));admin.exportInto($('diagnostics'));failure(results[1].reason);}
     if(results[2].status==='fulfilled')for(const author of results[2].value.authors)$('author').append(new Option(author.name+' ('+author.created+' create, '+author.modified+' modificate)',author.name));
     for(const key of ['type','relation','author','search','map-limit','apply'])$(key).disabled=invalid;
     if(invalid)$('counts').textContent='Caricamento interrotto: aggiorna la vista per leggere la nuova generazione.';
     else await loadGraph();
   } catch(error){if(run===epoch){$('counts').textContent='Dati non disponibili.';failure(error);}}
 }
 async function refreshVaults(preferred) {
   const body=await api('/api/v1/vaults');const current=preferred||$('vault').value;
   $('vault').replaceChildren();for(const vault of body.vaults)$('vault').append(new Option(vault.path,vault.vault_id));
   if(!body.vaults.length)$('vault').append(new Option('Nessun vault collegato',''));
   if(body.vaults.some(v=>v.vault_id===current))$('vault').value=current;
   if(body.registry_issues?.length)$('message').textContent=body.registry_issues.map(issue=>issue.message).join(' · ');
   $('vault').disabled=!body.vaults.length;await selectVault();
 }
 $('vault').addEventListener('change',selectVault);$('refresh').addEventListener('click',selectVault);
 $('search').addEventListener('input',renderGraph);$('map-limit').addEventListener('change',renderGraph);$('more').addEventListener('click',()=>loadGraph(true));$('load-all').addEventListener('click',loadAll);
 $('filters').addEventListener('submit',event=>{event.preventDefault();if(invalid)return;filters={};if($('type').value)filters.type=$('type').value;if($('relation').value)filters.relation=$('relation').value;if($('author').value)filters.author=$('author').value;nodes=[];edges=[];cursor=null;renderGraph();loadGraph();});
 document.querySelectorAll('[data-view]').forEach(button=>button.addEventListener('click',()=>{for(const view of ['graph','ontology','diagnostics'])$(view).hidden=view!==button.dataset.view;document.querySelectorAll('[data-view]').forEach(item=>item.setAttribute('aria-pressed',String(item===button)));}));
 $('attach').addEventListener('submit',async event=>{event.preventDefault();$('connect').disabled=true;
   try {const vault=await api('/api/v1/vaults/attach',{path:$('path').value});await refreshVaults(vault.vault_id);$('message').textContent='Vault collegato. Nessun file modificato.';}
   catch(error){$('message').textContent=error.message;}finally{$('connect').disabled=stopping;}
 });
 (async()=>{if(!token){$('message').textContent='Sessione assente. Apri il collegamento completo stampato dal launcher.';return;}
   try {csrf=(await api('/api/v1/session',{})).csrf_token;$('shutdown').disabled=false;await refreshVaults();$('connect').disabled=stopping;if(!stopping && !$('message').textContent.includes('Un vault salvato'))$('message').textContent='Servizio pronto · Note in sola lettura.';}
   catch(error){$('message').textContent=error.message;}
 })();
})();
"""
