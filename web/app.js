'use strict';
const icons = {
 download:'<path d="M12 3v12m-5-5 5 5 5-5M5 15v5h14v-5"/>',
 grid:'<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
 settings:'<path d="m9 3-1 3-3 1-2 4 2 2v4l4 2 3-1 3 1 4-2v-4l2-2-2-4-3-1-1-3Z"/><circle cx="12" cy="11" r="3"/>',
 link:'<path d="m10 13 4-4m-5 7-2 2a4 4 0 0 1-6-6l4-4a4 4 0 0 1 6 0m2 0 2-2a4 4 0 0 1 6 6l-4 4a4 4 0 0 1-6 0" transform="translate(1 -1)"/>',
 clipboard:'<rect x="5" y="5" width="14" height="16" rx="2"/><rect x="9" y="2" width="6" height="6" rx="1"/>',
 check:'<path d="m5 12 4 4L19 6"/>',
 shield:'<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6Z"/><path d="m8 11 3 3 5-5"/>',
 sliders:'<path d="M4 6h5m5 0h6M4 12h10m5 0h1M4 18h1m5 0h10M9 3v6m5 0v6M5 15v6"/>',
 folder:'<path d="M3 7V5a2 2 0 0 1 2-2h5l3 4h6a2 2 0 0 1 2 2v10H3Z"/><path d="M3 8h9"/>',
 help:'<circle cx="12" cy="12" r="9"/><path d="M9 9a3 3 0 0 1 6 0c0 2-3 2-3 4m0 3h.01"/>',
 power:'<path d="M12 2v10m-6-7a9 9 0 1 0 12 0"/>',
 search:'<circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/>',
 close:'<path d="m6 6 12 12M6 18 18 6"/>',
 image:'<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8" cy="8" r="1.5"/><path d="m3 16 5-5 5 5 3-3 5 5"/>',
 file:'<path d="M5 3h9l5 5v13H5Zm9 0v6h5M8 13h8m-8 4h5"/>'
};
const icon = name => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name] || icons.file}</svg>`;
document.querySelectorAll('[data-icon]').forEach(el => el.innerHTML = icon(el.dataset.icon));
const $ = id => document.getElementById(id);
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
let key = location.hash.slice(1) || sessionStorage.getItem('pinboard-key') || '';
if(key) sessionStorage.setItem('pinboard-key',key);
history.replaceState(null,'',location.pathname);
let state = {boards:[],job:null}, selectedBoard = null, mediaItems = [], mediaShown = 0, boardSignature = '', currentView = 'home', closed = false, networkFailed = false, toastTimer;
const active = job => job && ['starting','downloading','packing','stopping'].includes(job.status);
const size = n => n < 1048576 ? `${Math.round(n / 1024)} КБ` : n < 1073741824 ? `${(n / 1048576).toFixed(1)} МБ` : `${(n / 1073741824).toFixed(2)} ГБ`;
const plural = (n, forms) => forms[n % 100 > 10 && n % 100 < 20 ? 2 : n % 10 === 1 ? 0 : n % 10 >= 2 && n % 10 <= 4 ? 1 : 2];
const fileCount = n => `${n.toLocaleString('ru-RU')} ${plural(n,['файл','файла','файлов'])}`;
function mediaURL(board,file,save=false){ return '/media?' + new URLSearchParams({board,file,key,...(save?{save:'1'}:{})}); }
function toast(message){ $('toast').textContent = message; $('toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(()=>$('toast').hidden=true,5000); }
async function api(path,data){
  const controller = new AbortController(); const timeout = setTimeout(()=>controller.abort(),20000);
  try {
    const response = await fetch(path,{method:data===undefined?'GET':'POST',headers:{'X-Pinboard-Key':key,'Content-Type':'application/json'},body:data===undefined?undefined:JSON.stringify(data),signal:controller.signal});
    const value = await response.json();
    if(!response.ok) throw new Error(value.error || 'Не удалось выполнить действие.');
    return value;
  } catch(error) {
    if(error instanceof TypeError || error.name==='AbortError') throw new Error('Нет связи с приложением. Запустите Pinboard снова.');
    throw error;
  } finally {clearTimeout(timeout);}
}
function view(name){
  currentView=name;
  for(const candidate of ['home','library','settings']) $(`${candidate}-view`).hidden=candidate!==name;
  document.querySelectorAll('[data-view]').forEach(button=>button.classList.toggle('active',button.dataset.view===name));
  const titles={home:'Скачать',library:'Библиотека',settings:'Настройки'};
  $('breadcrumb').textContent=titles[name];
  if(name==='library') renderLibrary();
  if(name==='settings') $('output-path').value=state.output||'';
  window.scrollTo({top:0,behavior:'instant'});
}
document.querySelectorAll('[data-view]').forEach(button=>button.addEventListener('click',()=>view(button.dataset.view)));
document.querySelector('.brand').addEventListener('click',event=>{event.preventDefault();view('home');});
$('all-boards').addEventListener('click',()=>view('library'));
function empty(title){return `<div class="empty-state">${title}</div>`;}
function card(board,index){
  const covers=board.covers.map(file=>`<img src="${escapeHTML(mediaURL(board.id,file))}" alt="" loading="lazy">`).join('');
  return `<button class="board-card ${index>1?'recent-extra':''}" data-board="${escapeHTML(board.id)}" aria-label="Открыть ${escapeHTML(board.name)}"><div class="cover-collage">${covers||'<div class="cover-placeholder">'+icon('image')+'</div>'}<span class="cover-count">${icon('image')}${fileCount(board.count)}</span></div><div class="board-title-line"><h3>${escapeHTML(board.name)}</h3><span>↗</span></div><div class="board-meta"><span>${board.source_type==='pin'?'Пин':'Доска'} · ${escapeHTML(board.owner)}</span><span>${size(board.bytes)}</span></div></button>`;
}
function renderBoards(){
  $('nav-count').textContent=state.boards.length;
  $('recent-count').textContent=state.boards.length;
  $('recent-boards').innerHTML=state.boards.length?state.boards.slice(0,3).map(card).join(''):empty('Нет сохранённых файлов');
  renderLibrary();
}
function renderLibrary(){
  const query=$('search').value.trim().toLocaleLowerCase('ru');
  const boards=state.boards.filter(board=>`${board.name} ${board.owner}`.toLocaleLowerCase('ru').includes(query));
  const order=$('sort').value;
  if(order==='name') boards.sort((a,b)=>a.name.localeCompare(b.name,'ru'));
  if(order==='count') boards.sort((a,b)=>b.count-a.count);
  $('library-summary').textContent=`${state.boards.length} ${plural(state.boards.length,['загрузка','загрузки','загрузок'])} · ${fileCount(state.boards.reduce((n,b)=>n+b.count,0))} · ${size(state.boards.reduce((n,b)=>n+b.bytes,0))}`;
  $('all-board-grid').innerHTML=boards.length?boards.map(b=>card(b,0)).join(''):query?empty('Ничего не найдено'):empty('Нет сохранённых файлов');
}
$('search').addEventListener('input',renderLibrary); $('sort').addEventListener('change',renderLibrary);
function renderJob(){
  const job=state.job; $('job-panel').hidden=!job;
  $('download-button').disabled=!!active(job);
  $('download-button').innerHTML=icon('download')+(active(job)?'Идёт загрузка…':'Скачать');
  if(!job)return;
  const statuses={starting:'ПОДКЛЮЧЕНИЕ',downloading:'ЗАГРУЗКА',packing:'СОЗДАЁМ АРХИВ',stopping:'ОСТАНАВЛИВАЕМ',complete:'ГОТОВО',partial:'СОХРАНЕНО С ЗАМЕЧАНИЯМИ',failed:'НЕ УДАЛОСЬ СКАЧАТЬ',cancelled:'ОСТАНОВЛЕНО'};
  $('job-status').textContent=statuses[job.status]||job.status;
  $('job-name').textContent=job.name;
  $('job-message').textContent=job.message;
  $('job-stats').textContent=`${fileCount(job.count)} · ${size(job.bytes)}`;
  $('job-log').textContent=job.lines.join('\n')||'';
  $('job-progress').className='progress '+(active(job)?'indeterminate':job.status);
  $('job-stop').hidden=!['starting','downloading','stopping'].includes(job.status);
  $('job-stop').disabled=job.status==='stopping';
  $('job-open').hidden=!job.board_id||job.count===0;
}
async function refresh(){
  if(closed)return;
  try{
    state=await api('/api/state');
    if(networkFailed){toast('Соединение восстановлено.');networkFailed=false;}
    const signature=JSON.stringify(state.boards);
    if(signature!==boardSignature){boardSignature=signature;renderBoards();}
    if(document.activeElement!==$('output-path')) $('output-path').value=state.output;
    $('version').textContent=state.version;
    renderJob();
  }catch(error){
    if(!networkFailed){toast(error.message);networkFailed=true;}
    $('download-button').disabled=true;
  }
}
async function poll(){await refresh();if(!closed)setTimeout(poll,active(state.job)?1200:4000);}
$('download-form').addEventListener('submit',async event=>{
  event.preventDefault();$('form-error').hidden=true;
  let limit=null;
  if(!$('limit-mode').disabled && $('limit-mode').value==='custom'){
    limit=Number($('limit').value);
    if(!Number.isInteger(limit)||limit<1||limit>100000){$('form-error').textContent='Лимит должен быть целым числом от 1 до 100 000.';$('form-error').hidden=false;return;}
  }
  $('download-button').disabled=true;
  try{
    await api('/api/start',{url:$('board-url').value.trim(),limit,browser:$('browser').value,zip:$('make-zip').checked});
    await refresh();$('job-panel').scrollIntoView({behavior:'smooth',block:'nearest'});
  }catch(error){$('form-error').textContent=error.message;$('form-error').hidden=false;$('download-button').disabled=false;}
});
$('paste').addEventListener('click',async()=>{
  try{$('board-url').value=(await navigator.clipboard.readText()).trim();$('board-url').focus();updateLimitControls();}
  catch{toast('Нажмите Ctrl + V в поле ссылки, чтобы вставить адрес.');$('board-url').focus();updateLimitControls();}
});
function updateLimitControls(){
  const pin=/^(?:https?:\/\/)?(?:[a-z0-9-]+\.)?pinterest\.[a-z.]+\/pin\//i.test($('board-url').value.trim());
  $('limit-mode').disabled=pin;
  $('limit-mode-label').hidden=pin;
  $('limit-label').hidden=pin || $('limit-mode').value!=='custom';
  $('limit').disabled=pin || $('limit-mode').value!=='custom';
}
$('board-url').addEventListener('input',()=>{$('form-error').hidden=true;updateLimitControls();});
$('options-toggle').addEventListener('click',()=>{const show=$('download-options').hidden;$('download-options').hidden=!show;$('options-toggle').setAttribute('aria-expanded',String(show));$('options-chevron').textContent=show?'⌃':'⌄';});
$('limit-mode').addEventListener('change',updateLimitControls);
updateLimitControls();
async function openFolder(board){try{await api('/api/open',board?{board}:{});}catch(error){toast(error.message);}}
$('job-open').addEventListener('click',()=>openFolder(state.job?.board_id));
$('job-stop').addEventListener('click',async()=>{try{await api('/api/stop',{});await refresh();}catch(error){toast(error.message);}});
$('library-folder').addEventListener('click',()=>openFolder());$('settings-folder').addEventListener('click',()=>openFolder());
$('settings-form').addEventListener('submit',async event=>{
  event.preventDefault();const button=event.submitter;button.disabled=true;
  try{await api('/api/settings',{output:$('output-path').value.trim()});$('settings-message').textContent='Сохранено.';await refresh();}
  catch(error){$('settings-message').textContent=error.message;}
  finally{button.disabled=false;}
});
document.querySelectorAll('.board-grid').forEach(grid=>grid.addEventListener('click',async event=>{
  const button=event.target.closest('[data-board]');if(!button)return;
  selectedBoard=state.boards.find(b=>b.id===button.dataset.board);if(!selectedBoard)return;
  $('board-title').textContent=selectedBoard.name;$('board-owner').textContent=(selectedBoard.source_type==='pin'?'Пин':'Доска')+' · '+selectedBoard.owner;
  $('board-details').textContent=`${fileCount(selectedBoard.count)} · ${size(selectedBoard.bytes)}`;
  $('board-zip').hidden=!selectedBoard.zip;
  $('board-zip').href='/zip?'+new URLSearchParams({board:selectedBoard.id,key});
  $('media-grid').innerHTML='<p>Загрузка…</p>';$('load-more').hidden=true;$('board-dialog').showModal();
  const id=selectedBoard.id;
  try{const result=await api('/api/board?'+new URLSearchParams({id}));if(selectedBoard?.id!==id)return;mediaItems=result.items;mediaShown=0;$('media-grid').innerHTML='';showMore();}
  catch(error){$('media-grid').textContent=error.message;}
}));
function showMore(){
  if(!selectedBoard)return;
  const items=mediaItems.slice(mediaShown,mediaShown+48);
  $('media-grid').insertAdjacentHTML('beforeend',items.map(item=>{
    const url=escapeHTML(mediaURL(selectedBoard.id,item.file));const save=escapeHTML(mediaURL(selectedBoard.id,item.file,true));
    let content;
    if(item.kind==='image') content=`<a href="${save}" title="Сохранить ${escapeHTML(item.file)}"><img src="${url}" alt="${escapeHTML(item.title)}" loading="lazy"><p>${escapeHTML(item.title)}</p></a>`;
    else if(item.kind==='video'||item.kind==='audio') content=`<${item.kind} controls preload="metadata" src="${url}"></${item.kind}><a href="${save}"><p>↓ ${escapeHTML(item.file)}</p></a>`;
    else content=`<a href="${save}"><div class="file-icon">${icon('file')}</div><p>${escapeHTML(item.file)}</p></a>`;
    return `<article class="media-item">${content}</article>`;
  }).join(''));
  mediaShown+=items.length;$('load-more').hidden=mediaShown>=mediaItems.length;
}
$('load-more').addEventListener('click',showMore);$('board-folder').addEventListener('click',()=>openFolder(selectedBoard?.id));
$('help').addEventListener('click',()=>$('help-dialog').showModal());
document.querySelectorAll('.close-dialog').forEach(button=>button.addEventListener('click',()=>button.closest('dialog').close()));
document.querySelectorAll('dialog').forEach(dialog=>dialog.addEventListener('click',event=>{if(event.target===dialog){const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)dialog.close();}}));
$('board-dialog').addEventListener('close',()=>{$('media-grid').querySelectorAll('video,audio').forEach(media=>media.pause());});
$('quit').addEventListener('click',async()=>{try{await api('/api/quit',{});closed=true;toast('Pinboard завершил работу. Эту вкладку можно закрыть.');$('download-button').disabled=true;}catch(error){toast(error.message);}});
renderBoards();poll();
