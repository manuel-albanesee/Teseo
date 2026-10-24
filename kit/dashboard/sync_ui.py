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
     operation.addEventListener('input',refresh);exclusive.addEventListener('change',refresh);
     function head(){return snapshot?.head||snapshot?.local_head||snapshot?.HEAD||snapshot?.git?.head||null;}
     function refresh(){if(!current())return;for(const item of mutable)item.disabled=busy;configure.disabled=busy||!!pending||!head()||!previewComplete()||!consent.checked||!visibility.value||!branch.value.trim();initialize.disabled=busy||!!pending||!!head()||!previewComplete()||!Array.isArray(preview?.files)||!initializeConsent.checked||!branch.value.trim()||!remoteUrl.value.trim()||!authorName.value.trim()||!authorEmail.value.trim();publish.disabled=busy||pending?.action==='resolve'||!exclusive.checked||!operation.value.trim()||!head()||selectedRaw().length>0&&(!previewComplete()||!consent.checked);resolve.disabled=busy||pending?.action==='publish'||!snapshot?.current_operation?.idempotency_key||!exclusive.checked||!!decisionKey.value.trim()&&!semantic.checked||!!resolutionDigest.value.trim()&&!resolutionConsent.checked;for(const item of [branch,visibility,mode,raw,operation,decisionKey,semantic,resolutionDigest,resolutionConsent,remoteUrl,authorName,authorEmail,initializeConsent])item.disabled=busy||!!pending;previewButton.disabled=busy||!!pending;}
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
       const value=await api(path+'/status');if(!current())return;snapshot=value;view.replaceChildren();
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
