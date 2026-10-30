"""Pannello delle lavorazioni: stato delle pipeline ICM del vault, in sola lettura (nessun avvio di fasi)."""
LAVORAZIONI_SCRIPT = r"""
 function createLavorazioniPanel({api,element,getEpoch,getVault,stopped}) {
   let generation=0;
   const root=()=>'/api/v1/vaults/'+encodeURIComponent(getVault());
   function reset(){++generation;document.getElementById('lavorazioni-panel').replaceChildren();}
   function draw(list,data,message){
     list.replaceChildren();
     if(!data.lavorazioni.length){element('p','Nessuna lavorazione in lavorazioni/. Ne crei una dal client con: python .graph/lavorazioni.py nuova NOME --da report-periodico',list);}
     for(const item of data.lavorazioni){
       const section=element('section',undefined,list);element('h4',item.nome,section);
       element('p',item.esecuzione?'Esecuzione '+item.esecuzione:'Nessuna esecuzione',section);
       for(const problem of item.problemi)element('p','Definizione da correggere · '+problem.codice+' · '+problem.messaggio,section);
       const phases=element('ul',undefined,section);
       for(const phase of item.fasi){
         const row=element('li',phase.nome+' · '+phase.stato,phases);
         if(phase.motivi.length)element('span',' — '+phase.motivi.join(' · '),row);
       }
       if(item.output.length){const details=element('details',undefined,section);element('summary','Output ('+item.output.length+')',details);
         const files=element('ul',undefined,details);for(const path of item.output)element('li',path,files);}
     }
     if(data.troncato)element('p','Elenco parziale: ci sono altre lavorazioni oltre il limite mostrato.',list).className='hint';
     message.textContent=data.lavorazioni.length+' lavorazioni · sola lettura';
   }
   function mount(){
     const box=document.getElementById('lavorazioni-panel');box.replaceChildren();
     const run=getEpoch(),version=generation,vault=getVault();
     const current=()=>version===generation&&run===getEpoch()&&vault===getVault()&&!stopped();
     element('p','Sola lettura. Le fasi si eseguono dal client con la skill obsidian-wiki-lavorazioni; qui si vede dove sono arrivate e quali sono da rifare.',box).className='hint';
     const refresh=element('button','Aggiorna lavorazioni',box);refresh.type='button';refresh.id='lavorazioni-refresh';
     const message=element('p','Lettura delle lavorazioni…',box);message.id='lavorazioni-status';message.setAttribute('role','status');message.setAttribute('aria-live','polite');
     const list=element('div',undefined,box);
     async function load(){
       refresh.disabled=true;message.textContent='Lettura delle lavorazioni…';
       try{const data=await api(root()+'/lavorazioni');if(current())draw(list,data,message);}
       catch(error){if(current())message.textContent=(error.code||'errore')+': '+error.message;}
       finally{if(current())refresh.disabled=false;}
     }
     refresh.addEventListener('click',load);load();
   }
   return {mount,reset};
 }
"""
