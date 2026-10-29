"""Adozione di un vault legacy, export diagnostico e gestione delle pagine (crea, rinomina, elimina): anteprima, consenso esplicito."""
ADMIN_SCRIPT = r"""
 function createAdminPanel({api,element,getEpoch,getVault,getState,getNodes,stopped,onAdopted,onOperation}) {
   let generation=0;
   const root=()=>'/api/v1/vaults/'+encodeURIComponent(getVault());
   function reset(){++generation;for(const id of ['adopt','pages']){const section=document.getElementById(id+'-section');if(section)section.hidden=true;document.getElementById(id+'-panel').replaceChildren();}}
   // Crea, rinomina, elimina: stessa anteprima → conferma → journal della modifica del grafo. Rinominare riscrive solo i bersagli dei link.
   function mountPages(vaultStatus) {
     if(!vaultStatus.capabilities?.graph_edit||!vaultStatus.live_content_revision)return;
     const section=document.getElementById('pages-section'),box=document.getElementById('pages-panel');section.hidden=false;
     const run=getEpoch(),version=generation,vault=getVault(),current=()=>version===generation&&run===getEpoch()&&vault===getVault()&&!stopped();
     element('p','Tre operazioni sulle pagine: la rinomina aggiorna i link che puntano alla pagina; l\'eliminazione non è valida finché altre pagine la citano. Nessuna scrittura prima dell\'applicazione confermata.',box).className='hint';
     const kind=element('select',undefined,box);kind.setAttribute('aria-label','Operazione sulle pagine');
     for(const [value,text] of [['create','Crea una pagina'],['rename','Rinomina una pagina'],['delete','Elimina una pagina']])kind.append(new Option(text,value));
     const fields=element('div',undefined,box),result=element('div',undefined,box);
     const input=label=>{const wrap=element('div',undefined,fields),id='pages-'+Math.random().toString(36).slice(2);const l=element('label',label,wrap),field=element('input',undefined,wrap);field.id=id;l.htmlFor=id;return field;};
     let read=()=>({});
     const draw=()=>{
       fields.replaceChildren();result.replaceChildren();
       const hints=element('datalist',undefined,fields);hints.id='pages-known';for(const id of getNodes().slice(0,500))hints.append(new Option(id,id));
       if(kind.value==='create'){const name=input('Nome della nuova pagina'),tipo=input('Tipo (facoltativo)');read=()=>({op:'create',name:name.value.trim(),tipo:tipo.value.trim()||null});}
       else{const page=input('Pagina');page.setAttribute('list','pages-known');
         if(kind.value==='rename'){const name=input('Nuovo nome');read=()=>({op:'rename',page:page.value.trim(),new_name:name.value.trim()});}
         else read=()=>({op:'delete',page:page.value.trim()});}
     };
     kind.addEventListener('change',draw);draw();
     const preview=element('button','Anteprima',box);preview.type='button';
     preview.addEventListener('click',async()=>{
       const key=crypto.randomUUID().replaceAll('-','');preview.disabled=true;result.replaceChildren();element('p','Calcolo dell\'anteprima…',result);
       try{
         const base=root()+'/pages/',proposal=await api(base+'preview',{base_content_digest:getState().live_content_revision,idempotency_key:key,operation:read()});
         if(!current())return;result.replaceChildren();
         element('p','File coinvolti: '+proposal.paths.join(', '),result);
         element('h4','Differenze · Markdown come testo',result);element('pre',proposal.diff+(proposal.diff_truncated?'\n… differenze troncate':''),result);
         if(!proposal.valid){element('p',proposal.risk||'La proposta non supera la validazione del grafo, non si può applicare:',result);
           const bad=element('ul',undefined,result);for(const item of proposal.problems)element('li',item.code+' · '+(item.reason||item.page),bad);return;}
         const sure=element('input',undefined,result);sure.type='checkbox';sure.id='pages-sure-'+key;
         element('label','Ho sospeso editor e hook esterni e ho letto le differenze.',result).htmlFor=sure.id;
         const apply=element('button','Applica',result);apply.type='button';
         apply.addEventListener('click',async()=>{
           if(!sure.checked){element('p','Conferma prima la sospensione degli scrittori esterni e la lettura delle differenze.',result);return;}
           apply.disabled=true;
           try{
             const job=await api(base+'apply',{preview_id:proposal.preview_id,proposal_hash:proposal.proposal_hash,idempotency_key:crypto.randomUUID().replaceAll('-',''),
               mode:'manual_paused',external_writers_paused:true,semantic_reviewed:true},{'If-Match':'"'+proposal.base_content_digest+'"'});
             if(!current())return;result.replaceChildren();element('p','Operazione avviata ('+job.operation_id+'). Segui lo stato qui sopra; poi premi Aggiorna vista.',result);
             onOperation(vault,job.operation_id);
           }catch(error){element('p',(error.code?error.code+': ':'')+error.message+' · Rifai l\'anteprima.',result);}
         });
       }catch(error){if(current()){result.replaceChildren();element('p',(error.code?error.code+': ':'')+error.message,result);}}
       finally{preview.disabled=false;}
     });
   }
   function mount(vaultStatus) {
     reset();
     mountPages(vaultStatus);
     if(vaultStatus.compatibility!=='legacy_readonly')return;
     const section=document.getElementById('adopt-section'),box=document.getElementById('adopt-panel');section.hidden=false;
     const run=getEpoch(),version=generation,vault=getVault(),current=()=>version===generation&&run===getEpoch()&&vault===getVault()&&!stopped();
     element('p','Questo vault è in sola lettura (formato legacy). L\'adozione crea soltanto .teseo/project.json e lo stato locale: nessuna nota, fonte raw, script o database viene modificato o spostato. Si può annullare cancellando la cartella .teseo.',box);
     const result=element('div',undefined,box),start=element('button','Anteprima dell\'adozione',box);start.type='button';
     start.addEventListener('click',async()=>{
       start.disabled=true;result.replaceChildren();element('p','Analisi del vault…',result);
       try{
         const plan=await api(root()+'/adopt/preview',{});if(!current())return;result.replaceChildren();
         element('p',plan.pages+' pagine, '+plan.raw_files+' fonti raw ('+Math.round(plan.raw_bytes/1024)+' KiB). Verranno creati: '+plan.files.map(item=>item.path).join(', ')+'.',result);
         element('p',plan.unchanged,result).className='hint';
         if(plan.parse_error)element('p','Il vault non è analizzabile: '+plan.parse_error+'. Puoi adottarlo, ma il grafo non si costruirà finché non lo correggi.',result);
         else if(plan.problems.length){element('p','Il grafo non si può costruire finché questi problemi non sono corretti (l\'adozione resta possibile):',result);
           const list=element('ul',undefined,result);for(const item of plan.problems)element('li',item.code+' · '+item.page,list);}
         else element('p','Nessun problema: dopo l\'adozione si costruisce la prima generazione del grafo.',result);
         const agree=element('input',undefined,result);agree.type='checkbox';agree.id='adopt-consent';agree.style.width='24px';agree.style.minHeight='44px';agree.style.verticalAlign='middle';
         element('label','Ho letto l\'anteprima e autorizzo l\'adozione di questo vault.',result).htmlFor='adopt-consent';
         const go=element('button','Adotta il vault',result);go.type='button';go.disabled=true;agree.addEventListener('change',()=>{go.disabled=!agree.checked;});
         go.addEventListener('click',async()=>{go.disabled=true;
           try{const done=await api(root()+'/adopt/apply',{plan_digest:plan.plan_digest,confirm:true});if(!current())return;
             result.replaceChildren();element('p','Vault adottato. Grafo: '+(done.graph.state==='built'?'costruito':'non costruito ('+done.graph.reason+')')+'.',result);onAdopted(done.vault.vault_id);}
           catch(error){element('p',(error.code?error.code+': ':'')+error.message+' · Rifai l\'anteprima.',result);}});
       }catch(error){if(current()){result.replaceChildren();element('p',(error.code?error.code+': ':'')+error.message,result);}}
       finally{start.disabled=false;}
     });
   }
   // Export diagnostico: solo conteggi, versioni e codici; mai testo delle note, nomi di pagina, percorsi assoluti o URL del remoto.
   function exportInto(container) {
     const box=element('details',undefined,container);element('summary','Export diagnostico per le segnalazioni',box);
     element('p','Contiene versioni, forma del vault (conteggi), codici dei problemi e dei guasti. Non contiene testo delle note, nomi di pagina, percorsi, URL del remoto o nomi di persone.',box).className='hint';
     const out=element('div',undefined,box),button=element('button','Genera export',box);button.type='button';
     button.addEventListener('click',async()=>{
       button.disabled=true;out.replaceChildren();
       try{
         const data=await api(root()+'/diagnostics-export'),text=JSON.stringify(data,null,2);
         element('pre',text,out);
         const save=element('button','Scarica il file JSON',out);save.type='button';
         save.addEventListener('click',()=>{const url=URL.createObjectURL(new Blob([text],{type:'application/json'})),link=document.createElement('a');link.href=url;link.download='teseo-diagnostica.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
       }catch(error){element('p',(error.code?error.code+': ':'')+error.message,out);}
       finally{button.disabled=false;}
     });
   }
   return {mount,reset,exportInto};
 }
"""
