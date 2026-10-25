"""Publisher dati: preview esplicita, nessuna credenziale nel browser."""
SYNC_SCRIPT = r"""
 function createSyncPanel({api,element,getEpoch,getVault,stopped}) {
   let generation=0;
   function reset(){++generation;document.getElementById('sync-panel').replaceChildren();}
   function mount(vaultStatus){
     reset();const box=document.getElementById('sync-panel'),run=getEpoch(),vault=getVault(),version=generation;
     const current=()=>version===generation&&run===getEpoch()&&vault===getVault()&&!stopped();
     const path='/api/v1/vaults/'+encodeURIComponent(vault)+'/sync';
     let busy=false,snapshot=null,preview=null,pending=null;
     const mutable=[];
     const bounded=value=>{const text=typeof value==='string'?value:JSON.stringify(value,null,2);return (text||'').slice(0,32000)+((text||'').length>32000?'\n… visualizzazione troncata; non confermare senza revisione completa.':'');};
     const previewComplete=()=>preview&&JSON.stringify(preview,null,2).length<=32000;
     const receiverPreviewComplete=data=>!!data?.preview&&!data.preview.truncated&&data.preview.complete!==false&&JSON.stringify(data.preview.files||[],null,2).length<=32000&&(data.preview.diff||'').length<=32000;
     const json=(parent,value)=>element('pre',bounded(value),parent);
     const button=(parent,id,title,handler)=>{const input=element('button',title,parent);input.id=id;input.type='button';input.addEventListener('click',handler);mutable.push(input);return input;};
     const field=(parent,id,title,tag='input')=>{const row=element('div',undefined,parent),label=element('label',title,row),input=element(tag,undefined,row);input.id=id;label.htmlFor=id;input.maxLength=4096;mutable.push(input);return input;};
     const check=(parent,id,title)=>{const row=element('div',undefined,parent),input=element('input',undefined,row);input.type='checkbox';input.id=id;input.style.width='24px';input.style.minHeight='44px';input.style.verticalAlign='middle';const label=element('label',title,row);label.htmlFor=id;label.style.display='inline';mutable.push(input);return input;};
     element('h3','Pubblicazione Git dei dati',box);
     element('p','Revisiona la selezione prima di pubblicare. Git e gh usano le credenziali locali: non inserire token o password qui. Visibilità del repository, autore dei commit e permesso di push sono verifiche distinte.',box).className='ontology-direction';
     const message=element('p','Lettura dello stato Git…',box);message.id='sync-message';message.setAttribute('role','status');message.setAttribute('aria-live','polite');
     const actions=element('div',undefined,box);actions.className='editor-actions';
     button(actions,'sync-refresh','Aggiorna stato Git',()=>request('Lettura dello stato Git…',()=>read()));
     const view=element('section',undefined,box);view.id='sync-state';view.setAttribute('aria-label','Checkpoint e stato della pubblicazione');
     const receiverView=element('section',undefined,box);receiverView.id='receiver-state';receiverView.setAttribute('aria-label','Novità remote e candidato da ricevere');
     if(vaultStatus.compatibility!=='compatible'){message.textContent='Vault consultabile in sola lettura. La pubblicazione richiede un manifest compatibile.';request('Lettura dello stato Git…',()=>read());return;}
     const config=element('details',undefined,box);element('summary','Collega o inizializza il repository dati',config);
     const remote=field(config,'sync-remote','Remote Git già configurato');remote.value='origin';remote.readOnly=true;
     const branch=field(config,'sync-branch','Branch condiviso scelto');branch.placeholder='Branch dati del gruppo';
     const visibility=field(config,'sync-visibility','Visibilità confermata del repository','select');visibility.append(new Option('Scegli la visibilità',''),new Option('Privato','private'),new Option('Pubblico','public'));
     const mode=field(config,'sync-mode','Policy di pubblicazione','select');mode.append(new Option('Push diretto sul branch scelto','direct'),new Option('Richiedi approvazione tramite PR','pr'));
     element('p','La modalità PR pubblica un branch proposto e attende approvazione. Il link di confronto serve per creare la PR su GitHub: la dashboard non la crea e non esegue il merge.',config).className='hint';
     const raw=field(config,'sync-raw','Nuove fonti raw selezionate · un percorso relativo per riga','textarea');raw.rows=3;raw.placeholder='raw/fonte-condivisibile.md';
     const selectedRaw=()=>raw.value.split(/\r?\n/).map(x=>x.trim()).filter(Boolean);
     const previewButton=button(config,'sync-preview','Controlla selezione e privacy',()=>request('Analisi della allowlist e dei file tracked…',async()=>{preview=null;consent.checked=false;initializeConsent.checked=false;const value=await api(path+'/preview',{raw_paths:selectedRaw()});if(!current())return;preview=value;previewView.replaceChildren();json(previewView,preview);message.textContent='Preview pronta. Revisiona inclusioni, esclusioni e file già tracked prima di confermare.';}));
     const previewView=element('section',undefined,config);previewView.id='sync-preview-result';previewView.setAttribute('aria-label','Preview della selezione dati');
     element('p','La preview verifica esattamente le fonti selezionate. Ogni modifica della selezione richiede una nuova preview e un nuovo consenso.',config).className='hint';
     const consent=check(config,'sync-consent','Ho revisionato visibilità, branch, file selezionati e privacy; autorizzo questa selezione per la configurazione o la pubblicazione richiesta.');
     const configure=button(config,'sync-configure','Conferma configurazione',()=>request('Validazione della configurazione e della selezione…',async()=>{if(!consent.checked||!preview||!visibility.value||!branch.value.trim())throw new Error('Completa la scelta e la preview, poi conferma il consenso.');const result=await api(path+'/configure',{remote:'origin',branch:branch.value.trim(),visibility:visibility.value,mode:mode.value,raw_paths:raw.value.split(/\r?\n/).map(x=>x.trim()).filter(Boolean),share_confirmed:true,expected_head:head()});if(!current())return;resultView.replaceChildren();json(resultView,result);consent.checked=false;preview=null;message.textContent='Configurazione registrata. Rileggi la preview prima della pubblicazione.';await read(false);}));
     const onboarding=element('details',undefined,config);element('summary','Vault senza Git · crea il checkpoint locale iniziale',onboarding);
     element('p','Il repository remoto deve già esistere su GitHub: indica proprietario e repository nell’URL. Questa azione inizializza Git e il primo commit selettivo sul vault locale; non crea repository su GitHub e non esegue push. I file esclusi restano nel vault e possono richiedere pulizia esplicita prima della configurazione.',onboarding).className='hint';
     const remoteUrl=field(onboarding,'sync-remote-url','URL GitHub del repository dati esistente');remoteUrl.placeholder='https://github.com/proprietario/repository.git';
     const authorName=field(onboarding,'sync-author-name','Nome autore dei commit Git locali');authorName.maxLength=256;
     const authorEmail=field(onboarding,'sync-author-email','Email autore dei commit Git locali');authorEmail.type='email';authorEmail.maxLength=256;
     const initializeConsent=check(onboarding,'sync-initialize-consent','Ho revisionato tutti i percorsi e hash della preview; autorizzo Git e il commit iniziale locale con queste fonti, branch e identità autore.');
     const initialize=button(onboarding,'sync-initialize','Inizializza Git con la selezione revisionata',()=>request('Creazione del checkpoint Git iniziale locale…',async()=>{
       if(!initializeConsent.checked||!previewComplete()||!Array.isArray(preview.files))throw new Error('Revisiona una preview completa prima di inizializzare.');
       const expected=Object.fromEntries(preview.files.map(item=>[item.path,item.sha256]));
       const result=await api(path+'/initialize',{branch:branch.value.trim(),remote_url:remoteUrl.value.trim(),raw_paths:selectedRaw(),author:{name:authorName.value.trim(),email:authorEmail.value.trim()},share_confirmed:true,expected_files:expected});
       if(!current())return;resultView.replaceChildren();json(resultView,result);preview=null;initializeConsent.checked=false;consent.checked=false;message.textContent='Checkpoint iniziale locale creato. Nessun push eseguito. Revisiona i file esclusi e la configurazione prima di pubblicare.';await read(false);
     }));
     initializeConsent.addEventListener('change',refresh);
     for(const input of [remoteUrl,authorName,authorEmail])input.addEventListener('input',()=>{initializeConsent.checked=false;refresh();});
     for(const input of [branch,visibility,mode,raw])input.addEventListener('input',()=>{preview=null;consent.checked=false;initializeConsent.checked=false;refresh();});
     consent.addEventListener('change',refresh);
     const publication=element('section',undefined,box);element('h4','Pubblica un checkpoint validato',publication);
     const operation=field(publication,'sync-operation','UUID dell’operazione ingest/lint completata');operation.maxLength=36;
     element('p','La pubblicazione conserva il checkpoint locale se rete, autenticazione o policy bloccano il push. Prima di proseguire sospendi editor e hook che scrivono nel vault.',publication).className='hint';
     const exclusive=check(publication,'sync-exclusive','Ho sospeso gli scrittori esterni e autorizzo la pubblicazione del checkpoint e l’adozione locale del candidato validato.');
     const decisionKey=field(publication,'sync-decision-key','Chiave di riconciliazione semantica · solo dopo revisione del perimetro mostrato');decisionKey.maxLength=128;
     const semantic=check(publication,'sync-semantic','Ho revisionato le note e fonti correlate del candidato e confermo la decisione associata alla chiave indicata.');
     const resolutionDigest=field(publication,'sync-resolution-digest','SHA-256 del candidato risolto · restituito dal comando locale di revisione');resolutionDigest.maxLength=64;
     const resolutionConsent=check(publication,'sync-resolution-consent','Ho revisionato il candidato isolato risolto e confermo il digest indicato. Nessun file viene caricato dalla dashboard.');
     const publish=button(publication,'sync-publish','Pubblica operazione validata',()=>mutate('publish'));
     const resolve=button(publication,'sync-resolve','Riprendi candidato salvato',()=>mutate('resolve'));
     element('p','Riprendi usa il candidato già registrato nel journal. Conflitti sui contenuti richiedono una revisione esplicita; non vengono caricati file arbitrari.',publication).className='hint';
     const resultView=element('section',undefined,box);resultView.id='sync-result';resultView.setAttribute('aria-label','Esito della richiesta di pubblicazione');
     const receiverSection=element('section',undefined,box);receiverSection.id='receiver-controls';element('h3','Ricevi aggiornamenti dal gruppo',receiverSection);
     element('p','Il servizio può rilevare novità anche con questa scheda chiusa. Il rilevamento prepara un candidato isolato; applicarlo al vault richiede una conferma manuale.',receiverSection).className='ontology-direction';
     const receiverConsent=check(receiverSection,'receiver-consent','Autorizzo il controllo periodico del branch dati configurato. Nessuna applicazione automatica al vault.');
     const receiverActions=element('div',undefined,receiverSection);receiverActions.className='editor-actions';
     const receiverCheck=button(receiverActions,'receiver-check','Controlla novità ora',()=>receiverAction('check',{}));
     const receiverResume=button(receiverActions,'receiver-resume','Attiva rilevamento · ogni 60 secondi',()=>receiverAction('resume',{interval_seconds:60}));
     const receiverPause=button(receiverActions,'receiver-pause','Sospendi rilevamento',()=>receiverAction('pause',{}));
     element('p','Prima di adottare il candidato sospendi Obsidian, editor e hook che scrivono nel vault. Aggiorna lo stato e revisiona OID, digest, conflitti e validazione qui sopra.',receiverSection).className='hint';
     const receiverExclusive=check(receiverSection,'receiver-exclusive','Ho sospeso gli scrittori esterni e revisionato il candidato mostrato; autorizzo questa adozione manuale.');
     const receiveActions=element('div',undefined,receiverSection);receiveActions.className='editor-actions';
     const receive=button(receiveActions,'receiver-receive','Valida e applica candidato',()=>receiveCandidate());
     const finish=button(receiveActions,'receiver-finish','Completa ripristino interrotto',()=>receiveCandidate('finish'));
     const rollback=button(receiveActions,'receiver-rollback','Ripristina checkpoint precedente',()=>receiveCandidate('rollback'));
     receiverConsent.addEventListener('change',refresh);receiverExclusive.addEventListener('change',refresh);
     async function receiverAction(action,body){
       if(action==='resume'&&!receiverConsent.checked)return;
       return request(action==='check'?'Controllo remoto e preparazione isolata…':'Aggiornamento del rilevamento remoto…',async()=>{const result=await api(path+'/'+action,body);if(!current())return;resultView.replaceChildren();json(resultView,result);receiverExclusive.checked=false;message.textContent='Stato del rilevamento registrato. Il vault richiede un’adozione manuale separata.';await read(false);});
     }
     async function receiveCandidate(action){
       const receiver=snapshot?.receiver;if(!receiverExclusive.checked||!receiver)return;
       const transaction=snapshot?.receive_transaction;
       const body={exclusive_confirmed:true,expected_head:action?transaction?.B:receiver.base_head,pending_oid:action?transaction?.R:receiver.pending_oid,expected_digest:action?transaction?.candidate_digest:receiver.candidate_digest,...(action?{action}:{})};
       return request(action?'Ripristino del checkpoint in corso…':'Validazione e adozione manuale del candidato…',async()=>{receiverExclusive.checked=false;const result=await api(path+(action?'/receive-recover':'/receive'),body);if(!current())return;resultView.replaceChildren();json(resultView,result);receiverExclusive.checked=false;message.textContent='Esito ricezione registrato. Aggiorna il vault per consultare la generazione applicata.';await read(false);});
     }
     function renderReceiver(value){
       receiverView.replaceChildren();element('h3','Rilevamento remoto',receiverView);const data=value.receiver;
       if(!data){element('p','Stato del rilevamento non disponibile. Aggiorna lo stato Git.',receiverView);return;}
       element('p','Ricezione: '+bounded(data.state||'non configurato')+(data.paused?' · sospesa':''),receiverView);
       const labels=[['last_seen_remote_oid','Ultima revisione remota vista'],['last_applied_oid','Ultima revisione applicata'],['pending_oid','Novità in attesa'],['last_fetch_at','Ultimo controllo'],['next_check_at','Prossimo controllo'],['base_head','HEAD alla preparazione'],['candidate_digest','Digest del candidato']];
       const fields=element('dl',undefined,receiverView);for(const[key,label]of labels){element('dt',label,fields);element('dd',bounded(data[key]??'non disponibile'),fields);}
       if(data.error)element('p','Controllo non completato: '+bounded(data.error)+'. Conserva il candidato; riprova dopo aver risolto rete, autenticazione o conflitto.',receiverView).className='ontology-direction';
       if(data.backoff)element('p','Attesa dopo errore: '+bounded(data.backoff),receiverView).className='hint';
       if(data.update_event)element('p','Vault aggiornato. Usa “Aggiorna” per rileggere grafo e generazione corrente.',receiverView).className='ontology-direction';
       if(data.pending_oid&&data.candidate_digest)element('p','Il candidato è isolato: le viste del vault restano sulla generazione corrente fino all’adozione confermata.',receiverView).className='hint';
       if(data.preview){
         const review=element('section',undefined,receiverView);review.id='receiver-preview';element('h4','Modifiche del candidato da revisionare',review);
         if(data.preview.files)json(review,data.preview.files);
         if(typeof data.preview.diff==='string')element('pre',bounded(data.preview.diff),review);
         if(!receiverPreviewComplete(data))element('p','Preview incompleta o troncata. Revisiona il candidato completo con gli strumenti locali prima di proseguire; l’applicazione da questa vista è disabilitata.',review).className='ontology-direction';
       }
       const details=element('details',undefined,receiverView);element('summary','Validazione e checkpoint della ricezione',details);json(details,data);
       if(value.receive_transaction){element('h4','Transazione locale di ricezione',details);json(details,value.receive_transaction);}
     }
     function refreshReceiver(){
       const data=snapshot?.receiver,transaction=snapshot?.receive_transaction;
       receiverResume.disabled=busy||!!pending||!receiverConsent.checked||!snapshot?.configured;
       receiverCheck.disabled=busy||!!pending||!snapshot?.configured;receiverPause.disabled=busy||!!pending||!data?.enabled||data?.paused;
       const complete=!!data?.pending_oid&&!!data?.base_head&&!!data?.candidate_digest&&receiverPreviewComplete(data);
       const recovering=data?.state==='recovery_required'||['applying','recovery_required','rebuilding'].includes(transaction?.state);
       receive.disabled=busy||!!pending||!receiverExclusive.checked||!complete||data?.state!=='pending'||recovering;
       const recoverable=!!transaction?.B&&!!transaction?.R&&!!transaction?.candidate_digest;
       finish.disabled=rollback.disabled=busy||!!pending||!receiverExclusive.checked||!recoverable||!recovering;
     }
     operation.addEventListener('input',refresh);exclusive.addEventListener('change',refresh);
     function head(){return snapshot?.head||snapshot?.local_head||snapshot?.HEAD||snapshot?.git?.head||null;}
     function refresh(){if(!current())return;for(const item of mutable)item.disabled=busy;configure.disabled=busy||!!pending||!head()||!previewComplete()||!consent.checked||!visibility.value||!branch.value.trim();initialize.disabled=busy||!!pending||!!head()||!previewComplete()||!Array.isArray(preview?.files)||!initializeConsent.checked||!branch.value.trim()||!remoteUrl.value.trim()||!authorName.value.trim()||!authorEmail.value.trim();publish.disabled=busy||pending?.action==='resolve'||!exclusive.checked||!operation.value.trim()||!head()||selectedRaw().length>0&&(!previewComplete()||!consent.checked);resolve.disabled=busy||pending?.action==='publish'||!snapshot?.current_operation?.idempotency_key||!exclusive.checked||!!decisionKey.value.trim()&&!semantic.checked||!!resolutionDigest.value.trim()&&!resolutionConsent.checked;for(const item of [branch,visibility,mode,raw,operation,decisionKey,semantic,resolutionDigest,resolutionConsent,remoteUrl,authorName,authorEmail,initializeConsent])item.disabled=busy||!!pending;previewButton.disabled=busy||!!pending;refreshReceiver();}
     async function request(label,work){if(busy||!current())return;busy=true;if(vaultStatus.compatibility==='compatible')refresh();message.textContent=label;try{await work();}catch(error){if(current())message.textContent=(error.code||'Esito non confermato')+': '+error.message+' · Rileggi lo stato Git. In caso di esito incerto riprendi la stessa richiesta.';}finally{if(current()){busy=false;if(vaultStatus.compatibility==='compatible')refresh();}}}
     decisionKey.addEventListener('input',()=>{semantic.checked=false;refresh();});semantic.addEventListener('change',refresh);
     resolutionDigest.addEventListener('input',()=>{resolutionConsent.checked=false;refresh();});resolutionConsent.addEventListener('change',refresh);
     async function mutate(action){
       if(!exclusive.checked||action==='resolve'&&(decisionKey.value.trim()&&!semantic.checked||resolutionDigest.value.trim()&&!resolutionConsent.checked))return;
       if(action==='publish'&&selectedRaw().length>0&&(!previewComplete()||!consent.checked)){message.textContent='Revisiona la preview completa delle fonti selezionate e conferma la condivisione prima di pubblicare.';return;}
       if(pending&&pending.action!==action){message.textContent='Esito precedente incerto: riprendi la stessa richiesta prima di cambiare azione.';return;}
       const key=action==='resolve'?snapshot?.current_operation?.idempotency_key:crypto.randomUUID();if(!key){message.textContent='Nessun candidato registrato da riprendere. Aggiorna lo stato Git.';return;}
       if(!pending)pending={action,body:{idempotency_key:key,exclusive_confirmed:true,...(action==='publish'?{operation_id:operation.value.trim(),expected_head:head(),...(selectedRaw().length>0?{raw_paths:selectedRaw(),share_confirmed:true}:{})}:{...(decisionKey.value.trim()?{human_decision_key:decisionKey.value.trim()}:{}),...(resolutionDigest.value.trim()?{resolution_digest:resolutionDigest.value.trim()}:{} )})}};
       return request('Pubblicazione in corso: conserva il checkpoint e attendi l’esito…',async()=>{try{const result=await api(path+'/'+action,pending.body);if(!current())return;pending=null;resultView.replaceChildren();json(resultView,result);message.textContent='Esito registrato nel journal. Controlla stato, checkpoint e prossima azione.';await read(false);}catch(error){if(error.code)pending=null;throw error;}});
     }
     async function read(announce=true){
       const value=await api(path+'/status');if(!current())return;const previous=snapshot?.receiver;snapshot=value;if(vaultStatus.compatibility==='compatible'&&(previous?.pending_oid!==value.receiver?.pending_oid||previous?.candidate_digest!==value.receiver?.candidate_digest||previous?.base_head!==value.receiver?.base_head))receiverExclusive.checked=false;renderReceiver(value);view.replaceChildren();
       const job=value.operation||value.current_operation||value.last_operation||value,state=job.state||value.state||'non configurato';
       element('p','Stato: '+bounded(state),view);
       const next={waiting_network:'Rete non disponibile: conserva il checkpoint e riprendi dopo il ripristino della connessione.',waiting_auth:'Autenticati con Git/gh nel terminale, poi riprendi il candidato salvato.',needs_resolution:'Conflitto conservato in area isolata. Revisiona il perimetro e le note; nessun lato viene scelto automaticamente.',needs_decision:'Revisiona note, fonti e perimetro semantico. Per attestare la decisione usa la chiave restituita nel journal e il consenso dedicato.',needs_approval:'È richiesta approvazione: revisiona il branch proposto o le protezioni. Nessun merge viene eseguito dalla dashboard.',retry_exhausted:'Il remote continua a cambiare. Riprendi dopo aver concordato il momento di pubblicazione.',published_pending_local_adoption:'Il candidato è pubblicato. Conserva le modifiche locali e sospendi gli scrittori prima di riprendere l’adozione; nessun nuovo lint richiesto.',converged:'Pubblicazione e adozione locale verificate.',noop:'Nessuna novità condivisibile: nessun commit aggiuntivo.'}[state];
       if(next)element('p',next,view).className='ontology-direction';
       element('p','Autenticazione e autorizzazione al push: delegate a Git/gh locali; nessuna credenziale acquisita dalla dashboard.',view).className='hint';
       if(!value.config&&!value.configuration)element('p','Collega un repository dati esistente con remote origin e branch scelto, poi revisiona la preview.',view);
       const checkpoints=element('dl',undefined,view);for(const [key,label]of [['B','Base condivisa B'],['L','Checkpoint locale L'],['R','Revisione remota R'],['C','Candidato integrato C']]){element('dt',label,checkpoints);element('dd',bounded(job[key]||job.checkpoints?.[key]||value.config?.[key]||'non disponibile'),checkpoints);}
       if(job.proposal_compare_url){try{const url=new URL(job.proposal_compare_url);if(url.protocol==='https:'&&url.hostname==='github.com'&&!url.username&&!url.password){const link=element('a','Revisiona confronto e crea la PR su GitHub',view);link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';}}catch(_){element('p','Link di confronto non valido: consulta la destinazione Git configurata.',view);}}
       json(view,value);if(announce)message.textContent='Stato Git aggiornato. Nessuna pubblicazione avviata dalla lettura.';
     }
     refresh();request('Lettura dello stato Git…',()=>read());
   }
   return {mount,reset};
 }
"""
