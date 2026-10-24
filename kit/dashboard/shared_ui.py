"""Risposte condivise: consenso esplicito, causalità e preview privacy."""
SHARED_SCRIPT = r"""
 function createSharedPanel({api,element,getEpoch,getVault,stopped,reload}) {
   let generation=0;
   function reset(){++generation;document.getElementById('shared-panel').replaceChildren();}
   function mount(status){
     reset();const box=document.getElementById('shared-panel'),run=getEpoch(),vault=getVault(),version=generation;
     const current=()=>version===generation&&run===getEpoch()&&vault===getVault()&&!stopped();
     const path='/api/v1/vaults/'+encodeURIComponent(vault);
     const bounded=(value,limit=24000)=>{const text=typeof value==='string'?value:JSON.stringify(value,null,2);return (text||'').slice(0,limit)+((text||'').length>limit?'\n… contenuto visualizzato troncato':'');};
     const json=(parent,value)=>element('pre',bounded(value),parent);
     element('h3','Risposte e decisioni condivise',box);
     element('p','Le risposte condivise attraversano i clone. Non inserire dati personali o riservati senza averne concordato la diffusione. I dati già copiati nei DB o nella storia Git non vengono cancellati da questa selezione.',box).className='ontology-direction';
     if(status.compatibility!=='compatible'){element('p','Questo formato resta consultabile: creazione, import ed export condivisi richiedono un manifest compatibile. Nessuna lettura dei DB personali.',box);return;}
     const message=element('p','Lettura dello stato condiviso…',box);message.id='shared-message';message.setAttribute('role','status');message.setAttribute('aria-live','polite');
     const controls=element('div',undefined,box);controls.className='editor-actions';
     const button=(parent,id,title,handler)=>{const b=element('button',title,parent);b.type='button';b.id=id;b.addEventListener('click',handler);return b;};
     const check=(parent,id,title)=>{const row=element('div',undefined,parent),input=element('input',undefined,row);input.type='checkbox';input.id=id;input.style.width='24px';input.style.minHeight='44px';input.style.verticalAlign='middle';const label=element('label',title,row);label.htmlFor=id;label.style.display='inline';return input;};
     const field=(parent,id,title,tag='input',limit=4096)=>{const row=element('div',undefined,parent),label=element('label',title,row),input=element(tag,undefined,row);label.htmlFor=id;input.id=id;input.maxLength=limit;return input;};
     let busy=false,preview=null,answerPending=null,exportPending=null,decisionPending=new Map();
     const mutable=[];
     function refreshDisabled(){for(const control of mutable)control.disabled=busy||(control._sharedConsent&&!control._sharedConsent.checked);for(const input of [question,questionText,pages,text])input.disabled=busy||!!answerPending;questionText.disabled=busy||!!answerPending||!!question.value;previewButton.disabled=busy||!!exportPending;for(const input of previewView.querySelectorAll('input[data-selection]'))input.disabled=busy||!!exportPending;answerButton.disabled=busy||!answerConsent.checked;exportButton.disabled=busy||!preview||!exportConsent.checked||!selected().length;}
     async function request(label,work){if(busy||!current())return;busy=true;refreshDisabled();message.textContent=label;
       try{await work();}catch(error){if(current())message.textContent=(error.code||'Esito incerto')+': '+error.message+(error.code?' · Aggiorna lo stato prima di una nuova azione.':' · Riprova per recuperare la stessa richiesta; non creare un duplicato.');}
       finally{if(current()){busy=false;refreshDisabled();}}}
     const readButton=button(controls,'shared-refresh','Aggiorna stato',()=>request('Lettura dello stato condiviso…',read));mutable.push(readButton);
     const importButton=button(controls,'shared-import','Ricostruisci proiezione locale',()=>request('Validazione e import degli eventi condivisi…',async()=>{const value=await api(path+'/shared-state/import',{});if(!current())return;message.textContent='Proiezione locale aggiornata. Nessun push eseguito.';json(last,value);await read(false);}));mutable.push(importButton);
     const stateView=element('section',undefined,box);stateView.id='shared-state';stateView.setAttribute('aria-label','Stato delle risposte e conflitti');
     const answerSection=element('section',undefined,box);element('h4','Registra una risposta',answerSection);
     const form=element('form',undefined,answerSection);form.id='shared-answer-form';
     const question=field(form,'shared-question','Domanda condivisa','select');question.append(new Option('Nuova domanda',''));mutable.push(question);
     const questionText=field(form,'shared-question-text','Testo della nuova domanda','textarea');questionText.rows=2;mutable.push(questionText);
     const pages=field(form,'shared-pages','ID delle pagine di riferimento · uno per riga','textarea');pages.rows=2;mutable.push(pages);
     const text=field(form,'shared-answer-text','Risposta da condividere','textarea',16000);text.required=true;text.rows=4;mutable.push(text);
     const answerConsent=check(form,'shared-answer-consent','Confermo che domanda, risposta e riferimenti selezionati sono condivisibili con il gruppo.');mutable.push(answerConsent);
     const answerButton=element('button','Registra risposta condivisa',form);answerButton.id='shared-answer-save';answerButton.type='submit';answerButton.disabled=true;
     question.addEventListener('change',()=>{questionText.disabled=!!question.value;questionText.required=!question.value;});questionText.required=true;
     answerConsent.addEventListener('change',refreshDisabled);
     form.addEventListener('submit',event=>{event.preventDefault();if(!answerConsent.checked||busy)return;
       request('Registrazione della risposta condivisa…',async()=>{
         if(!answerPending)answerPending={question_id:question.value||null,question_text:question.value?'':questionText.value.trim(),pages:pages.value.split(/\r?\n/).map(v=>v.trim()).filter(Boolean),text:text.value.trim(),share_confirmed:true,idempotency_key:crypto.randomUUID()};
         const sent=answerPending;
         try{const value=await api(path+'/answers',sent);if(!current())return;answerPending=null;last.replaceChildren();json(last,value);text.value='';answerConsent.checked=false;message.textContent='Risposta registrata nello stato condiviso. Applicazione alle note e pubblicazione sono stati separati.';await read(false);}
         catch(error){if(error.code)answerPending=null;throw error;}
       });});
     for(const input of [question,questionText,pages,text])input.addEventListener('input',()=>{if(answerPending){message.textContent='Esito precedente incerto: riprova la richiesta originale prima di modificare la risposta.';}});
     const exportSection=element('section',undefined,box);element('h4','Migrazione legacy selettiva',exportSection);
     element('p','La preview legge un backup consistente dell’archivio locale di domande e risposte. Nessun export automatico: sono condivise solo le righe selezionate dopo revisione. Telemetria, turni e memoria personale restano locali.',exportSection);
     const previewButton=button(exportSection,'shared-export-preview','Mostra preview e campi legacy',()=>request('Preparazione della preview privacy…',async()=>{const value=await api(path+'/shared-state/export-preview',{});if(!current())return;preview=value;exportPending=null;exportConsent.checked=false;drawPreview(value);message.textContent='Preview pronta. Nessuna riga selezionata e nessun evento esportato.';}));mutable.push(previewButton);
     const previewView=element('div',undefined,exportSection);previewView.id='shared-export-rows';
     const exportConsent=check(exportSection,'shared-export-consent','Ho revisionato i campi e autorizzo la condivisione delle sole righe selezionate.');mutable.push(exportConsent);exportConsent.addEventListener('change',refreshDisabled);
     const selected=()=>[...previewView.querySelectorAll('input[data-selection]:checked')].map(input=>input.dataset.selection);
     const exportButton=button(exportSection,'shared-export-save','Esporta righe selezionate',()=>{if(!exportConsent.checked||!selected().length)return;request('Export delle sole righe selezionate…',async()=>{
       if(!exportPending)exportPending={preview_id:preview.preview_id,selection_ids:selected(),share_confirmed:true,idempotency_key:crypto.randomUUID()};
       try{const value=await api(path+'/shared-state/export',exportPending);if(!current())return;exportPending=null;preview=null;previewView.replaceChildren();exportConsent.checked=false;last.replaceChildren();json(last,value);message.textContent='Export selettivo registrato. DB originali conservati; pubblicazione non verificata.';await read(false);}catch(error){if(error.code)exportPending=null;throw error;}
     });});
     const last=element('section',undefined,box);last.id='shared-last-result';last.setAttribute('aria-label','Ultimo esito esplicito');
     function drawPreview(value){previewView.replaceChildren();const rows=Array.isArray(value.rows)?value.rows:[];
       if(value.copied_source_warning)element('p','Provenienza storica del DB non certificata: copie già distribuite possono produrre identità distinte. Revisiona eventuali duplicati; nessuna deduplica automatica.',previewView);
       if(value.backup_manifest_path)element('p','Manifest del backup locale: '+bounded(value.backup_manifest_path,500),previewView);
       if(!rows.length)element('p','Nessuna riga legacy esportabile.',previewView);
       for(const [index,row] of rows.slice(0,200).entries()){
         const detail=element('details',undefined,previewView);element('summary',bounded(row.table,80)+' · riga '+bounded(row.row_id,80)+(row.shareable?' · selezionabile':' · esclusa'),detail);json(detail,row.fields);
         if(JSON.stringify(row.fields||{}).length>24000){element('p','Riga troppo lunga per la revisione completa nella UI: consulta il backup e prepara una selezione più piccola. Condivisione disabilitata per questa riga.',detail);continue;}
         if(row.shareable&&typeof row.selection_id==='string'){const input=check(detail,'shared-row-'+index,'Condividi questa riga dopo aver revisionato i campi');input.dataset.selection=row.selection_id;input.addEventListener('change',refreshDisabled);mutable.push(input);}
       }
       if(rows.length>200)element('p','Visualizzate le prime 200 righe. Non sono selezionate le righe restanti.',previewView);
       if(value.exclusions){element('h4','Campi e record esclusi',previewView);json(previewView,value.exclusions);}
     }
     function decisionForm(conflict,index,parent){
       const id=conflict.question_id,heads=Array.isArray(conflict.heads)?conflict.heads:[];
       if(!id||!heads.length){element('p','Identità o teste causali mancanti: nessuna decisione automatica. Rileggi lo stato dopo aver acquisito gli eventi mancanti.',parent);return;}
       const decision=field(parent,'shared-decision-'+index,'Nuova decisione causale','select');for(const [value,title]of [['open','Aperta'],['reopen','Riaperta'],['defer','Rinvio condiviso'],['closed','Chiusa'],['accepted','Accettata'],['rejected','Rifiutata']])decision.append(new Option(title,value));mutable.push(decision);
       const reason=field(parent,'shared-reason-'+index,'Motivo della decisione','textarea');mutable.push(reason);
       const consent=check(parent,'shared-decision-consent-'+index,'Confermo che decisione e motivo possono essere condivisi.');mutable.push(consent);
       const save=button(parent,'shared-decision-save-'+index,'Registra decisione sulle teste mostrate',()=>{if(!consent.checked||!reason.value.trim()){message.textContent='Inserisci il motivo e conferma la condivisione.';return;}request('Registrazione della decisione causale…',async()=>{
         if(!decisionPending.has(id))decisionPending.set(id,{question_id:id,heads:[...heads],decision:decision.value,reason:reason.value.trim(),share_confirmed:true,idempotency_key:crypto.randomUUID()});
         try{const value=await api(path+'/shared-state/decision',decisionPending.get(id));if(!current())return;decisionPending.delete(id);last.replaceChildren();json(last,value);message.textContent='Decisione registrata sulle teste osservate. Nuovi eventi concorrenti richiedono una nuova revisione.';await read(false);}catch(error){if(error.code)decisionPending.delete(id);throw error;}
       });});save._sharedConsent=consent;save.disabled=true;consent.addEventListener('change',()=>save.disabled=busy||!consent.checked);mutable.push(save);
     }
     async function read(showMessage=true){const value=await api(path+'/answers');if(!current())return;stateView.replaceChildren();
       element('h4','Risposte registrate',stateView);const answers=Array.isArray(value.answers)?value.answers:[];
       if(!answers.length)element('p','Nessuna risposta condivisa registrata. La memoria personale non è consultata.',stateView);
       for(const answer of answers.slice(0,200)){const detail=element('details',undefined,stateView);element('summary',bounded(answer.entity_id||answer.answer_id,100)+' · '+bounded(answer.state||'archived',60),detail);
         const publication=answer.publication==='published'&&typeof answer.published_oid==='string'?'sì, OID '+bounded(answer.published_oid,128)+' · attestazione del journal locale':'non verificata';
         element('p','Registrata: sì · Applicata alle note: '+(answer.applied===true?'sì, checkpoint verificato':answer.applied===null?'storica, da verificare':'non attestata')+' · Pubblicata: '+publication+'.',detail);json(detail,answer);}
       if(answers.length>200)element('p','Visualizzate le prime 200 risposte.',stateView);
       const previous=question.value;question.replaceChildren(new Option('Nuova domanda',''));for(const item of (value.questions||[]).slice(0,200)){if(item.question_id)question.append(new Option(bounded(item.text||item.question_text||item.question_id,200),item.question_id));}if([...question.options].some(option=>option.value===previous))question.value=previous;
       questionText.disabled=!!question.value;questionText.required=!question.value;
       const requiredHeads=q=>[...new Set([...(q.heads||[]),...(value.conflicts||[]).filter(c=>c.entity_id===q.question_id).flatMap(c=>c.heads||[])])];
       element('h4','Domande e rinvii',stateView);
       (value.questions||[]).slice(0,100).forEach((q,index)=>{const detail=element('details',undefined,stateView);element('summary',bounded(q.text,180)+' · '+q.state+' · rinvii '+q.defer_count,detail);json(detail,q);decisionForm({question_id:q.question_id,heads:requiredHeads(q)},1000+index,detail);});
       element('h4','Conflitti e parent mancanti',stateView);const conflicts=Array.isArray(value.conflicts)?value.conflicts:[];
       if(!conflicts.length)element('p','Nessun conflitto causale rilevato.',stateView);
       conflicts.slice(0,100).forEach((conflict,index)=>{const section=element('section',undefined,stateView);json(section,conflict);
         const id=conflict.question_id||(value.questions||[]).find(q=>q.question_id===conflict.entity_id)?.question_id||answers.find(a=>a.entity_id===conflict.entity_id)?.question_id;
         const q=(value.questions||[]).find(q=>q.question_id===id),heads=q?requiredHeads(q):[];
         if(conflict.kind==='answer.state')element('p','Accetta la revisione causale, poi esegui un nuovo lint sugli UUID interessati per attestare le note risolte.',section);
         decisionForm({...conflict,question_id:id,heads},index,section);});
       if(value.pending&&(!Array.isArray(value.pending)||value.pending.length)){element('p','Eventi pending: acquisisci i parent mancanti prima di considerarli applicati.',stateView);json(stateView,value.pending);}
       element('p','La pubblicazione è attestata per risposta dal journal locale quando disponibile; negli altri clone resta da verificare. L’import aggiorna la proiezione locale e non esegue un push.',stateView).className='hint';
       if(showMessage)message.textContent='Stato condiviso aggiornato.';
     }
     refreshDisabled();request('Lettura dello stato condiviso…',read);
   }
   return {mount,reset};
 }
"""
