/** ECC evaluate_script: run only on an authenticated, synthetic managed vault.
 * A real rebuild is submitted. The first response is deliberately lost in this
 * page; retry must recover that same durable operation, without a second job.
 */
async function dashboardRebuildSmoke() {
  const $ = id => document.getElementById(id), original = window.fetch;
  const keys = [], checks = [];
  const wait = async predicate => {
    for(let n=0;n<500;n++){if(predicate())return;await new Promise(r=>setTimeout(r,20));}
    throw new Error('UI timeout');
  };
  const expect = (condition, message) => {if(!condition)throw new Error(message);checks.push(message);};
  await wait(()=>!$('rebuild').disabled && !$('apply').disabled);
  expect($('vault').options.length===2,'restart restores managed and legacy vaults without --vault');
  let lose = true;
  window.fetch = async(path,options) => {
    const response = await original(path,options);
    if(String(path).endsWith('/rebuild')) {
      keys.push(JSON.parse(options.body).idempotency_key);
      if(lose){lose=false;throw new TypeError('Risposta persa dopo invio');}
    }
    return response;
  };
  try {
    $('rebuild').click();await wait(()=>!$('rebuild').disabled);
    expect($('operation').textContent.includes('Esito della richiesta non confermato'),
      'lost response reports uncertainty, preserves retry key');
    $('rebuild').click();await wait(()=>$('operation').textContent.includes('succeeded'));
    expect(keys.length===2 && keys[0]===keys[1],'retry reuses identical idempotency key');
    expect($('operation').textContent.includes('Aggiorna vista'),'success requests explicit refresh');
    expect(!location.hash,'session fragment removed after restart');
    return {status:'pass',checks};
  } finally {window.fetch=original;}
}
