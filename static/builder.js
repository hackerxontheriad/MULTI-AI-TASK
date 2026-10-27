(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const token = () => { try { return sessionStorage.getItem('madx-app-token') || ''; } catch (_) { return ''; } };
  const headers = () => { const t = token().trim(); return t ? { Authorization: `Bearer ${t}` } : {}; };
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let modelRows = [], building = false;
  function toast(text) { const node = document.createElement('div'); node.className='toast show'; node.textContent=text; document.body.append(node); setTimeout(()=>node.remove(),4500); }
  async function api(url, options={}) { const response=await fetch(url,{credentials:'same-origin',...options,headers:{...headers(),...(options.headers||{}),...(options.body?{'Content-Type':'application/json'}:{})}}); if(!response.ok){let data={};try{data=await response.json()}catch(_){}const e=data.detail||data.message||`HTTP ${response.status}`;throw new Error(typeof e==='string'?e:(e.message||JSON.stringify(e)));}return response; }
  async function json(url, options={}) { return (await api(url,options)).json(); }
  function setStep(id,state){const el=$(id);if(!el)return;el.classList.toggle('active',state==='active');el.classList.toggle('done',state==='done');el.querySelector('i').textContent=state==='done'?'DONE':state==='active'?'RUNNING':state==='fail'?'FAILED':'WAITING';}
  function setStatus(text,kind=''){const el=$('build-status');el.textContent=text;el.className='status-message '+kind;}
  function setBusy(v){building=v;$('build-button').disabled=v;$('build-button').querySelector('span').textContent=v?'Building…':'Build project ZIP';$('pulse').style.opacity=v?'1':'.25';}
  function isReady(row){
    if(row.route_kind==='auto')return false;
    if(row.route_kind==='official_api')return row.auth_configured===true;
    if(row.route_kind==='local')return row.verified_by==='provider-live-models-api'||String(row.availability||'').startsWith('installed in the local Ollama service');
    return row.auth_configured===true&&!!row.id;
  }
  function renderModels(){
    const host=$('models');host.replaceChildren();
    const textRows=modelRows.filter(r=>r.type==='text'&&r.id!=='auto|auto'&&r.id!=='auto'&&r.route_kind!=='auto');
    const selectedValue=host.dataset.selected||'auto';
    const autoLabel=document.createElement('label');autoLabel.className='model-option';
    const autoRadio=document.createElement('input');autoRadio.type='radio';autoRadio.name='worker-model';autoRadio.value='auto';autoRadio.checked=selectedValue==='auto';
    autoRadio.addEventListener('change',()=>{host.dataset.selected='auto';});
    const autoContent=document.createElement('span');const autoTitle=document.createElement('b');autoTitle.textContent='Auto · resolve one configured route';const autoSmall=document.createElement('small');autoSmall.textContent='Selects one configured route before execution; no fallback if it fails.';const autoTier=document.createElement('small');autoTier.className='free';autoTier.textContent='ONE ROUTE ONLY';autoContent.append(autoTitle,autoSmall,autoTier);autoLabel.append(autoRadio,autoContent);host.append(autoLabel);
    if(!textRows.length){const msg=document.createElement('div');msg.className='empty';msg.textContent='No provider model catalog returned. Auto will work only after a configured route is available.';host.append(msg);return;}
    const selectedReady=textRows.find(r=>r.id===selectedValue&&isReady(r));
    if(selectedValue!=='auto'&&!selectedReady)host.dataset.selected='auto';
    for(const row of textRows){
      const ready=isReady(row);const label=document.createElement('label');label.className='model-option'+(ready?'':' unavailable');
      const radio=document.createElement('input');radio.type='radio';radio.name='worker-model';radio.value=row.id;radio.disabled=!ready;radio.checked=ready&&(host.dataset.selected===row.id||(selectedValue==='auto'&&!host.dataset.selected&&!!row.free_tier));
      radio.addEventListener('change',()=>{host.dataset.selected=row.id;});
      const content=document.createElement('span');const b=document.createElement('b');b.textContent=row.id;const small=document.createElement('small');small.textContent=ready?'Ready · '+(row.route_kind||'configured route'):(row.availability||'Not configured / not reachable');const tier=document.createElement('small');tier.className='free';tier.textContent=row.free_tier?'FREE-TIER MAY APPLY':'KEYED / USER CONFIGURED';content.append(b,small,tier);label.append(radio,content);host.append(label);
      if(radio.checked)host.dataset.selected=row.id;
    }
    const checked=host.querySelector('input[name="worker-model"]:checked');if(!checked){autoRadio.checked=true;host.dataset.selected='auto';}
  }
  async function loadModels(){
    $('models').innerHTML='<div class="empty">Refreshing model routes…</div>';
    try{const data=await json('/v1/models');modelRows=data.data||[];const host=$('models');host.dataset.selected=host.dataset.selected||'auto';renderModels();}
    catch(e){$('models').innerHTML=`<div class="empty">${esc(e.message)}<br><br>Sign in on the main workspace or save the app access token under Settings, then refresh.</div>`;}
  }
  function showResult(data){const host=$('result');host.replaceChildren();$('stat-workers').textContent=String((data.tasks||[]).length||'—');$('stat-files').textContent=String(data.file_count||'—');$('stat-size').textContent=data.zip_bytes?`${(data.zip_bytes/1024).toFixed(1)} KB`:'—';for(const [id,state] of [['step-plan','done'],['step-workers',data.status==='completed'?'done':data.status==='failed'?'fail':'active'],['step-validate',data.status==='completed'?'done':data.status==='failed'?'fail':'waiting'],['step-zip',data.status==='completed'?'done':data.status==='failed'?'fail':'waiting']])setStep(id,state);
    const banner=document.createElement('div');banner.className='result-banner';const h=document.createElement('h3');h.textContent=data.status==='completed'?'Project ZIP ready':data.status==='failed'?'Build failed':'Build response';const p=document.createElement('p');p.textContent=data.message||data.summary||'Build completed.';banner.append(h,p);if(data.model_route||data.planner_route||data.storage_backend){const meta=document.createElement('p');meta.className='muted';meta.textContent=`Model: ${data.model_route||data.planner_route||'see task rows'} · ZIP storage: ${data.storage_backend||'database'}`;banner.append(meta);}if(data.download_url&&data.status==='completed'){const a=document.createElement('a');a.href=data.download_url;a.textContent='Download ZIP ↗';a.addEventListener('click',e=>{e.preventDefault();downloadZip(data.download_url)});banner.append(a);}host.append(banner);
    for(const task of data.tasks||[]){const details=document.createElement('details');details.className='assignment';const summary=document.createElement('summary');summary.textContent=`${task.title||'Worker'} · ${task.route||'route'}`;details.append(summary);const status=document.createElement('span');status.className='task-status '+(task.status||'');status.textContent=String(task.status||'unknown').toUpperCase();details.append(status);const small=document.createElement('small');small.textContent=`${task.role||'Worker'} · ${task.elapsed_ms||0} ms · ${(task.files||[]).join(', ')}`;details.append(small);if(task.error){const pre=document.createElement('pre');pre.textContent=JSON.stringify(task.error,null,2);pre.className='error-text';details.append(pre);}if(task.notes){const pre=document.createElement('pre');pre.textContent=task.notes;details.append(pre);}const assignment=(data.assignments||[]).find(a=>a.task_id===task.task_id);if(assignment?.work_prompt){const btn=document.createElement('button');btn.type='button';btn.textContent='Copy full work prompt';btn.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(assignment.work_prompt);toast('Worker prompt copied.');}catch(_){toast('Clipboard unavailable. Expand and select the prompt manually.');}});details.append(btn);const pre=document.createElement('pre');pre.textContent=assignment.work_prompt;details.append(pre);}host.append(details);}
    if(data.summary){const notes=document.createElement('p');notes.className='muted';notes.textContent=data.summary;host.append(notes);} }
  async function downloadZip(url){try{const response=await api(url);const blob=await response.blob();const href=URL.createObjectURL(blob);const a=document.createElement('a');a.href=href;a.download='madx-project.zip';document.body.append(a);a.click();a.remove();URL.revokeObjectURL(href);}catch(e){toast(e.message);}}
  $('refresh-models').addEventListener('click',loadModels);
  $('build-form').addEventListener('submit',async event=>{event.preventDefault();if(building)return;const selected=[...document.querySelectorAll('input[name="worker-model"]:checked')].map(el=>el.value).slice(0,1);if(!selected.length){toast('Choose one model route or Auto.');return;}const prompt=$('prompt').value.trim();if(prompt.length<8){toast('Add a little more detail to the build request.');return;}setBusy(true);setStatus('Resolving one model route for planning and all work packages…');$('result').innerHTML='';$('stat-workers').textContent='—';$('stat-files').textContent='—';$('stat-size').textContent='—';for(const id of ['step-plan','step-workers','step-validate','step-zip'])setStep(id,'waiting');setStep('step-plan','active');setStep('step-workers','waiting');try{const data=await json('/api/projects/build',{method:'POST',body:JSON.stringify({project_name:$('project-name').value.trim()||'MADX project',prompt,planner_model:selected[0],worker_models:selected,max_tasks:Number($('max-tasks').value),worker_max_tokens:Number($('worker-tokens').value)})});showResult(data);if(data.status==='completed')setStatus('All work packages used the same selected model; ZIP was packaged.','success');else setStatus(data.message||'Some tasks failed; no final ZIP was marked complete.','error');}catch(e){setStatus(e.message,'error');for(const id of ['step-plan','step-workers','step-validate','step-zip'])setStep(id,'fail');$('result').innerHTML=`<div class="result-banner"><h3>Request could not complete</h3><p>${esc(e.message)}</p><p>Check model configuration and try again. The system never hides a failed selected route.</p></div>`;}finally{setBusy(false);}});
  loadModels();
})();
