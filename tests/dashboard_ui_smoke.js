/** Run with ECC Chrome DevTools evaluate_script on an authenticated synthetic vault.
 * Fixture: 56 persona nodes named Persona 00..55, a source nota-utente,
 * directed usa edges and hostile HTML stored as note text. No real vaults.
 * Fetch overrides are scoped to this page and restored even on failure.
 */
async function dashboardSmoke() {
  const $ = id => document.getElementById(id);
  const original = window.fetch, requests = [], checks = [];
  const expect = (condition, label) => { if (!condition) throw new Error(label); checks.push(label); };
  const wait = async predicate => { for(let n=0;n<250;n++){if(predicate())return;await new Promise(r=>setTimeout(r,20));}throw new Error('UI timeout'); };
  const tracked = (path, options) => {requests.push(String(path));return original(path,options);};
  const refresh = async () => {$('refresh').click();await wait(()=>!$('apply').disabled && $('counts').textContent.includes('50 nodi'));};
  window.fetch = tracked;
  try {
    await wait(()=>!$('apply').disabled && $('counts').textContent.includes('50 nodi'));
    expect($('counts').textContent.includes('Dati parziali'), 'partial: first page explicitly marked');
    for(let page=0;page<5&&!$('more').hidden;page++) {
      $('more').click();expect($('more').disabled, 'pagination: duplicate click disabled');
      await wait(()=>!$('more').disabled);
    }
    const labels=[...document.querySelectorAll('#nodes button')].map(button=>button.firstChild.textContent);
    expect(labels.length===57 && new Set(labels).size===57 && $('more').hidden, 'pagination: all 57 nodes without duplicates');
    $('type').value='persona';$('relation').value='usa';$('filters').requestSubmit();
    await wait(()=>!$('apply').disabled);
    expect(document.querySelectorAll('#nodes button').length===50, 'type/relation filters: first 50 persona nodes');
    $('search').value='NO MATCH';$('search').dispatchEvent(new Event('input'));
    expect($('nodes').textContent.includes('Nessun nodo'), 'empty: loaded-node search has useful next action');
    $('search').value='';$('search').dispatchEvent(new Event('input'));
    document.querySelector('#nodes button').click();await wait(()=>!!document.querySelector('#detail pre'));
    expect($('detail').textContent.includes('<script>') && !window.XSS_EXECUTED && !$('detail').querySelector('script,img,a'), 'security: hostile Markdown is inert text with no active external links');
    expect(document.activeElement.id==='detail', 'accessibility: selecting node focuses detail');
    expect($('detail').textContent.includes('nota-utente') && $('detail').textContent.includes(' → usa → '), 'detail: source and directed relations available');
    let releaseFirst;
    window.fetch=async(path,options)=>{const response=await tracked(path,options);if(String(path).includes('/nodes/Persona%2000?'))await new Promise(resolve=>releaseFirst=resolve);return response;};
    const buttons=document.querySelectorAll('#nodes button');buttons[0].click();await wait(()=>!!releaseFirst);buttons[1].click();
    await wait(()=>$('detail').querySelector('h3')?.textContent==='Persona 01' && !!$('detail').querySelector('pre'));
    releaseFirst();await new Promise(r=>setTimeout(r,100));
    expect($('detail').querySelector('h3').textContent==='Persona 01', 'race: delayed first detail cannot replace latest selection');
    window.fetch=async(path,options)=>String(path).includes('/graph?')?new Response(JSON.stringify({error:{code:'revision_changed',message:'Nuova generazione'}}),{status:409,headers:{'Content-Type':'application/json'}}):tracked(path,options);
    $('more').click();await wait(()=>$('notice').textContent.includes('nuova generazione'));
    expect($('apply').disabled && $('more').disabled && document.querySelectorAll('#nodes button').length===50, 'revision conflict: old coherent data retained and pagination blocked');
    window.fetch=tracked;await refresh();
    window.fetch=async()=>{throw new TypeError('Offline di prova');};$('refresh').click();await wait(()=>$('notice').textContent.includes('Connessione non disponibile'));
    expect($('notice').textContent.includes('Aggiorna vista'), 'offline: readable failure and explicit retry');
    window.fetch=tracked;await refresh();
    let releaseStatus;
    window.fetch=async(path,options)=>{if(String(path).endsWith('/status'))await new Promise(resolve=>releaseStatus=resolve);return tracked(path,options);};
    $('refresh').click();await wait(()=>!!releaseStatus);
    expect($('root').textContent.includes('Caricamento'), 'loading: state visible while request is pending');
    releaseStatus();await wait(()=>!$('apply').disabled);
    window.fetch=async(path,options)=>{const response=await tracked(path,options);if(String(path).includes('/graph?')){const data=await response.json();return Response.json({...data,nodes:[],edges:[],next_cursor:null});}return response;};
    $('filters').requestSubmit();await wait(()=>!$('apply').disabled);
    expect($('counts').textContent.includes('0 nodi') && $('nodes').textContent.includes('Nessun nodo'), 'empty: empty graph page has clear result');
    window.fetch=tracked;await refresh();
    let releaseGraph, held=false;
    window.fetch=async(path,options)=>{
      const response=await tracked(path,options);
      if(String(path).includes('/graph?')&&!held){held=true;const data=await response.json();await new Promise(resolve=>releaseGraph=resolve);return Response.json({...data,nodes:[{id:'OBSOLETE',tipo:'persona'}]});}
      return response;
    };
    $('filters').requestSubmit();await wait(()=>!!releaseGraph);await refresh();releaseGraph();await new Promise(r=>setTimeout(r,100));
    expect(!$('nodes').textContent.includes('OBSOLETE'), 'race: graph response from prior view ignored after refresh');
    window.fetch=async(path,options)=>{
      const response=await tracked(path,options);
      if(String(path).endsWith('/status')){const data=await response.json();return Response.json({...data,capabilities:{...data.capabilities,graph:false},graph_generation:null,content_revision:null,issues:[{severity:'warning',code:'graph_unavailable',message:'Grafo assente'}]});}
      return response;
    };
    $('refresh').click();await wait(()=>$('counts').textContent.includes('Grafo non disponibile'));
    expect($('apply').disabled && $('ontology').textContent.includes('non disponibile') && $('diagnostics').textContent.includes('graph_unavailable'), 'missing graph: controls disabled and diagnostic reason available');
    window.fetch=tracked;await refresh();
    document.querySelector('[data-view=ontology]').click();
    expect(!$('ontology').hidden && $('ontology').textContent.includes('X usa Y'), 'ontology: meaning and direction shown');
    document.querySelector('[data-view=diagnostics]').click();
    expect(!$('diagnostics').hidden && $('diagnostics').textContent.includes('revisione pubblicata'), 'diagnostics: scope explicitly declared');
    document.querySelector('[data-view=graph]').click();
    const pinned=requests.filter(path=>/\/(graph|ontology|diagnostics)\?|\/nodes\//.test(path));
    expect(pinned.length>0 && pinned.every(path=>new URL(path,location.origin).searchParams.get('generation')?.length===64), 'consistency: all content requests carry generation pin');
    expect(!requests.some(path=>/rebuild|operations/.test(path)), 'readonly: no rebuild or operation requests');
    return {status:'pass',checks};
  } finally {window.fetch=original;}
}
