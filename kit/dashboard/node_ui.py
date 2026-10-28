"""Strumenti del nodo selezionato: autori, catena causale, vicinato nel disegno ed editor del grafo (anteprima → applica)."""
NODE_SCRIPT = r"""
 function createNodeTools({api,element,plain,url,getState,getVault,getEpoch,stopped,graphView,getVocabulary,onOperation,reopen}) {
   const when=text=>text?String(text).slice(0,10):'data non nota';
   const OPS=[['add_relation','Aggiungi relazione'],['remove_relation','Togli relazione'],['set_tags','Imposta tag'],
              ['set_aliases','Imposta alias'],['set_tipo','Cambia tipo'],['set_relation_detail','Dettaglio di una causa']];
   const list=text=>text.split(',').map(item=>item.trim()).filter(Boolean);
   function authors(container,body) {
     element('h4','Autori',container);
     const a=body.authors;
     if(!a){element('p','Nessun autore disponibile: serve un vault con storia Git e un grafo ricostruito dopo il primo commit.',container).className='hint';return;}
     element('p','Creata da '+(a.created_by||'?')+' il '+when(a.created_at)+' · ultima modifica di '+(a.modified_by||'?')+' il '+when(a.modified_at)
       +(a.agent?' (agente '+a.agent+')':'')+' · '+a.changes+(a.changes===1?' commit':' commit'),container);
   }
   function causal(container,node) {
     element('h4','Catena causale',container);
     const row=element('div',undefined,container),out=element('div',undefined,container);
     const depth=element('select',undefined,row);depth.setAttribute('aria-label','Profondità della catena');
     for(const n of [1,2,3,5,10])depth.append(new Option('fino a '+n+(n===1?' passo':' passi'),String(n)));depth.value='3';
     const run=async direction=>{
       out.replaceChildren();element('p','Lettura della catena…',out);
       try{
         const body=await api(url('causal',{node,direction,depth:depth.value}));out.replaceChildren();
         if(!body.edges.length){element('p',direction==='effects'?'Nessun effetto dichiarato con la relazione causa.':'Nessuna causa dichiarata con la relazione causa.',out);graphView.highlight(null);return;}
         graphView.expand(body.nodes,body.edges,node);graphView.highlight(body.nodes.map(item=>item.id),body.edges);
         const items=element('ul',undefined,out);
         for(const edge of body.edges){const li=element('li','Passo '+edge.level+' · '+edge.source_id+' → causa → '+edge.target_id,items);
           if(edge.confidenza||edge.evidenza)element('small',' · '+(edge.confidenza?'confidenza '+edge.confidenza:'')+(edge.evidenza?' · «'+edge.evidenza+'»':''),li);}
         if(body.cycle)element('p','La catena torna al nodo di partenza: ciclo causale.',out).className='hint';
         if(body.truncated)element('p','Catena limitata ai primi archi.',out).className='hint';
         const clear=element('button','Togli evidenza dal disegno',out);clear.type='button';clear.addEventListener('click',()=>graphView.highlight(null));
       }catch(error){out.replaceChildren();element('p','Catena non disponibile: '+error.message,out);}
     };
     for(const [direction,text] of [['effects','Mostra gli effetti'],['causes','Mostra le cause']]){const button=element('button',text,row);button.type='button';button.addEventListener('click',()=>run(direction));}
   }
   function neighborhood(container,node) {
     const out=element('p',undefined,container),button=element('button','Espandi il vicinato nel disegno',container);button.type='button';
     button.addEventListener('click',async()=>{
       button.disabled=true;
       try{const body=await api(url('neighbors',{node,limit:'100'}));
         const added=graphView.expand(body.nodes,body.edges,node);
         out.textContent=added+' nodi aggiunti al disegno'+(body.truncated?' (vicinato limitato a 100 archi)':'')+(graphView.size()>=graphView.max?' · limite del disegno raggiunto':'')+'.';
       }catch(error){out.textContent='Vicinato non disponibile: '+error.message;}finally{button.disabled=false;}
     });
   }
   function editor(container,node,body) {
     const state=getState(),details=element('details',undefined,container);element('summary','Modifica il grafo · anteprima, poi applica',details);
     if(!state?.capabilities?.graph_edit||!state.live_content_revision){element('p','Modifica non disponibile per questo vault: serve un vault compatibile con revisione corrente leggibile.',details);return;}
     element('p','La modifica riscrive solo il frontmatter di questa pagina, mai il testo. Nessuna scrittura avviene prima dell\'applicazione confermata.',details).className='hint';
     const operations=[],queue=element('ul',undefined,details),form=element('div',undefined,details),result=element('div',undefined,details);
     const kind=element('select',undefined,form);kind.setAttribute('aria-label','Tipo di modifica');for(const [value,text] of OPS)kind.append(new Option(text,value));
     const fields=element('div',undefined,form);
     const input=(label,tag='input')=>{const wrap=element('div',undefined,fields),id='edit-'+Math.random().toString(36).slice(2);
       const l=element('label',label,wrap);const field=element(tag,undefined,wrap);field.id=id;l.htmlFor=id;return field;};
     const choice=(label,values)=>{const field=input(label,'select');for(const value of values)field.append(new Option(value,value));return field;};
     let read=()=>({});
     const draw=()=>{
       fields.replaceChildren();const k=kind.value,vocabulary=getVocabulary(),relations=vocabulary.relations,others=vocabulary.nodes.filter(id=>id!==node);
       if(k==='add_relation'||k==='remove_relation'){
         const relation=choice('Relazione',relations),target=input('Pagina di destinazione');target.setAttribute('list','edit-targets');
         const hints=element('datalist',undefined,fields);hints.id='edit-targets';for(const id of others.slice(0,500))hints.append(new Option(id,id));
         read=()=>({op:k,relation:relation.value,target:target.value.trim()});
       } else if(k==='set_tags'||k==='set_aliases'){
         const field=k==='set_tags'?'tags':'aliases',current=field==='tags'?list(String(body.properties.tags??'').replace(/[\[\]]/g,'')):body.aliases;
         const text=input(field==='tags'?'Tag, separati da virgola':'Alias, separati da virgola');text.value=current.join(', ');
         read=()=>({op:k,[field]:list(text.value)});
       } else if(k==='set_tipo'){
         const tipo=choice('Tipo',vocabulary.types);tipo.value=body.node.tipo||tipo.value;read=()=>({op:k,tipo:tipo.value});
       } else {
         const target=input('Effetto già dichiarato con causa'),confidence=choice('Confidenza',['','alta','media','bassa']),evidence=input('Evidenza (una riga)');
         read=()=>({op:k,target:target.value.trim(),confidenza:confidence.value||null,evidenza:evidence.value.trim()||null});
       }
     };
     kind.addEventListener('change',draw);draw();
     const drawQueue=()=>{queue.replaceChildren();operations.forEach((operation,index)=>{const li=element('li',JSON.stringify(operation)+' ',queue);
       const remove=element('button','Rimuovi',li);remove.type='button';remove.addEventListener('click',()=>{operations.splice(index,1);drawQueue();result.replaceChildren();});});};
     const add=element('button','Aggiungi alla modifica',details);add.type='button';
     add.addEventListener('click',()=>{if(operations.length>=16){result.textContent='Al più 16 operazioni per modifica.';return;}operations.push(read());drawQueue();result.replaceChildren();});
     const preview=element('button','Anteprima',details);preview.type='button';
     preview.addEventListener('click',async()=>{
       if(!operations.length){result.textContent='Aggiungi almeno una modifica.';return;}
       const run=getEpoch(),vault=getVault(),key=crypto.randomUUID().replaceAll('-','');preview.disabled=true;result.replaceChildren();element('p','Calcolo dell\'anteprima…',result);
       try{
         const path='/api/v1/vaults/'+encodeURIComponent(vault)+'/nodes/'+encodeURIComponent(node)+'/edit/';
         const proposal=await api(path+'preview',{base_content_digest:getState().live_content_revision,idempotency_key:key,operations});
         if(run!==getEpoch()||stopped())return;result.replaceChildren();
         element('h4','Differenze nel frontmatter · Markdown come testo',result);element('pre',plain(proposal.diff),result);
         if(!proposal.valid){element('p','La proposta non supera la validazione del grafo, non si può applicare:',result);
           const bad=element('ul',undefined,result);for(const item of proposal.problems)element('li',item.code+' · '+item.reason,bad);return;}
         const sure=element('input',undefined,result);sure.type='checkbox';sure.id='edit-sure-'+key;
         element('label','Ho sospeso editor e hook esterni e ho letto le differenze.',result).htmlFor=sure.id;
         const apply=element('button','Applica la modifica',result);apply.type='button';
         apply.addEventListener('click',async()=>{
           if(!sure.checked){element('p','Conferma prima la sospensione degli scrittori esterni e la lettura delle differenze.',result);return;}
           apply.disabled=true;
           try{
             const job=await api(path+'apply',{preview_id:proposal.preview_id,proposal_hash:proposal.proposal_hash,idempotency_key:crypto.randomUUID().replaceAll('-',''),
               mode:'manual_paused',external_writers_paused:true,semantic_reviewed:true},{'If-Match':'"'+proposal.base_content_digest+'"'});
             if(run!==getEpoch()||stopped())return;
             result.replaceChildren();element('p','Modifica avviata ('+job.operation_id+'). Segui lo stato qui sopra; poi premi Aggiorna vista.',result);
             onOperation(vault,job.operation_id);
           }catch(error){element('p',error.code+': '+error.message+' · Rileggi il nodo e crea una nuova anteprima.',result);}
         });
       }catch(error){if(run===getEpoch()){result.replaceChildren();element('p',(error.code?error.code+': ':'')+error.message,result);}}
       finally{preview.disabled=false;}
     });
   }
   function mount(container,body) {
     const node=body.node.id;
     authors(container,body);
     causal(container,node);
     neighborhood(container,node);
     if(body.node.path)editor(container,node,body);
   }
   return {mount};
 }
"""
