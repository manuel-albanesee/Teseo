"""Editor proposte e apply manuale confermato; testo del vault sempre inerte."""
EDITOR_SCRIPT = r"""
 function createOntologyEditor({api, plain, element, getEpoch, stopped, onOperation}) {
   const drafts=new Map();let context=0,timer;
   const initial={category:'relation',action:'add',name:'',to:'',description:'',parent:'',from_types:'',to_types:'',meaning:'',example:''};
   function reset(){++context;clearTimeout(timer);document.getElementById('ontology-editor').replaceChildren();}
   function mount(status) {
     reset();const container=document.getElementById('ontology-editor');
     element('h3','Prepara una modifica',container);
     element('p','Componi e verifica la proposta. L’applicazione manuale richiede conferme separate dopo la preview; nessuna modifica automatica.',container).className='hint';
     if(!status.capabilities.ontology_preview){element('p','Editor non disponibile: il vault legacy resta in sola lettura. È necessario un manifest compatibile, senza adozione automatica.',container);return;}
     if(!status.live_content_revision){element('p','Base corrente non leggibile. Correggi i problemi del vault e premi Aggiorna vista.',container);return;}
     const vault=status.vault_id, run=getEpoch(), active=context;
     if(!drafts.has(vault))drafts.set(vault,{base:status.live_content_revision,patch:[],adopt:false,fields:{...initial},version:0,pending:null,result:null});
     const draft=drafts.get(vault);let busy=false,obsolete=false;
     const current=()=>active===context && run===getEpoch() && !stopped();
     const base=element('p','',container);base.className='hint';
     const rebase=element('button','Aggiorna base corrente',container);rebase.type='button';
     const message=element('p','',container);message.id='ontology-editor-message';message.setAttribute('role','status');message.setAttribute('aria-live','polite');
     const adoption=element('div',undefined,container),adopt=element('input',undefined,adoption);adopt.type='checkbox';adopt.id='ontology-adopt';adopt.checked=draft.adopt;
     const adoptLabel=element('label','Proponi anche l’adozione del catalogo tipi (solo se assente)',adoption);adoptLabel.htmlFor=adopt.id;
     const form=element('form',undefined,container);form.id='ontology-form';
     const grid=element('div',undefined,form);grid.className='ontology-fields';
     const controls={};
     function field(key,label,options) {
       const wrapper=element('div',undefined,grid);wrapper.dataset.field=key;
       const id='ontology-'+key;const title=element('label',label,wrapper);title.htmlFor=id;
       const input=element(options?'select':['description','meaning','example'].includes(key)?'textarea':'input',undefined,wrapper);
       input.id=id;input.name=key;input.setAttribute('aria-describedby','ontology-form-help ontology-editor-message');
       if(options)for(const [value,text]of options)input.append(new Option(text,value));
       else{input.maxLength=['name','to','parent'].includes(key)?64:4096;input.spellcheck=false;}
       input.value=draft.fields[key];controls[key]=input;return input;
     }
     field('category','Elemento',[['relation','Relazione'],['type','Tipo']]);
     field('action','Modifica',[['add','Aggiungi'],['update','Modifica definizione'],['rename','Rinomina'],['remove','Rimuovi']]);
     field('name','Nome');field('to','Nuovo nome');field('description','Descrizione del tipo');field('parent','Sottotipo di (vuoto per un tipo radice)');
     field('from_types','Tipi sorgente · Da');field('to_types','Tipi destinazione · A');
     field('meaning','Significato · X → Y');field('example','Esempio · sorgente → destinazione');
     const direction=element('p','Verso salvato: sorgente → relazione → destinazione. Nessuna inversione automatica.',form);direction.className='ontology-direction';
     const help=element('p','',form);help.id='ontology-form-help';help.className='hint';
     const add=element('button','Aggiungi alla proposta',form);add.type='submit';
     const queue=element('ol',undefined,container);queue.id='ontology-changes';
     const actions=element('div',undefined,container);actions.className='editor-actions';
     const preview=element('button','Genera preview',actions);preview.type='button';preview.id='ontology-preview';
     const clear=element('button','Svuota proposta',actions);clear.type='button';
     const result=element('section',undefined,container);result.id='ontology-result';result.tabIndex=-1;result.setAttribute('aria-label','Risultato della preview');
     function baseLabel(){base.textContent='Base corrente della proposta: '+draft.base+(draft.base!==status.live_content_revision?' · Diversa dall’ultima lettura dello stato. Aggiorna la base prima di riprovare.':'')+' · Bozza solo in memoria; chiudere la scheda la elimina.';}
     function invalidated(text='Bozza modificata. Genera una nuova preview.') {
       ++draft.version;draft.pending=null;obsolete=true;
       message.textContent=text+(draft.result?' La preview precedente non è aggiornata.':'');if(draft.result)result.setAttribute('data-obsolete','true');
       for(const control of result.querySelectorAll('[data-apply-control]'))control.disabled=!draft.applyPending;
     }
     function fields() {
       const relation=controls.category.value==='relation',definition=['add','update'].includes(controls.action.value),rename=controls.action.value==='rename';
       for(const key of ['to','description','parent','from_types','to_types','meaning','example']){
         const visible=key==='to'?rename:['description','parent'].includes(key)?definition&&!relation:definition&&relation;
         controls[key].parentElement.hidden=!visible;controls[key].disabled=!visible;
         controls[key].required=visible&&['to','from_types','to_types'].includes(key);
       }
       controls.name.required=true;direction.hidden=!relation;
       help.textContent=definition?(relation?'Definizione completa. Tipi separati da virgole; ammessi anche «qualsiasi» e «stesso tipo». Significato ed esempio omessi saranno vuoti.':'Definizione completa: descrizione e sottotipo sostituiscono quelli precedenti; un sottotipo omesso rende il tipo radice.'):'La modifica riguarda lo schema candidato. Le eventuali modifiche alle note verranno soltanto suggerite.';
     }
     function drawQueue(){
       queue.replaceChildren();
       if(!draft.patch.length)element('li',draft.adopt?'Solo proposta di adozione del catalogo tipi.':'Nessuna modifica. Aggiungi un elemento alla proposta.',queue);
       const labels={add_relation:'Aggiungi relazione',update_relation:'Modifica relazione',remove_relation:'Rimuovi relazione',rename_relation:'Rinomina relazione',add_type:'Aggiungi tipo',update_type:'Modifica tipo',remove_type:'Rimuovi tipo',rename_type:'Rinomina tipo'};
       draft.patch.forEach((item,index)=>{const li=element('li',undefined,queue);element('span',labels[item.op]+' · '+item.name+(item.to?' → '+item.to:''),li);
         if(item.value){const info=element('details',undefined,li);element('summary','Definizione proposta',info);
           element('p',item.value.from_types?item.value.from_types.join(', ')+' → '+item.name+' → '+item.value.to_types.join(', '):(item.value.description||'Descrizione vuota')+(item.value.parent?' · sottotipo di '+item.value.parent:''),info);
           if(item.value.meaning)element('p',item.value.meaning,info);if(item.value.example)element('p','Esempio: '+item.value.example,info);}
         const remove=element('button','Rimuovi modifica '+(index+1),li);remove.type='button';remove.addEventListener('click',()=>{draft.patch.splice(index,1);invalidated();drawQueue();preview.focus();});});
       preview.disabled=busy||(!draft.adopt&&!draft.patch.length);
     }
     function details(parent,title,values,format){
       const section=element('details',undefined,parent);element('summary',title+' · '+values.length,section);
       const list=element('ul',undefined,section);for(const value of values.slice(0,200))element('li',format(value),list);
       if(!values.length)element('li','Nessun elemento.',list);
       if(values.length>200)element('p','Visualizzati i primi 200 elementi su '+values.length+'. L’analisi del servizio è completa.',section);
     }
     function drawResult(body,focus=false){
       result.replaceChildren();result.removeAttribute('data-obsolete');
       element('h3','Preview della proposta',result);
       element('p',body.schema_only_valid?'Validazione disponibile superata. Nessuna modifica applicata.':'Sono necessarie correzioni o migrazioni. Nessuna modifica applicata.',result);
       element('p','Nessuna nuova inferenza automatica. Aggiungere una relazione non aggiorna le regole di sintesi e le domande del kit.',result).className='ontology-direction';
       element('p','Base: '+body.base_content_digest+' · Preview: '+body.preview_id+' · Scadenza: '+new Date(body.expires_at*1000).toLocaleString('it-IT'),result).className='hint';
       element('p','Hash proposta: '+body.proposal_hash,result).className='hint';
       element('h4','Diff dello schema · base → proposta',result);element('pre',plain(body.schema_diff)||'Nessuna differenza nello schema.',result);
       const schema=element('details',undefined,result);element('summary','Schema candidato · Markdown come testo',schema);element('pre',plain(body.candidate_schema),schema);
       details(result,'Violazioni',body.violations,item=>item.page+' · '+item.property+' · '+item.code+' · '+item.reason+(item.target?' · Destinazione: '+item.target:''));
       details(result,'Suggerimenti di migrazione',body.migration_suggestions,item=>item.page+' · '+item.property+' · '+item.from+' → '+item.to+' · '+(item.deterministic?'Rinomina esatta da confermare':'Intervento manuale')+' · '+item.reason);
       details(result,'Testo libero da revisionare',body.manual_review,item=>item.page+' · '+item.property+' · '+item.names.join(', ')+' · '+item.reason);
       details(result,'Pagine interessate',body.impacted_pages,item=>item);
       details(result,'Archi interessati · sorgente → destinazione',body.impacted_edges,item=>item.page+' → '+item.property+' → '+item.target);
       details(result,'Riferimenti',body.references,item=>item.page+' · '+item.property+' → '+item.target);
       details(result,'Record condivisi',body.shared_records,item=>item);
       const usage=element('details',undefined,result);element('summary','Uso di tipi e proprietà, alias e fonti',usage);element('pre',JSON.stringify(body.usage,null,2),usage);
       if(status.capabilities.ontology_apply){
         const panel=element('section',undefined,result);element('h4','Applicazione manuale',panel);
         element('p','Modalità non protetta dagli editor esterni. Sospendi Obsidian, hook e altri scrittori prima di applicare; il lock del servizio non li esclude. Apply automatico disabilitato.',panel);
         const selected=[];
         for(const item of body.migration_suggestions.slice(0,200)){
           const row=element('div',undefined,panel),input=element('input',undefined,row);input.type='checkbox';input.id='migration-'+item.migration_id;input.disabled=!item.deterministic;input.dataset.applyControl='';
           const label=element('label',item.page+' · '+item.from+' → '+item.to+(item.deterministic?'':' · Solo manuale esterno'),row);label.htmlFor=input.id;
           input.addEventListener('change',()=>{const index=selected.indexOf(item.migration_id);if(input.checked&&index<0)selected.push(item.migration_id);else if(!input.checked&&index>=0)selected.splice(index,1);});
           if(item.diff){const note=element('details',undefined,panel);element('summary','Diff della nota · '+item.page,note);element('pre',plain(item.diff),note);}
         }
         const confirmations=[];
         for(const [id,text]of [['writers','Ho sospeso gli editor e gli hook esterni.'],['review','Ho revisionato diff schema/note, significato e testo libero.']]){
           const row=element('div',undefined,panel),input=element('input',undefined,row);input.type='checkbox';input.id='apply-'+id;input.dataset.applyControl='';
           const label=element('label',text,row);label.htmlFor=input.id;confirmations.push(input);
         }
         const button=element('button',draft.applyPending?'Recupera esito applicazione':'Applica manualmente la proposta',panel);button.type='button';button.id='ontology-apply';button.dataset.applyControl='';button.disabled=!draft.applyPending;
         const enabled=()=>{button.disabled=!draft.applyPending&&(obsolete||!confirmations.every(input=>input.checked)||!!body.shared_records.length);};
         for(const input of confirmations)input.addEventListener('change',enabled);
         button.addEventListener('click',async()=>{
           if(stopped()||button.disabled)return;
           if(!draft.applyPending)draft.applyPending={body:{preview_id:body.preview_id,proposal_hash:body.proposal_hash,selected_migrations:[...selected],idempotency_key:crypto.randomUUID(),mode:'manual_paused',external_writers_paused:true,semantic_reviewed:true},base:body.base_content_digest};
           button.disabled=true;message.textContent='Richiesta di applicazione manuale…';
           try{const job=await api('/api/v1/vaults/'+encodeURIComponent(vault)+'/ontology/apply',draft.applyPending.body,{'If-Match':'"'+draft.applyPending.base+'"'});draft.applyPending=null;
             if(!current())return;invalidated('Operazione '+job.operation_id+' avviata. Segui lo stato sopra la vista.');onOperation(vault,job.operation_id);
           }catch(error){if(!current())return;if(error.code){draft.applyPending=null;obsolete=true;}message.textContent=(error.code?error.code+': ':'Esito apply non confermato: ')+error.message+'. '+(draft.applyPending?'Recupera esito applicazione con la stessa richiesta.':'Correggi e genera una nuova preview.');
             if(error.details?.length)for(const item of error.details)element('p',item.page+' · '+item.property+' · '+item.reason,panel);
             button.textContent=draft.applyPending?'Recupera esito applicazione':'Applica manualmente la proposta';enabled();}
         });
       }
       obsolete=Date.now()>=body.expires_at*1000;
       if(obsolete){result.setAttribute('data-obsolete','true');message.textContent='Preview scaduta. Genera una nuova preview.';}
       clearTimeout(timer);if(!obsolete)timer=setTimeout(()=>{if(current()&&draft.result===body){obsolete=true;draft.pending=null;result.setAttribute('data-obsolete','true');for(const control of result.querySelectorAll('[data-apply-control]'))control.disabled=!draft.applyPending;message.textContent='Preview scaduta. Genera una nuova preview.';}},Math.max(0,body.expires_at*1000-Date.now()));
       if(focus)result.focus();
     }
     for(const input of Object.values(controls))input.addEventListener('input',()=>{draft.fields[input.name]=input.value;invalidated();fields();});
     adopt.addEventListener('change',()=>{draft.adopt=adopt.checked;invalidated();drawQueue();});
     form.addEventListener('submit',event=>{
       event.preventDefault();if(stopped())return;
       if(draft.patch.length+(draft.adopt?1:0)>=64){message.textContent='Limite di 64 modifiche. Rimuovi una modifica prima di aggiungerne altre.';return;}
       const f=draft.fields,item={op:f.action+'_'+f.category,name:f.name.trim()};
       if(f.action==='rename')item.to=f.to.trim();
       if(['add','update'].includes(f.action))item.value=f.category==='type'?{description:f.description,...(f.parent.trim()?{parent:f.parent.trim()}:{})}:{from_types:f.from_types.split(',').map(x=>x.trim()),to_types:f.to_types.split(',').map(x=>x.trim()),meaning:f.meaning,example:f.example,direction:'source_to_target'};
       draft.patch.push(item);invalidated('Modifica aggiunta. Genera la preview per verificarla.');drawQueue();preview.focus();
     });
     clear.addEventListener('click',()=>{if(draft.applyPending){message.textContent='Recupera prima l’esito dell’applicazione incerta.';return;}draft.patch=[];draft.adopt=false;adopt.checked=false;draft.result=null;invalidated('Proposta svuotata. Nessun file modificato.');result.replaceChildren();drawQueue();controls.name.focus();});
     rebase.addEventListener('click',async()=>{
       rebase.disabled=true;invalidated('Lettura della base corrente…');
       try{const fresh=await api('/api/v1/vaults/'+encodeURIComponent(vault)+'/status');if(!current())return;
         if(!fresh.capabilities.ontology_preview||!fresh.live_content_revision)throw new Error('Base non disponibile o vault non compatibile');
         draft.base=fresh.live_content_revision;status=fresh;baseLabel();message.textContent='Base aggiornata. Bozza conservata: genera e revisiona una nuova preview.';
       }catch(error){if(current())message.textContent='Base non aggiornata: '+error.message+'. Riprova con Aggiorna base corrente.';}
       finally{if(current())rebase.disabled=false;}
     });
     preview.addEventListener('click',async()=>{
       if(busy||stopped())return;
       const patch=[...(draft.adopt?[{op:'adopt_types'}]:[]),...draft.patch];if(!patch.length)return;
       if(patch.length>64){message.textContent='Limite di 64 modifiche, inclusa l’adozione.';return;}
       const signature=JSON.stringify({base_content_digest:draft.base,patch});
       if(!draft.pending||draft.pending.signature!==signature)draft.pending={signature,body:{base_content_digest:draft.base,idempotency_key:crypto.randomUUID(),patch:structuredClone(patch)}};
       const payload=draft.pending.body,version=draft.version;
       if(new TextEncoder().encode(JSON.stringify(payload)).length>16384){message.textContent='Proposta oltre 16 KiB. Riduci il numero o il testo delle modifiche.';return;}
       busy=true;preview.disabled=true;result.setAttribute('aria-busy','true');message.textContent='Analisi della proposta in corso…';
       try{
         const body=await api('/api/v1/vaults/'+encodeURIComponent(vault)+'/ontology/preview',payload);
         if(!current()||version!==draft.version)return;
         draft.pending=null;draft.result=body;obsolete=false;drawResult(body,true);message.textContent=obsolete?'Preview scaduta. Genera una nuova preview.':'Preview pronta. Revisiona diff e impatto prima di qualsiasi applicazione manuale.';
       }catch(error){
         if(!current()||version!==draft.version)return;
         if(error.code)draft.pending=null;obsolete=true;if(draft.result)result.setAttribute('data-obsolete','true');
         message.textContent=(error.code?error.code+': ':'Connessione non confermata: ')+error.message+(error.code==='preview_stale'||error.code==='blocked_external_change'?'. Aggiorna base corrente, poi genera una nuova preview.':'. Bozza conservata. Riprova Genera preview.');
         if(error.details?.length){const list=element('ul',undefined,result);for(const item of error.details)element('li',item.page+' · '+item.property+' · '+item.reason,list);}
       }finally{if(current()){busy=false;result.removeAttribute('aria-busy');drawQueue();}}
     });
     fields();baseLabel();drawQueue();
     if(draft.result){drawResult(draft.result);invalidated('Preview precedente conservata. Genera una nuova preview sulla base desiderata.');}
   }
   return {mount,reset};
 }
"""
