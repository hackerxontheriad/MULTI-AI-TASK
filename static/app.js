(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const state = {
    page: 'chat', user: null, busy: false, messages: [], pendingFiles: [], files: [],
    catalogRows: [], catalogSource: '', freeReadyRoutes: [], health: {}, googleReady: false, googleLoading: false,
    previewHtml: '', uploadBusy: false
  };
  const TEXT_EXT = new Set(['txt','md','markdown','py','js','mjs','cjs','ts','tsx','jsx','html','htm','css','scss','json','jsonl','xml','yaml','yml','toml','ini','cfg','conf','sh','bash','zsh','bat','ps1','php','java','kt','kts','c','h','cpp','hpp','cs','go','rs','rb','sql','r','ipynb','csv','tsv','log','env.example','dockerfile','makefile','properties','gradle','vue','svelte']);
  const LANG_EXT = {html:'html',htm:'html',javascript:'js',js:'js',jsx:'jsx',typescript:'ts',tsx:'tsx',css:'css',scss:'scss',python:'py',py:'py',json:'json',jsonl:'jsonl',xml:'xml',svg:'svg',java:'java',kotlin:'kt',kt:'kt',c:'c',cpp:'cpp',csharp:'cs',cs:'cs',go:'go',rust:'rs',rs:'rs',php:'php',ruby:'rb',rb:'rb',sql:'sql',bash:'sh',sh:'sh',yaml:'yml',yml:'yml',toml:'toml',markdown:'md',md:'md',text:'txt',txt:'txt',csv:'csv',dockerfile:'Dockerfile',unknown:'txt'};
  const PAGE_PATHS = {chat:'/chat',agents:'/agents',studio:'/studio',files:'/files',settings:'/settings'};
  const PAGE_TITLES = {chat:'Chat workspace',agents:'Agent Lab',studio:'Media Studio',files:'My Files',settings:'Studio Settings'};
  const sessionToken = () => { try { return sessionStorage.getItem('madx-app-token') || ''; } catch (_) { return ''; } };
  const authHeaders = () => { const token=sessionToken().trim(); return token ? {'Authorization':`Bearer ${token}`} : {}; };
  const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const formatBytes = (n) => { if (!Number.isFinite(Number(n))) return '—'; const v=Number(n); if(v<1024)return `${v} B`; if(v<1048576)return `${(v/1024).toFixed(1)} KB`; if(v<1073741824)return `${(v/1048576).toFixed(1)} MB`; return `${(v/1073741824).toFixed(2)} GB`; };
  const formatDate = (seconds) => { try { return new Date(Number(seconds)*1000).toLocaleString(); } catch (_) { return ''; } };
  function toast(message, time=3400) { const t=$('toast'); t.textContent=String(message); t.classList.add('show'); clearTimeout(toast.timer); toast.timer=setTimeout(()=>t.classList.remove('show'),time); }
  function setStatus(id, message, kind='') { const el=$(id); if(!el)return; el.textContent=message||''; el.classList.remove('error','success'); if(kind)el.classList.add(kind); }
  async function errorMessage(response) {
    let data={}; try{data=await response.json();}catch(_){}
    let detail=data.detail ?? data.error ?? data.message ?? `HTTP ${response.status}`;
    if(Array.isArray(detail)) detail=detail.map(x=>x.msg||JSON.stringify(x)).join('; ');
    if(detail && typeof detail==='object') detail=[detail.message||detail.error||'Request failed',detail.reason?`Reason: ${detail.reason}`:'',detail.hint?`Fix: ${detail.hint}`:''].filter(Boolean).join('\n');
    if(response.status===429){const retry=response.headers.get('Retry-After');if(retry)detail+=`\nRetry in about ${retry}s.`;}
    return String(detail);
  }
  async function api(url, options={}) {
    const headers={...authHeaders(),...(options.headers||{})};
    if(options.body && typeof options.body==='string' && !headers['Content-Type'])headers['Content-Type']='application/json';
    const res=await fetch(url,{credentials:'same-origin',...options,headers});
    if(!res.ok) { const err=new Error(await errorMessage(res)); err.status=res.status; throw err; }
    return res;
  }
  async function apiJson(url, options={}) { const res=await api(url,options); return res.json(); }

  function navigate(page, push=true) {
    if(!PAGE_PATHS[page]) page='chat';
    state.page=page;
    document.querySelectorAll('.page').forEach(el=>el.classList.toggle('page-active',el.dataset.page===page));
    document.querySelectorAll('[data-page-link]').forEach(el=>el.classList.toggle('active',el.dataset.pageLink===page));
    $('breadcrumb-title').textContent=PAGE_TITLES[page]||'Chat workspace';
    document.title=`MAD X · ${PAGE_TITLES[page]||'Hybrid AI Studio'}`;
    $('sidebar').classList.remove('open');
    if(push && location.pathname!==PAGE_PATHS[page])history.pushState({page},'',PAGE_PATHS[page]);
    if(page==='files')loadFiles();
    if(page==='settings') { loadCatalog(); setupGoogle(); }
    if(page==='agents') loadCatalog();
    if(page==='studio') loadCatalog();
    if(page==='chat') { $('prompt').focus({preventScroll:true}); }
    window.scrollTo({top:0,behavior:'smooth'});
  }
  document.querySelectorAll('[data-page-link]').forEach(el=>el.addEventListener('click',e=>{e.preventDefault();navigate(el.dataset.pageLink);}));
  document.querySelectorAll('[data-go-page]').forEach(el=>el.addEventListener('click',()=>navigate(el.dataset.goPage)));
  window.addEventListener('popstate',()=>navigate(pathToPage(location.pathname),false));
  function pathToPage(path) { if(path.startsWith('/agents'))return'agents'; if(path.startsWith('/studio'))return'studio'; if(path.startsWith('/files'))return'files'; if(path.startsWith('/settings'))return'settings'; return'chat'; }

  function historyKey(){return `madx:history:${state.user?.id||'local'}`;}
  function saveHistory(){ try{sessionStorage.setItem(historyKey(),JSON.stringify(state.messages.slice(-40)));}catch(_){} }
  function loadHistory(){try{const value=JSON.parse(sessionStorage.getItem(historyKey())||'[]');state.messages=Array.isArray(value)?value.filter(m=>m&&['user','assistant'].includes(m.role)).slice(-40):[];}catch(_){state.messages=[];}renderChat();}
  function clearChat(){if(state.busy){toast('Wait for the current task to finish.');return;}state.messages=[];saveHistory();renderChat();$('prompt').focus();}

  function guessLanguage(raw, given='') {
    const lang=String(given||'').toLowerCase().split(/[\s,;]/)[0].replace(/[^a-z0-9_+#.-]/g,''); if(lang)return lang;
    const code=String(raw||'').trim();
    if(/^<!doctype html|^<html[\s>]|^<\?xml/i.test(code))return'html';
    if(/\b(def|import|from)\b/.test(code)&&/\b(def|print|class)\b/.test(code))return'python';
    if(/\b(const|let|function|console\.log|document\.)\b/.test(code))return'javascript';
    if(/^\s*\{[\s\S]*\}\s*$/.test(code))return'json';
    if(/^[.#][\w-]+\s*\{/.test(code))return'css';
    return'text';
  }
  function highlighter(code, lang) {
    const pre=document.createElement('pre'), inner=document.createElement('code');
    inner.dataset.language=lang; const source=String(code);
    // Tokenization builds spans from text segments; model output is never inserted as HTML.
    const isMarkup=['html','htm','xml','svg'].includes(lang);
    const pattern=isMarkup ? /(<!--[^]*?-->|<![^>]*>|<\/?[A-Za-z][^>]*>|"[^"\n]*"|'[^'\n]*')/g : /(\/\*[\s\S]*?\*\/|\/\/[^\n]*|#[^\n]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`|\b(?:async|await|break|case|catch|class|const|continue|def|elif|else|except|export|extends|false|finally|for|from|function|if|import|in|interface|let|new|null|pass|private|public|return|static|super|switch|this|throw|true|try|type|var|void|while|with|yield|async|await|SELECT|FROM|WHERE|CREATE|INSERT|UPDATE|DELETE)\b|\b\d+(?:\.\d+)?\b)/g;
    let last=0,match; pattern.lastIndex=0;
    while((match=pattern.exec(source))!==null){if(match.index>last)inner.append(document.createTextNode(source.slice(last,match.index)));const token=match[0];const span=document.createElement('span');let cls='';
      if(isMarkup){if(token.startsWith('<'))cls='tok-tag';else if(token.startsWith('"')||token.startsWith("'"))cls='tok-attr';}
      else if(token.startsWith('//')||token.startsWith('/*')||token.startsWith('#'))cls='tok-comment';else if(token.startsWith('"')||token.startsWith("'")||token.startsWith('`'))cls='tok-string';else if(/^\d/.test(token))cls='tok-number';else cls='tok-keyword';
      if(cls){span.className=cls;span.textContent=token;inner.appendChild(span);}else inner.append(document.createTextNode(token));last=pattern.lastIndex;
    }
    if(last<source.length)inner.append(document.createTextNode(source.slice(last)));pre.appendChild(inner);return pre;
  }
  function languageExtension(lang){return LANG_EXT[lang]||'txt';}
  function downloadText(name, text, type='text/plain;charset=utf-8') {const blob=new Blob([text],{type}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name||'mad-x-output.txt';document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1500);}
  async function copyText(text, button) {try{await navigator.clipboard.writeText(String(text));if(button){const old=button.textContent;button.textContent='Copied ✓';setTimeout(()=>button.textContent=old,1200);}else toast('Copied to clipboard.');}catch(_){toast('Clipboard permission denied. Select the text and copy manually.');}}
  function secureHtmlForPreview(html) {
    let value=String(html||'');
    const policy='<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data: blob: https:; style-src \'unsafe-inline\' https:; script-src \'unsafe-inline\'; font-src data: https:; media-src data: blob: https:; connect-src \'none\'; object-src \'none\'; base-uri \'none\'; form-action \'none\'">';
    if(/<head(?:\s[^>]*)?>/i.test(value)) value=value.replace(/<head(?:\s[^>]*)?>/i,m=>m+policy);
    else value='<!doctype html><html><head>'+policy+'</head><body>'+value+'</body></html>';
    return value;
  }
  function openHtmlPreview(html, label='Generated HTML') {state.previewHtml=String(html||'');$('dialog-title').textContent=label;$('preview-source-label').textContent='Isolated preview · local rendering';$('preview-frame').srcdoc=secureHtmlForPreview(state.previewHtml);const dlg=$('preview-dialog');if(typeof dlg.showModal==='function')dlg.showModal();else dlg.setAttribute('open','');}
  function addCodeBlock(target, language, code) {
    const lang=guessLanguage(code,language);const wrap=document.createElement('section');wrap.className='code-block';
    const head=document.createElement('div');head.className='code-head';const badge=document.createElement('span');badge.className='code-language';badge.textContent=lang==='text'?'CODE':lang.toUpperCase();head.appendChild(badge);
    const tools=document.createElement('div');tools.className='code-tools';
    const button=(label,fn)=>{const b=document.createElement('button');b.type='button';b.textContent=label;b.addEventListener('click',()=>fn(b));tools.appendChild(b);return b;};
    button('Copy',b=>copyText(code,b));button('Download',()=>downloadText(`mad-x-output.${languageExtension(lang)}`,code,lang==='html'?'text/html;charset=utf-8':'text/plain;charset=utf-8'));
    if(['html','htm','svg'].includes(lang)||/^\s*(?:<!doctype html|<html[\s>])/i.test(code)){
      button('▶ Run',()=>openHtmlPreview(code,'Run · isolated HTML sandbox'));
      button('Preview',()=>openHtmlPreview(code,'HTML / code preview'));
    }
    head.appendChild(tools);wrap.appendChild(head);wrap.appendChild(highlighter(code,lang));target.appendChild(wrap);
  }
  function appendPlain(target,text) {if(!text)return;const div=document.createElement('div');div.className='message-copy';div.textContent=String(text);target.appendChild(div);}
  function renderRichText(target, text) {
    const source=String(text??'');
    const trimmed=source.trim();
    if(trimmed && /^\s*(?:<!doctype html|<html(?:\s|>))/i.test(trimmed) && !trimmed.includes('```')) {addCodeBlock(target,'html',trimmed);return;}
    const fence=/```([^\n`]*)\n([\s\S]*?)```/g;let last=0,match;
    while((match=fence.exec(source))!==null){appendPlain(target,source.slice(last,match.index));const lang=(match[1]||'').trim().split(/\s+/)[0];addCodeBlock(target,lang,match[2].replace(/\n$/,''));last=fence.lastIndex;}
    appendPlain(target,source.slice(last));
  }
  function renderOneMessage(m,index) {
    const outer=document.createElement('article');outer.className=`message ${m.role}`;
    if(m.status==='thinking') {outer.className='thinking-row';const orb=document.createElement('span');orb.className='thinking-orb';orb.textContent='MX';const copy=document.createElement('span');copy.className='thinking-copy';copy.textContent=m.statusText||'Routing your request';const dots=document.createElement('span');dots.className='thinking-dots';for(let i=0;i<3;i++)dots.append(document.createElement('i'));copy.append(dots);outer.append(orb,copy);return outer;}
    const avatar=document.createElement('div');avatar.className='message-avatar';avatar.textContent=m.role==='user'?'YOU':'MX';
    const body=document.createElement('div');body.className='message-body';const label=document.createElement('div');label.className='message-label';const who=document.createElement('span');who.textContent=m.role==='user'?'YOU':'MAD X';label.appendChild(who);if(m.meta){const small=document.createElement('small');small.textContent=m.meta;label.appendChild(small);}body.appendChild(label);
    const bubble=document.createElement('div');bubble.className='message-bubble';renderRichText(bubble,m.display??m.content??'');body.appendChild(bubble);
    if(m.files?.length){const chips=document.createElement('div');chips.className='attached-files';m.files.forEach(f=>{const c=document.createElement('span');c.className='attachment-chip';c.textContent=`▤ ${f.name} · ${formatBytes(f.size)}`;chips.appendChild(c);});body.appendChild(chips);}
    if(m.role==='assistant' && m.content && !m.status){const acts=document.createElement('div');acts.className='message-actions';const cp=document.createElement('button');cp.className='message-action';cp.type='button';cp.textContent='Copy answer';cp.addEventListener('click',()=>copyText(m.content,cp));acts.appendChild(cp);const dl=document.createElement('button');dl.className='message-action';dl.type='button';dl.textContent='Download .txt';dl.addEventListener('click',()=>downloadText(`mad-x-answer-${index+1}.txt`,m.content));acts.appendChild(dl);body.appendChild(acts);}
    if(m.meta && m.role==='assistant'){const md=document.createElement('div');md.className='message-metadata';md.textContent=m.meta;body.appendChild(md);}
    outer.append(avatar,body);return outer;
  }
  function renderChat() {
    const stream=$('chat-stream');stream.replaceChildren();const has=state.messages.length>0;$('welcome').classList.toggle('hidden',has);
    state.messages.forEach((m,i)=>stream.appendChild(renderOneMessage(m,i)));
    if(has)stream.scrollTop=stream.scrollHeight;
  }

  function fileExtension(name){const s=String(name||'').toLowerCase();if(!s.includes('.'))return s==='dockerfile'?'dockerfile':'';return s.split('.').pop()||'';}
  function isTextFile(file){const ext=fileExtension(file.name);return TEXT_EXT.has(ext)||['Dockerfile','Makefile'].includes(file.name);}
  function renderPending() {
    const box=$('pending-files');box.replaceChildren();box.hidden=!state.pendingFiles.length;
    state.pendingFiles.forEach((file,idx)=>{const chip=document.createElement('div');chip.className='attachment-chip';const name=document.createElement('span');name.textContent=`${file.name} · ${formatBytes(file.size)}`;const remove=document.createElement('button');remove.type='button';remove.textContent='×';remove.setAttribute('aria-label',`Remove ${file.name}`);remove.addEventListener('click',()=>{state.pendingFiles.splice(idx,1);renderPending();});chip.append(name,remove);box.appendChild(chip);});
  }
  function addPendingFiles(files) {
    const incoming=Array.from(files||[]);const seen=new Set(state.pendingFiles.map(f=>`${f.name}:${f.size}:${f.lastModified}`));
    for(const file of incoming){if(seen.has(`${file.name}:${file.size}:${file.lastModified}`))continue;if(file.size===0){toast(`${file.name} is empty and was skipped.`);continue;}if(file.size>100*1024*1024){toast(`${file.name} exceeds the 100 MB browser guard.`);continue;}state.pendingFiles.push(file);}
    if(state.pendingFiles.length>12){state.pendingFiles=state.pendingFiles.slice(0,12);toast('A maximum of 12 files can be attached to one message.');}renderPending();
  }
  async function uploadRawFile(file) {
    const maxMB=Number(state.health.max_upload_mb||25);if(file.size>maxMB*1024*1024)throw new Error(`${file.name} is over the server's ${maxMB} MB upload limit.`);
    const data=await apiJson('/v1/files/upload',{method:'POST',headers:{'Content-Type':file.type||'application/octet-stream','X-File-Name':encodeURIComponent(file.name)},body:file});
    return data;
  }
  async function processPendingFiles(files) {
    const fileMeta=[];const textParts=[];
    for(let i=0;i<files.length;i++){
      const file=files[i];setStatus('chat-status',`Uploading ${i+1}/${files.length}: ${file.name}…`);
      const meta=await uploadRawFile(file);fileMeta.push(meta);
      if(isTextFile(file)&&file.size<=1024*1024&&textParts.length<6){
        try{let content=await file.text();if(content.length>26000)content=content.slice(0,26000)+'\n[truncated locally at 26,000 characters]';const lang=fileExtension(file.name)||'text';textParts.push(`ATTACHMENT TEXT — ${file.name}\n\`\`\`${lang}\n${content}\n\`\`\``);}catch(_){textParts.push(`ATTACHMENT — ${file.name} uploaded as ${meta.mime_type}, but browser text decoding failed.`);}
      }else{textParts.push(`ATTACHMENT FILE — ${file.name} (${meta.mime_type}, ${formatBytes(file.size)}, file id ${meta.id}). The file is stored in the MAD X file library. Only inspect its binary contents if the selected model/provider or an enabled parser supports that format; do not assume the model can access the stored id automatically.`);}
    }
    state.files=[...fileMeta,...state.files.filter(old=>!fileMeta.some(f=>f.id===old.id))];renderFileList();
    return {meta:fileMeta,context:textParts.join('\n\n')};
  }

  async function sendMessage(raw) {
    const text=String(raw??$('prompt').value).trim();const files=state.pendingFiles.slice();if(!text&&!files.length)return;if(state.busy)return;
    state.busy=true;$('send-button').disabled=true;$('prompt').disabled=true;$('attach-button').disabled=true;
    const userDisplay=[text||'Please inspect the attached file(s).', ...(files.length?['Attachments: '+files.map(f=>f.name).join(', ')]:[])].join('\n\n');
    state.messages.push({role:'user',content:text||'Please inspect the attached file(s).',display:userDisplay,files:files.map(f=>({name:f.name,size:f.size}))});
    $('prompt').value='';resizePrompt();state.pendingFiles=[];renderPending();
    const assistant={role:'assistant',content:'',status:'thinking',statusText:'Warming up the selected route'};state.messages.push(assistant);renderChat();saveHistory();
    try {
      let finalPrompt=text||'Please inspect the attached file(s) and summarize what can be determined from their metadata/content.';
      if(files.length){const uploaded=await processPendingFiles(files);if(uploaded.context)finalPrompt+='\n\n'+uploaded.context;assistant.statusText='Routing prompt with attachment context';renderChat();}
      const msgs=state.messages.filter(m=>m!==assistant&&['user','assistant'].includes(m.role)).slice(-16).map(m=>({role:m.role,content:m.role==='user'?(m===state.messages.filter(x=>x.role==='user').at(-1)?finalPrompt:(m.content||m.display||'')):(m.content||'')})).filter(m=>String(m.content||'').trim());
      if(!msgs.length)msgs.push({role:'user',content:finalPrompt});else msgs[msgs.length-1].content=finalPrompt;
      const selected=$('chat-model').value||'auto';
      const data=await apiJson('/v1/chat/completions',{method:'POST',body:JSON.stringify({model:selected,messages:msgs,temperature:0.65,max_tokens:4096,stream:false})});
      assistant.status='';assistant.content=data.choices?.[0]?.message?.content||'The selected route returned no text.';assistant.meta=`${data.model||selected}${data.madex?.fallback_used?' · fallback':''}`;
      setStatus('chat-status','Response received. Code blocks can be copied, downloaded, or previewed.','success');
    }catch(err){assistant.status='';assistant.content=`The request could not complete.\n\n${err.message}\n\nYour prompt is still in this conversation. Try another configured free route or check Settings.`;assistant.meta=err.status===401?'Access required':'Request failed';setStatus('chat-status',err.message,'error');if(err.status===401)toast('Sign in with Google or enter the app access token in Settings.');}
    finally{state.busy=false;$('send-button').disabled=false;$('prompt').disabled=false;$('attach-button').disabled=false;renderChat();saveHistory();$('prompt').focus({preventScroll:true});}
  }
  $('chat-form').addEventListener('submit',e=>{e.preventDefault();sendMessage($('prompt').value);});
  $('prompt').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendMessage($('prompt').value);}});
  $('prompt').addEventListener('input',resizePrompt);
  function resizePrompt(){const t=$('prompt');t.style.height='auto';t.style.height=`${Math.min(t.scrollHeight,240)}px`;}
  $('attach-button').addEventListener('click',()=>$('file-input').click());
  $('file-input').addEventListener('change',()=>{addPendingFiles($('file-input').files);$('file-input').value='';});
  $('new-chat').addEventListener('click',clearChat);
  $('open-agents').addEventListener('click',()=>{if($('prompt').value.trim())$('task-prompt').value=$('prompt').value.trim();navigate('agents');});
  document.querySelectorAll('[data-prompt]').forEach(btn=>btn.addEventListener('click',()=>{$('prompt').value=btn.dataset.prompt;resizePrompt();$('prompt').focus();}));
  $('mobile-menu').addEventListener('click',()=>$('sidebar').classList.toggle('open'));
  $('google-open').addEventListener('click',()=>navigate('settings'));
  $('account-action').addEventListener('click',()=>navigate('settings'));

  function routeReady(row){if(row.route_kind==='official_api')return row.auth_configured===true;if(row.route_kind==='local')return true;if(row.route_kind==='g4f_community')return !!state.health.g4f_installed&&!String(row.availability||'').includes('not detected');return !!row.free_tier&&row.auth_configured===true;}
  function displayRoute(row){const suffix=row.free_tier?' · free tier':row.route_kind==='g4f_community'?' · community / experimental':'';const ready=routeReady(row);return `${row.provider} · ${row.model}${suffix}${ready?'':' · needs setup'}`;}
  function fillSelect(select,items,current,includeAuto=false){if(!select)return;select.replaceChildren();if(includeAuto){const opt=document.createElement('option');opt.value='auto';opt.textContent=state.health.g4f_installed?'Auto · community route':'Auto · experimental (requires g4f)';select.appendChild(opt);}for(const row of items){const opt=document.createElement('option');opt.value=row.id;opt.textContent=displayRoute(row);opt.dataset.ready=String(routeReady(row));select.appendChild(opt);}if(current&&[...select.options].some(o=>o.value===current))select.value=current;}
  function updateEngineUI(){const row=state.catalogRows.find(r=>r.id===$('chat-model').value);if(row){$('active-engine').textContent=row.provider;$('active-model-note').textContent=`${row.model} · ${row.free_tier?'free-tier route':row.route_kind||'provider route'} · ${routeReady(row)?'configured':'may need setup'}`;$('route-chip').textContent=row.free_tier?'FREE ROUTE':'MODEL ROUTE';}else{$('active-engine').textContent=$('chat-model').value==='auto'?'Auto route':'Model routing';$('active-model-note').textContent=state.health.g4f_installed?'Community Auto route is experimental and may be unavailable.':'Select a configured provider route from Settings.';$('route-chip').textContent='AUTO';}}
  function updateFallbackOptions(){
    const fallback=$('fallback-route'), primary=$('task-routes');if(!fallback||!primary)return;
    const keep=fallback.value, selected=new Set(Array.from(primary.selectedOptions).map(o=>o.value));
    fallback.replaceChildren();const blank=document.createElement('option');blank.value='';blank.textContent='Auto-pick free-first backup';fallback.appendChild(blank);
    state.freeReadyRoutes.filter(row=>!selected.has(row.id)).forEach(row=>{const opt=document.createElement('option');opt.value=row.id;opt.textContent=`${row.provider} · ${row.model}`;fallback.appendChild(opt);});
    if(state.health.g4f_installed&&!selected.has('auto')){const opt=document.createElement('option');opt.value='auto';opt.textContent='Auto · g4f community adapter (experimental)';fallback.appendChild(opt);}
    if([...fallback.options].some(o=>o.value===keep))fallback.value=keep;
  }
  function renderProviderCatalog(){const box=$('provider-catalog');box.replaceChildren();const rows=state.catalogRows.filter(r=>r.type==='text');if(!rows.length){const empty=document.createElement('div');empty.className='empty-library';empty.innerHTML='<span>✧</span><b>Provider catalog unavailable</b><small>Enter the gateway token, sign in, or refresh.</small>';box.appendChild(empty);return;}const providers=new Map();for(const row of rows){const current=providers.get(row.provider)||{provider:row.provider,free:row.free_tier,ready:routeReady(row),count:0,route_kind:row.route_kind,models:[]};current.count++;current.free=current.free||row.free_tier;current.ready=current.ready||routeReady(row);current.models.push(row.model);providers.set(row.provider,current);}Array.from(providers.values()).sort((a,b)=>Number(b.ready)-Number(a.ready)||a.provider.localeCompare(b.provider)).forEach(p=>{const row=document.createElement('div');row.className='provider-row';const symbol=document.createElement('span');symbol.className='provider-symbol';symbol.textContent=p.provider.split(/\s+/).map(s=>s[0]).join('').slice(0,2).toUpperCase();const copy=document.createElement('div');copy.className='provider-row-copy';const name=document.createElement('b');name.textContent=p.provider;const small=document.createElement('small');small.textContent=`${p.count} model${p.count===1?'':'s'} · ${p.models.slice(0,3).join(', ')}${p.models.length>3?'…':''}${p.free?' · free tier flag':''}`;copy.append(name,small);const status=document.createElement('span');status.className=`provider-status ${p.ready?'ready':''}`;status.textContent=p.ready?'CONFIGURED':'SETUP';row.append(symbol,copy,status);box.appendChild(row);});}
  async function loadCatalog(){try{const data=await apiJson('/v1/catalog');state.catalogRows=Array.isArray(data.rows)?data.rows:[];state.catalogSource=data.source||'catalog';const textRows=state.catalogRows.filter(r=>r.type==='text');const freeReady=textRows.filter(r=>r.free_tier&&routeReady(r));const sorted=[...textRows].sort((a,b)=>Number(routeReady(b))-Number(routeReady(a))||Number(!!b.free_tier)-Number(!!a.free_tier)||a.provider.localeCompare(b.provider)||a.model.localeCompare(b.model));
      const current=$('chat-model').value;fillSelect($('chat-model'),sorted,current,true);if(!current||!Array.from($('chat-model').options).some(o=>o.value===current)){const best=freeReady[0]||sorted.find(routeReady)||sorted[0];if(best)$('chat-model').value=best.id;else $('chat-model').value='auto';}updateEngineUI();
      const imageRows=state.catalogRows.filter(r=>r.type==='image');fillSelect($('image-model'),imageRows,$('image-model').value,true);
      const taskSelect=$('task-routes');const prior=new Set(Array.from(taskSelect.selectedOptions).map(o=>o.value));taskSelect.replaceChildren();const usable=sorted.slice(0,180);usable.forEach(row=>{const opt=document.createElement('option');opt.value=row.id;opt.textContent=displayRoute(row);opt.title=row.availability||'';taskSelect.appendChild(opt);});if(!prior.size){const defaults=freeReady.slice(0,6);(defaults.length?defaults:sorted.filter(routeReady).slice(0,6)).forEach(row=>{const opt=[...taskSelect.options].find(o=>o.value===row.id);if(opt)opt.selected=true;});if(!taskSelect.selectedOptions.length&&taskSelect.options.length)taskSelect.options[0].selected=true;}else [...taskSelect.options].forEach(o=>o.selected=prior.has(o.value));
      state.freeReadyRoutes=freeReady;updateFallbackOptions();
      $('model-count').textContent=String(textRows.length);$('free-count').textContent=String(textRows.filter(r=>r.free_tier).length);$('route-summary').textContent=freeReady.length?`${freeReady.length} free routes configured`:(state.health.g4f_installed?'Community adapter available · experimental':'Add a free-tier key or configure a local model');$('catalog-age').textContent='CATALOG';renderProviderCatalog();
    }catch(err){if(err.status===401){$('route-summary').textContent='Sign in or add the app access token';}else $('route-summary').textContent='Provider catalog temporarily unavailable';setStatus('token-status',err.message,'error');}}
  $('chat-model').addEventListener('change',updateEngineUI);$('refresh-catalog').addEventListener('click',loadCatalog);$('task-routes').addEventListener('change',()=>{const selected=Array.from($('task-routes').selectedOptions);if(selected.length>6){selected[selected.length-1].selected=false;toast('Select up to six primary routes.');}updateFallbackOptions();});
  async function loadHealth(){try{state.health=await apiJson('/health');$('server-label').textContent=state.health.status==='ok'?'Gateway online':'Gateway check';updateAccountUI();}catch(_){$('server-label').textContent='Gateway not reachable';state.health={};} }

  function renderAgentResults(data){const box=$('agent-results');box.replaceChildren();const head=document.createElement('div');head.className='agent-result-head';const title=document.createElement('h2');title.textContent='Run report';const stat=document.createElement('span');stat.className='chip chip-green';stat.textContent=`${data.agents_completed||0}/6 AGENTS SUCCESS`;head.append(title,stat);box.appendChild(head);
    const summary=document.createElement('div');summary.className='panel';summary.style.padding='13px 15px';summary.style.marginBottom='12px';const summaryText=document.createElement('div');summaryText.className='message-copy';summaryText.textContent=`Task lane: ${data.task_plan?.agent_info?.label||data.task_plan?.agent||'General'} · Fallbacks used: ${data.fallbacks_used||0} · Free fallback route: ${data.fallback_route||'none configured'}\n\n${data.note||''}`;summary.appendChild(summaryText);box.appendChild(summary);
    const grid=document.createElement('div');grid.className='agent-result-grid';(data.agents||[]).forEach(a=>{const card=document.createElement('article');card.className=`agent-result-card ${a.ok?'ok':'failed'}`;const top=document.createElement('header');const nameWrap=document.createElement('div');const name=document.createElement('h3');name.textContent=a.agent||'Agent';const route=document.createElement('small');route.textContent=`${a.resolved||a.route||'route unavailable'}${a.fallback_used?` · fallback from ${a.route}`:''}`;nameWrap.append(name,route);const pill=document.createElement('span');pill.className=`result-pill ${a.ok?'':'failed'}`;pill.textContent=a.ok?(a.fallback_used?'FALLBACK OK':'OK'):'FAILED';top.append(nameWrap,pill);card.appendChild(top);
      if(a.ok){const text=document.createElement('p');text.textContent=a.text||'';card.appendChild(text);const actions=document.createElement('div');actions.className='message-actions';const copy=document.createElement('button');copy.className='message-action';copy.textContent='Copy report';copy.addEventListener('click',()=>copyText(a.text,copy));actions.appendChild(copy);card.appendChild(actions);}else{const msg=document.createElement('p');msg.textContent=a.error?.message||a.primary_error?.message||'Agent unavailable';card.appendChild(msg);if(a.primary_error&&a.fallback_route){const primary=document.createElement('small');primary.textContent=`Primary failed: ${a.primary_error.message}`;card.appendChild(primary);}}grid.appendChild(card);});box.appendChild(grid);
    if(data.professional_prompt){const details=document.createElement('details');details.className='panel';details.style.padding='12px 14px';details.style.marginTop='12px';const summary=document.createElement('summary');summary.textContent='View professionalized prompt';summary.style.cursor='pointer';summary.style.fontSize='10px';const pre=document.createElement('pre');pre.style.whiteSpace='pre-wrap';pre.style.font='10px/1.7 DM Mono,monospace';pre.style.color='#b7ddc6';pre.textContent=data.professional_prompt;details.append(summary,pre);box.appendChild(details);}
    if(data.final){const final=document.createElement('div');final.className='panel';final.style.padding='14px';final.style.marginTop='12px';const finHead=document.createElement('div');finHead.className='agent-result-head';const h=document.createElement('h2');h.textContent='Final integrated response';const dl=document.createElement('button');dl.className='button button-quiet';dl.textContent='Download result';dl.addEventListener('click',()=>downloadText('mad-x-agent-result.md',data.final,'text/markdown;charset=utf-8'));finHead.append(h,dl);const rich=document.createElement('div');rich.className='message-bubble';renderRichText(rich,data.final);final.append(finHead,rich);box.appendChild(final);}
  }
  $('run-team').addEventListener('click',async()=>{
    const task=$('task-prompt').value.trim();if(!task){setStatus('agent-status','Enter your task first.','error');return;}if(state.busy)return;
    const routes=Array.from($('task-routes').selectedOptions).map(o=>o.value).slice(0,6);if(routes.length>6){toast('Only six routes can be selected.');return;}
    state.busy=true;const btn=$('run-team');btn.disabled=true;btn.textContent='⟡ Distributing work…';setStatus('agent-status','Professionalizing the prompt, assigning specialists and preparing the fallback route…');$('agent-results').replaceChildren();
    try{const data=await apiJson('/v1/tasks/run',{method:'POST',body:JSON.stringify({task,routes,fallback_route:$('fallback-route').value||null,temperature:Number($('task-temperature').value),max_tokens:Number($('task-tokens').value)})});renderAgentResults(data);setStatus('agent-status',`Complete · ${data.agents_completed}/6 agents returned results · ${data.fallbacks_used} fallback(s) used.`,'success');$('agent-results').scrollIntoView({behavior:'smooth',block:'start'});}catch(err){setStatus('agent-status',`Task pipeline failed: ${err.message}`,'error');if(err.status===401)toast('Sign in or enter the app access token in Settings.');}
    finally{state.busy=false;btn.disabled=false;btn.innerHTML='<span>⟡</span> Run six-agent pipeline <span class="button-arrow">↗</span>';}
  });

  $('generate-image').addEventListener('click',async()=>{const prompt=$('image-prompt').value.trim();if(!prompt){setStatus('image-status','Write an image prompt first.','error');return;}const btn=$('generate-image');btn.disabled=true;btn.textContent='Generating image…';setStatus('image-status','Calling the selected image route. This can take a moment.');$('image-result').replaceChildren();try{const data=await apiJson('/v1/images/generations',{method:'POST',body:JSON.stringify({prompt,model:$('image-model').value||'auto',size:$('image-size').value||'1024x1024',response_format:'url',n:1})});const item=data.data?.[0]||data.image||data;const url=item.url||(item.b64_json?`data:image/png;base64,${item.b64_json}`:null);if(!url)throw new Error('Provider returned no image URL or image data.');const img=document.createElement('img');img.src=url;img.alt='Generated image';img.loading='lazy';$('image-result').appendChild(img);const meta=document.createElement('div');meta.className='result-meta';meta.textContent=`Route: ${data.model||$('image-model').value} · ${data.fallback_used?'fallback used':'requested route'}`;$('image-result').appendChild(meta);if(url.startsWith('http')){const a=document.createElement('a');a.href=url;a.target='_blank';a.rel='noopener noreferrer';a.className='button button-quiet';a.style.marginTop='8px';a.textContent='Open original image ↗';$('image-result').appendChild(a);}setStatus('image-status','Image result received from the selected provider.','success');}catch(err){setStatus('image-status',err.message,'error');}finally{btn.disabled=false;btn.innerHTML='Generate image <span class="button-arrow">↗</span>';}});
  $('generate-video').addEventListener('click',async()=>{const prompt=$('video-prompt').value.trim();if(!prompt){setStatus('video-status','Describe the video you want first.','error');return;}const btn=$('generate-video');btn.disabled=true;btn.textContent='Checking configured provider…';setStatus('video-status','Only a real configured video-generation provider can return a playable result.');try{const data=await apiJson('/v1/video/generate',{method:'POST',body:JSON.stringify({prompt,model:'auto',aspect_ratio:'16:9'})});const url=data.video_url||data.url||data.output?.url;if(!url)throw new Error('The selected provider returned no video URL. No MP4 was fabricated.');const video=document.createElement('video');video.controls=true;video.playsInline=true;video.src=url;video.preload='metadata';$('local-video-preview').replaceChildren(video);setStatus('video-status','Video returned by configured provider.','success');}catch(err){setStatus('video-status',err.message,'error');}finally{btn.disabled=false;btn.innerHTML='Try configured video provider <span>▷</span>';}});
  $('video-file-input').addEventListener('change',async()=>{const file=$('video-file-input').files?.[0];if(!file)return;if(!file.type.startsWith('video/')&&!/\.(mp4|m4v|mov|webm)$/i.test(file.name)){toast('Choose a video file.');return;}if(file.size>100*1024*1024){toast('Local preview is limited to 100 MB.');return;}const url=URL.createObjectURL(file);const video=document.createElement('video');video.controls=true;video.playsInline=true;video.preload='metadata';video.src=url;video.setAttribute('aria-label',`Preview ${file.name}`);$('local-video-preview').replaceChildren(video);const meta=document.createElement('div');meta.className='result-meta';meta.textContent=`Local preview: ${file.name} · ${formatBytes(file.size)} · not uploaded`; $('local-video-preview').appendChild(meta);});

  $('browse-files').addEventListener('click',()=>$('library-file-input').click());$('library-file-input').addEventListener('change',async()=>{const files=Array.from($('library-file-input').files||[]);$('library-file-input').value='';if(!files.length)return;await uploadToLibrary(files);});$('refresh-files').addEventListener('click',loadFiles);$('close-file-preview').addEventListener('click',()=>{$('file-preview-area').classList.add('hidden');$('file-preview-content').replaceChildren();});
  async function uploadToLibrary(files){if(state.uploadBusy)return;state.uploadBusy=true;setStatus('token-status','');try{for(let i=0;i<files.length;i++){toast(`Uploading ${i+1}/${files.length}: ${files[i].name}`,5000);await uploadRawFile(files[i]);}await loadFiles();toast(`${files.length} file(s) uploaded to your library.`);}catch(err){toast(err.message,5000);if(err.status===401)navigate('settings');}finally{state.uploadBusy=false;}}
  async function loadFiles(){const box=$('file-list');if(!box)return;try{const data=await apiJson('/v1/files');state.files=data.files||[];renderFileList();}catch(err){box.replaceChildren();const empty=document.createElement('div');empty.className='empty-library';const b=document.createElement('b');b.textContent=err.status===401?'Sign in or enter the app access token':'Could not load file library';const small=document.createElement('small');small.textContent=err.message;empty.append(b,small);box.appendChild(empty);}}
  function renderFileList(){const box=$('file-list');if(!box)return;box.replaceChildren();$('files-count').textContent=String(state.files.length);if(!state.files.length){const empty=document.createElement('div');empty.className='empty-library';const icon=document.createElement('span');icon.textContent='▤';const b=document.createElement('b');b.textContent='Your library is ready';const sm=document.createElement('small');sm.textContent='Upload a file to add it here.';empty.append(icon,b,sm);box.appendChild(empty);return;}
    state.files.forEach(file=>{const row=document.createElement('div');row.className='file-row';const type=document.createElement('span');type.className='file-type-icon';const ext=fileExtension(file.name).slice(0,5)||'FILE';type.textContent=ext;const copy=document.createElement('div');copy.className='file-row-copy';const name=document.createElement('b');name.textContent=file.name;const small=document.createElement('small');small.textContent=`${formatBytes(file.size)} · ${file.mime_type||'application/octet-stream'} · ${formatDate(file.uploaded_at)}`;copy.append(name,small);const actions=document.createElement('div');actions.className='file-row-actions';const preview=document.createElement('button');preview.type='button';preview.textContent='Preview';preview.addEventListener('click',()=>previewStoredFile(file));const dl=document.createElement('button');dl.type='button';dl.textContent='Download';dl.addEventListener('click',()=>downloadStoredFile(file));const del=document.createElement('button');del.type='button';del.textContent='Delete';del.addEventListener('click',()=>deleteStoredFile(file));actions.append(preview,dl,del);row.append(type,copy,actions);box.appendChild(row);});
  }
  async function fileBlob(file){const res=await api(file.download_url||`/v1/files/${file.id}/download`);return res.blob();}
  async function downloadStoredFile(file){try{const blob=await fileBlob(file);const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=file.name;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1500);}catch(err){toast(err.message);}}
  async function previewStoredFile(file){const area=$('file-preview-area'),content=$('file-preview-content');content.replaceChildren();$('preview-title').textContent=file.name;area.classList.remove('hidden');area.scrollIntoView({behavior:'smooth',block:'start'});const busy=document.createElement('div');busy.className='empty-library';busy.textContent='Loading preview…';content.appendChild(busy);try{const blob=await fileBlob(file);content.replaceChildren();const type=String(file.mime_type||'').toLowerCase();const name=file.name.toLowerCase();
      if(type.startsWith('video/')){const video=document.createElement('video');video.controls=true;video.playsInline=true;video.src=URL.createObjectURL(blob);content.appendChild(video);}
      else if(type.startsWith('audio/')){const audio=document.createElement('audio');audio.controls=true;audio.src=URL.createObjectURL(blob);audio.style.width='100%';content.appendChild(audio);}
      else if(type.startsWith('image/')){const img=document.createElement('img');img.src=URL.createObjectURL(blob);img.alt=file.name;content.appendChild(img);}
      else if(type==='text/html'||/\.(html?|svg)$/i.test(name)){const html=await blob.text();const frame=document.createElement('iframe');frame.title='Stored HTML preview';frame.sandbox='allow-scripts';frame.referrerPolicy='no-referrer';frame.srcdoc=secureHtmlForPreview(html);frame.style.height='540px';content.appendChild(frame);const openCode=document.createElement('details');openCode.style.marginTop='12px';const summary=document.createElement('summary');summary.textContent='View source code';const pre=document.createElement('pre');pre.textContent=html;openCode.append(summary,pre);content.appendChild(openCode);}
      else if(type.startsWith('text/')||isTextFile({name:file.name})){const text=await blob.text();const ext=fileExtension(file.name);addCodeBlock(content,ext,text);}
      else if(type==='application/pdf'||name.endsWith('.pdf')){const frame=document.createElement('iframe');frame.title='PDF preview';frame.src=URL.createObjectURL(blob);frame.style.height='540px';content.appendChild(frame);}
      else{const info=document.createElement('div');info.className='empty-library';const b=document.createElement('b');b.textContent='No inline viewer for this format';const sm=document.createElement('small');sm.textContent=`The file is stored intact (${formatBytes(file.size)}). Download it to open it with a compatible application.`;info.append(b,sm);content.appendChild(info);const dl=document.createElement('button');dl.className='button button-primary';dl.textContent='Download file';dl.addEventListener('click',()=>downloadStoredFile(file));content.appendChild(dl);}
    }catch(err){content.replaceChildren();const error=document.createElement('div');error.className='status-line error';error.textContent=err.message;content.appendChild(error);}}
  async function deleteStoredFile(file){if(!confirm(`Delete ${file.name} from this workspace?`))return;try{await api(`/v1/files/${file.id}`,{method:'DELETE'});state.files=state.files.filter(f=>f.id!==file.id);renderFileList();toast('File deleted.');}catch(err){toast(err.message);}}

  async function setupGoogle(){if(state.googleReady||state.googleLoading)return;const clientId=window.MADX_CONFIG?.googleClientId||'';const slot=$('google-button');if(!clientId){slot.replaceChildren();const hint=document.createElement('div');hint.className='settings-copy';hint.style.margin='0';hint.textContent='Google sign-in is not configured yet. Add GOOGLE_CLIENT_ID and SESSION_ENCRYPTION_KEY to the server environment.';slot.appendChild(hint);return;}state.googleLoading=true;try{await ensureGoogleScript();if(!window.google?.accounts?.id)throw new Error('Google Identity Services did not load.');window.google.accounts.id.initialize({client_id:clientId,callback:googleCredentialCallback,auto_select:false,cancel_on_tap_outside:true});window.google.accounts.id.renderButton(slot,{theme:'filled_black',size:'large',shape:'pill',text:'signin_with',width:240,logo_alignment:'left'});state.googleReady=true;}catch(err){slot.replaceChildren();const msg=document.createElement('small');msg.className='status-line error';msg.textContent=err.message;slot.appendChild(msg);}finally{state.googleLoading=false;}}
  async function ensureGoogleScript(){if(window.google?.accounts?.id)return;await new Promise((resolve,reject)=>{const existing=document.getElementById('google-identity-script');if(existing){existing.addEventListener('load',resolve,{once:true});existing.addEventListener('error',reject,{once:true});if(window.google?.accounts?.id)resolve();return;}const script=document.createElement('script');script.id='google-identity-script';script.src='https://accounts.google.com/gsi/client';script.async=true;script.defer=true;script.onload=resolve;script.onerror=()=>reject(new Error('Google sign-in script was blocked or could not load.'));document.head.appendChild(script);});}
  async function googleCredentialCallback(response){try{const data=await fetch('/api/auth/google',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({credential:response.credential})});if(!data.ok)throw new Error(await errorMessage(data));const payload=await data.json();state.user=payload.user||null;updateAccountUI();loadHistory();setStatus('token-status','Google sign-in complete.','success');setStatus('chat-status','Google session connected.','success');toast('Google sign-in successful.');await loadCatalog();}catch(err){toast(err.message,5000);}}
  async function restoreSession(){try{const res=await fetch('/api/me',{credentials:'same-origin'});if(res.ok){state.user=await res.json();updateAccountUI();loadHistory();}}catch(_){} }
  function updateAccountUI(){if(state.user){$('account-name').textContent=state.user.name||state.user.email||'Google account';$('account-subtitle').textContent=state.user.email||'Signed in securely';$('account-avatar').textContent=(state.user.name||state.user.email||'M').trim().charAt(0).toUpperCase();$('google-open').textContent='Account';$('auth-status-chip').textContent='SIGNED IN';$('account-settings-state').textContent=`Signed in as ${state.user.email||state.user.name||'Google user'}.`; }else{$('account-name').textContent='Local workspace';$('account-subtitle').textContent='Sign in to connect an account';$('account-avatar').textContent='M';$('google-open').textContent='Sign in';$('auth-status-chip').textContent=state.health.login_required?'SIGN IN REQUIRED':'OPTIONAL';$('account-settings-state').textContent=state.health.login_required?'Google sign-in or the gateway access token is required.':'No Google session detected.';}}
  $('google-retry').addEventListener('click',setupGoogle);$('signout-button').addEventListener('click',async()=>{try{await fetch('/api/auth/logout',{method:'POST',credentials:'same-origin'});}catch(_){}state.user=null;state.messages=[];state.files=[];renderFileList();updateAccountUI();renderChat();toast('Signed out.');});
  $('save-token').addEventListener('click',async()=>{const value=$('access-token').value.trim();try{if(value)sessionStorage.setItem('madx-app-token',value);else sessionStorage.removeItem('madx-app-token');setStatus('token-status','Testing gateway access…');await loadCatalog();if(state.catalogRows.length){setStatus('token-status','Saved for this browser tab.','success');toast('Access token saved in session storage.');}else setStatus('token-status','Saved, but catalog access was not confirmed. Check the token.','error');}catch(err){setStatus('token-status',err.message,'error');}});
  $('clear-token').addEventListener('click',()=>{try{sessionStorage.removeItem('madx-app-token');}catch(_){}$('access-token').value='';setStatus('token-status','Token cleared from this browser tab.','success');state.catalogRows=[];});
  $('access-token').value=sessionToken();
  $('close-preview').addEventListener('click',()=>{const dlg=$('preview-dialog');if(dlg.open)dlg.close();$('preview-frame').srcdoc='';});$('download-preview').addEventListener('click',()=>downloadText('mad-x-preview.html',state.previewHtml,'text/html;charset=utf-8'));
  $('year').textContent=String(new Date().getFullYear());
  // Initialize the route from the URL, then restore session-local state.
  navigate(pathToPage(location.pathname),false);updateAccountUI();
  (async()=>{await loadHealth();await loadCatalog();await restoreSession();await loadFiles();})();
  document.addEventListener('keydown',e=>{if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'){e.preventDefault();navigate('chat');clearChat();}if(e.key==='Escape'&&$('sidebar').classList.contains('open'))$('sidebar').classList.remove('open');});
})();
