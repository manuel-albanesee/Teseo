/** ECC Chrome DevTools evaluate_script; use tests/dashboard_ui_fixture.py. No real vaults. */
async function ontologySmoke(){
 const $=id=>document.getElementById(id),original=window.fetch,checks=[],requests=[];
 const expect=(ok,label)=>{if(!ok)throw new Error(label);checks.push(label);};
 const wait=async test=>{for(let n=0;n<400;n++){if(test())return;await new Promise(r=>setTimeout(r,25));}throw new Error('UI timeout: '+$('ontology-editor-message')?.textContent);};
 const set=(id,value)=>{const input=$('ontology-'+id);input.value=value;input.dispatchEvent(new Event('input',{bubbles:true}));};
 const adopt=()=>{if(!$('ontology-adopt').checked){$('ontology-adopt').checked=true;$('ontology-adopt').dispatchEvent(new Event('change'));}};
 const clear=()=>[...document.querySelectorAll('#ontology-editor button')].find(x=>x.textContent==='Svuota proposta').click();
 const add=(action,name,extra={})=>{set('category','relation');set('action',action);set('name',name);for(const [key,value] of Object.entries(extra))set(key,value);$('ontology-form').requestSubmit();};
 const done=()=>!$('ontology-preview').disabled && !$('ontology-result').hasAttribute('aria-busy');
 const tracked=(path,options)=>{requests.push({path:String(path),method:options?.method||'GET',body:options?.body?JSON.parse(options.body):null});return original(path,options);};
 window.fetch=tracked;
 try{
   await wait(()=>!!$('ontology-form'));document.querySelector('[data-view=ontology]').click();clear();
   expect($('ontology-preview').disabled&&$('ontology-changes').textContent.includes('Nessuna modifica'),'empty: clear proposal has no submission');
   adopt();add('add','approva',{from_types:'persona',to_types:'persona',meaning:'<script>window.EDITOR_XSS=true</script>',example:'Anna → Bruno'});
   expect($('ontology-form').textContent.includes('sorgente → relazione → destinazione'),'direction: saved source to target is explicit');
   let release;
   window.fetch=async(path,options)=>{const response=await tracked(path,options);if(String(path).endsWith('/ontology/preview'))await new Promise(r=>release=r);return response;};
   $('ontology-preview').click();await wait(()=>!!release);
   expect($('ontology-preview').disabled&&$('ontology-editor-message').textContent.includes('in corso'),'loading: duplicate submission disabled');
   release();await wait(done);
   expect($('ontology-result').textContent.includes('Nessuna nuova inferenza automatica')&&$('ontology-result').textContent.includes('Nessuna modifica applicata'),'success: no inference or apply implied');
   expect(document.activeElement.id==='ontology-result','focus: result receives keyboard focus');
   expect(!$('ontology-result').querySelector('script,img,a')&&!window.EDITOR_XSS&&$('ontology-result').textContent.includes('<script>'),'security: schema HTML remains text');
   const payload=requests.find(x=>x.path.endsWith('/ontology/preview')).body;
   expect(payload.patch[0].op==='adopt_types'&&payload.patch[1].value.direction==='source_to_target','contract: explicit adoption precedes oriented relation');
   set('meaning','Bozza successiva');expect($('ontology-result').dataset.obsolete==='true','draft edit: old result marked obsolete');
   window.fetch=tracked;$('refresh').click();await wait(()=>!!$('ontology-form')&&$('ontology-name').value==='approva');
   expect($('ontology-changes').textContent.includes('approva')&&$('ontology-result').dataset.obsolete==='true','refresh: queue, fields and old result preserved as obsolete');
   clear();adopt();add('remove','usa');$('ontology-preview').click();await wait(done);
   expect($('ontology-result').textContent.includes('unknown_relation')&&$('ontology-result').textContent.includes('wiki/Persona 00.md'),'impact: used removal shows located violations');
   clear();adopt();add('rename','usa',{to:'utilizza'});$('ontology-preview').click();await wait(done);
   expect($('ontology-result').textContent.includes('Rinomina esatta da confermare'),'rename: migration is suggestion requiring confirmation');
   clear();adopt();add('add','approva',{from_types:'ignoto',to_types:'persona'});$('ontology-preview').click();await wait(done);
   expect($('ontology-editor-message').textContent.includes('invalid_schema')&&$('ontology-result').textContent.includes('Wiki reference.md'),'error: invalid schema gives located details and preserved draft');
   clear();adopt();add('add','approva',{from_types:'persona',to_types:'persona'});
   let lost=true;
   window.fetch=async(path,options)=>{const response=await tracked(path,options);if(String(path).endsWith('/ontology/preview')&&lost){lost=false;throw new TypeError('Risposta persa di prova');}return response;};
   $('ontology-preview').click();await wait(done);expect($('ontology-editor-message').textContent.includes('non confermata'),'offline: uncertain response has explicit retry');
   $('ontology-preview').click();await wait(done);
   const retries=requests.filter(x=>x.path.endsWith('/ontology/preview')).slice(-2);
   expect(retries[0].body.idempotency_key===retries[1].body.idempotency_key&&$('ontology-result').textContent.includes('Validazione disponibile superata'),'retry: same key recovers response');
   let releaseOld;
   window.fetch=async(path,options)=>{const response=await tracked(path,options);if(String(path).endsWith('/ontology/preview'))await new Promise(r=>releaseOld=r);return response;};
   $('ontology-preview').click();await wait(()=>!!releaseOld);set('name','altra_bo zza');releaseOld();await wait(done);
   expect($('ontology-editor-message').textContent.includes('Bozza modificata')&&$('ontology-result').dataset.obsolete==='true','race: late response does not replace edited draft');
   window.fetch=tracked;
   expect([...document.querySelectorAll('#ontology-form input,#ontology-form select,#ontology-form textarea')].every(x=>document.querySelector('label[for="'+x.id+'"]')),'accessibility: every form control has a label');
   expect(!requests.some(x=>x.method==='POST'&&!x.path.endsWith('/ontology/preview')),'safety: editor sends only preview POSTs');
   expect(!requests.some(x=>x.path.includes('/ontology/preview?')),'revision: preview does not pin old graph generation');
   return {checks,previewPosts:requests.filter(x=>x.path.endsWith('/ontology/preview')).length};
 }finally{window.fetch=original;}
}
