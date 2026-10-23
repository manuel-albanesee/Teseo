"""Controlli espliciti dei cicli: handoff, ricevute e applicazione revisionata."""
SKILL_SCRIPT = r"""
 function createSkillPanel({api,element,getEpoch,getVault,stopped,onOperation,reload}) {
   let status=null,pending=null;
   const root=()=>'/api/v1/vaults/'+encodeURIComponent(getVault());
   const current=(run,vault)=>run===getEpoch()&&vault===getVault()&&!stopped();
   function mount(value){
     status=value;const box=document.getElementById('skill-panel');box.replaceChildren();
     element('h3','Cicli ingest e lint',box);
     element('p','Prepara una copia isolata e un mandato da eseguire nella tua sessione client. Nessun modello viene avviato automaticamente. Il callback e gli hook Stop non certificano il successo.',box);
     if(value.compatibility!=='compatible'){element('p','Cicli non disponibili per questo formato. Il vault resta consultabile.',box);return;}
     const form=element('form',undefined,box),fields={};
     function field(id,label,tag='input'){const row=element('div',undefined,form),lab=element('label',label,row),input=element(tag,undefined,row);input.id='skill-'+id;lab.htmlFor=input.id;fields[id]=input;return input;}
     const kind=field('kind','Ciclo','select');for(const [id,label]of [['ingest_lint','Ingest seguito da lint'],['lint','Solo lint'],['fill_gaps','Lacune con dialogo utente']])kind.append(new Option(label,id));
     const adapter=field('adapter','Client della sessione','select');for(const name of ['codex','claude','copilot'])adapter.append(new Option(name,name));
     const inputs=field('inputs','Fonti raw già presenti · un percorso relativo per riga','textarea');inputs.rows=2;inputs.placeholder='raw/fonte.txt';
     kind.addEventListener('change',()=>{inputs.disabled=kind.value!=='ingest_lint';});
     const scope=field('scope','Perimetro delle modifiche · un percorso relativo per riga','textarea');scope.rows=4;scope.value='wiki/\nWiki reference.md\nindex.md\nlog.md';
     const start=element('button','Prepara ciclo e handoff',form);start.type='submit';start.id='skill-start';
     const probe=element('button','Verifica versioni client',box);probe.type='button';probe.id='skill-probe';
     const message=element('p','Nessun nuovo ciclo richiesto.',box);message.id='skill-status';message.setAttribute('role','status');message.setAttribute('aria-live','polite');
     const result=element('div',undefined,box);
     probe.addEventListener('click',async()=>{const run=getEpoch(),vault=getVault();probe.disabled=true;message.textContent='Rilevamento versioni…';
       try{const data=await api(root()+'/probe-adapters',{});if(current(run,vault)){result.replaceChildren();element('pre',JSON.stringify(data.adapters,null,2),result);message.textContent='Versioni rilevate. Avvio automatico, isolamento e callback nativi restano non verificati; usa l’handoff manuale.';}}
       catch(error){if(current(run,vault))message.textContent=error.code+': '+error.message;}finally{if(current(run,vault))probe.disabled=false;}});
     form.addEventListener('submit',async event=>{event.preventDefault();if(stopped()||start.disabled)return;const run=getEpoch(),vault=getVault();
       const lines=input=>input.value.split(/\r?\n/).map(x=>x.trim()).filter(Boolean);
       if(!pending||pending.vault!==vault)pending={vault,body:{kind:kind.value,adapter:adapter.value,inputs:kind.value==='ingest_lint'?lines(inputs):[],scope:lines(scope),base_content_digest:status.live_content_revision,idempotency_key:crypto.randomUUID()}};
       start.disabled=true;message.textContent='Preparazione della copia isolata…';
       const sent=pending;
       try{const job=await api(root()+'/operations',sent.body);if(pending===sent)pending=null;if(!current(run,vault))return;result.replaceChildren();render(job,result);message.textContent='Ciclo '+job.operation_id+' · '+job.state+'. Segui le fasi nel registro operazioni.';}
       catch(error){if(!current(run,vault))return;if(error.code&&pending===sent)pending=null;message.textContent=(error.code||'Esito incerto')+': '+error.message+(pending?' · Riprova per recuperare lo stesso ciclo.':' · Aggiorna la base prima di riprovare.');}
       finally{if(current(run,vault))start.disabled=false;}});
   }
   function render(job,section){
     if(!['ingest_lint','lint','fill_gaps'].includes(job.kind))return;
     const vault=getVault(),run=getEpoch(),path=root()+'/operations/'+encodeURIComponent(job.operation_id);
     element('p','Ingest: '+job.phases?.ingest+' · Lint: '+job.phases?.lint+' · Pubblicabile: '+(job.publication_eligible?'sì, checkpoint validato':'no'),section);
     if(job.handoff){const details=element('details',undefined,section);element('summary','Mandato e copia isolata · '+job.phase,details);element('pre',job.handoff.prompt||'',details);element('p',job.handoff.workspace,details);element('pre',job.handoff.completion_command||'',details);
       element('p','Per chiedere dialogo usa --outcome awaiting_user --reason "motivo". Per dichiarare fallimento usa --outcome failed. La ricevuta non contiene un giudizio semantico del servizio.',details);}
     async function action(suffix,body,headers){const buttons=[...section.querySelectorAll('button')];buttons.forEach(b=>b.disabled=true);try{const value=await api(path+'/'+suffix,body,headers||{});if(!current(run,vault))return;notice.textContent='Operazione '+value.operation_id+' · '+value.state;if(suffix==='apply'||suffix==='recover')onOperation(vault,value.operation_id);else{section.replaceChildren();element('p',value.operation_id+' · '+value.state,section);render(value,section);reload();}}
       catch(error){if(current(run,vault)){notice.textContent=error.code+': '+error.message;buttons.forEach(b=>b.disabled=false);}}}
     const notice=element('p','',section);notice.setAttribute('role','status');
     const button=(text,handler)=>{const control=element('button',text,section);control.type='button';control.addEventListener('click',handler);return control;};
     if(job.state==='awaiting_client'){
       const row=element('div',undefined,section),input=element('input',undefined,row);input.type='file';input.accept='.json,application/json';input.id='receipt-'+job.operation_id;
       const label=element('label','Ricevuta JSON locale · contiene una capacità riservata',row);label.htmlFor=input.id;
       button('Verifica ricevuta',async()=>{const file=input.files[0];if(!file||file.size>240*1024){notice.textContent='Seleziona una ricevuta JSON fino a 240 KiB.';return;}
         try{const receipt=JSON.parse(await file.text());if(current(run,vault))await action('complete',{receipt});}catch(error){notice.textContent='Ricevuta JSON non valida: '+error.message;}});
     }
     if(job.state==='awaiting_user'){button('Conferma continuazione dopo il dialogo',()=>action('resume',{decision:'continue'}));button('Rifiuta e cancella ciclo',()=>action('resume',{decision:'refuse'}));}
     if(job.validation){const details=element('details',undefined,section);element('summary','Manifest, perimetro e diff completi del candidato',details);element('pre',JSON.stringify(job.validation,null,2),details);}
     if(['prepared','recovery_required'].includes(job.state)){
       element('p','Apply/recovery manuale: sospendi editor e hook, revisiona il diff completo e i backup. Nessuna esclusione garantita degli scrittori esterni.',section);
       const input=element('input',undefined,section);input.type='checkbox';input.id='skill-review-'+job.operation_id;
       const label=element('label','Ho sospeso gli scrittori esterni e revisionato significato, diff e stato dei file.',section);label.htmlFor=input.id;
       const confirm=(suffix,body,base)=>{if(!input.checked){notice.textContent='Conferma prima sospensione e revisione.';return;}action(suffix,{...body,mode:'manual_paused',external_writers_paused:true,semantic_reviewed:true},{'If-Match':'"'+base+'"'});};
       if(job.state==='prepared')button('Applica candidato revisionato',()=>confirm('apply',{},job.base_content_digest));
       else for(const [name,label]of [['finish','Completa candidato'],['rollback','Ripristina base']])button(label,async()=>{try{const latest=await api(root()+'/operations');if(current(run,vault))confirm('recover',{action:name},latest.live_content_revision);}catch(error){notice.textContent=error.message;}});
     }
     if(['queued','awaiting_client','awaiting_user','prepared'].includes(job.state)||(job.state==='recovery_required'&&!job.checkpoint))button('Cancella ciclo · conserva output',()=>action('cancel',{}));
   }
   return {mount,render,reset:()=>document.getElementById('skill-panel').replaceChildren()};
 }
"""
