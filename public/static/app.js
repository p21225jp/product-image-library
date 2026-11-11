'use strict';
const $ = (id) => document.getElementById(id);
const icons = {
  team:'<circle cx="9" cy="7" r="3"/><path d="M3 20v-2a6 6 0 0 1 12 0v2M16 4a3 3 0 0 1 0 6M18 14a5 5 0 0 1 3 4v2"/>',
  grid:'<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  box:'<path d="m12 3 9 5v8l-9 5-9-5V8zM3 8l9 5 9-5M12 13v8M7.5 5.5l9 5"/>',
  inbox:'<path d="M4 4h16l2 11v5H2v-5zM2 15h6l2 3h4l2-3h6"/>',
  image:'<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8" cy="8" r="1.5"/><path d="m3 17 6-6 4 4 3-3 5 5"/>',
  upload:'<path d="M12 16V3m-5 5 5-5 5 5M4 15v5a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-5"/>',
  download:'<path d="M12 3v13m-5-5 5 5 5-5M4 16v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4"/>',
  plus:'<path d="M12 5v14M5 12h14"/>',
  search:'<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
  shield:'<path d="M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6z"/><path d="m8 12 3 3 5-6"/>',
  lock:'<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3"/>',
  spark:'<path d="m12 3 2.3 6.7L21 12l-6.7 2.3L12 21l-2.3-6.7L3 12l6.7-2.3zM20 2v4M18 4h4"/>',
  trash:'<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7"/>',
  clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v6l4 2"/>',
  refresh:'<path d="M20 7v5h-5M4 17v-5h5M5.5 7a8 8 0 0 1 13-2L20 8M4 16l1.5 3a8 8 0 0 0 13-2"/>',
  logout:'<path d="M9 3H4v18h5M10 12h11m-4-4 4 4-4 4"/>',
  layers:'<path d="m12 3 10 5-10 5L2 8zM2 12l10 5 10-5M2 16l10 5 10-5"/>',
  database:'<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 4 16 4 16 0V5M4 12c0 4 16 4 16 0"/>',
  check:'<path d="m5 12 4 4L19 6"/>',
  sort:'<path d="M4 6h16M4 12h11M4 18h6"/>',
  info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7v.1"/>'
};
const icon = (name) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name] || icons.image}</svg>`;
document.querySelectorAll('[data-icon]').forEach(el => {el.innerHTML = icon(el.dataset.icon);});
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const state = {view:'library', status:null, images:[], products:[], selected:new Set(), offset:0, total:0, uploadFiles:[], uploading:false, request:0, productRequest:0, navigationRequest:0, productCode:'', productCategory:'', productOffset:0, productPageSize:20, productTotal:0, productLoading:false, productError:false};
const bytes = number => number >= 1024 ** 3 ? `${(number / 1024 ** 3).toFixed(2)} GB` : number >= 1024 ** 2 ? `${(number / 1024 ** 2).toFixed(1)} MB` : `${(number / 1024).toFixed(1)} KB`;
const date = stamp => new Date(stamp * 1000).toLocaleString('zh-CN', {hour12:false});
const splitTags = value => value.split(/[,，]/).map(item => item.trim()).filter(Boolean);
const debounce = (fn, delay=250) => {let timeout; const run=(...args) => {clearTimeout(timeout); timeout=setTimeout(() => fn(...args), delay);};run.cancel=()=>clearTimeout(timeout);return run;};
function toast(message, error=false) {const el=document.createElement('div');el.className='toast'+(error?' error':'');el.textContent=message;$('toast-container').append(el);setTimeout(()=>el.remove(),5000);}
async function api(path, options={}) {
  const headers = {...options.headers};
  if (options.body && !(options.body instanceof FormData)) headers['Content-Type']='application/json';
  const response = await fetch(path, {...options, headers});
  if (!response.ok) {
    let result={};try {result=await response.json();}catch {}
    if (response.status===401 && !['/api/login','/api/setup'].includes(path)) {await boot();}
    const detail=result.detail;const error=new Error(typeof detail==='string'?detail:response.status===422?'请检查必填项和输入长度。':`请求失败（${response.status}）`);error.status=response.status;throw error;
  }
  return response.json();
}
const guarded = fn => async (...args) => {try {return await fn(...args);} catch(error){toast(error.message,true);}};
function options(id, values, empty=null) {const select=$(id);select.replaceChildren();if(empty!==null) select.add(new Option(empty,''));values.forEach(value=>select.add(new Option(value,value)));}
async function boot() {
  try {
    state.status=await api('/api/status');$('loading').classList.add('hidden');
    if (!state.status.logged_in) {
      $('token-secret').value='';$('new-token').classList.add('hidden');$('token-scope').value='read';
      $('app').classList.add('hidden');$('auth').classList.remove('hidden');
      document.querySelectorAll('dialog[open]').forEach(dialog=>dialog.close());
      const setup=!state.status.configured;
      $('auth-title').textContent=setup?'建立你的素材空间':'欢迎回来';
      $('auth-description').textContent=setup?'创建一个管理员账号，开始管理产品图片。':'登录后，继续整理你的产品素材。';
      $('auth-submit').innerHTML=setup?'创建并进入 <span>→</span>':'进入素材库 <span>→</span>';
      $('confirm-wrap').classList.toggle('hidden',!setup);$('password-confirm').required=setup;
      $('password').minLength=setup?10:1;$('password').autocomplete=setup?'new-password':'current-password';
      $('auth-error').textContent='';$('auth-submit').disabled=setup&&!state.status.can_setup;
      $('auth-note').textContent=setup?'密码至少 10 位。原图与产品资料将保存到云端。':'账号仅用于这套素材库。请使用独立密码。';
      if (setup&&!state.status.can_setup) {$('auth-description').textContent='云端资料正在准备，请稍后刷新。';}
      return;
    }
    $('auth').classList.add('hidden');$('app').classList.remove('hidden');
    const role=state.status.role;
    const canEdit=role==='admin';
    const isStaff=role==='admin'||role==='staff';
    $('app').classList.toggle('viewer',!isStaff);
    const roleLabel=role==='admin'?'素材管理员':role==='staff'?'内部成员':'外部访客';
    document.querySelector('.profile>span:nth-child(2)>span').textContent=roleLabel;
    // Upload, edit and trash belong to internal accounts; token pages only need staff.
    document.body.classList.toggle('external-view',role==='external');
    document.querySelectorAll('.admin-only').forEach(element=>element.classList.toggle('hidden',!canEdit));
    document.querySelectorAll('.staff-only').forEach(element=>element.classList.toggle('hidden',!isStaff));
    document.querySelectorAll('.internal-only').forEach(element=>element.classList.toggle('hidden',!isStaff));
    document.querySelector('[data-view="trash"]').classList.toggle('hidden',!canEdit);
    if(!isStaff&&!['library','unassigned','products'].includes(state.view))state.view='library';
    for(const prefix of ['filter','upload','detail']) {
      options(prefix+'-kind',state.status.kinds,prefix==='filter'?'全部类型':null);
      options(prefix+'-angle',state.status.angles,prefix==='filter'?'全部角度':null);
      options(prefix+'-background',state.status.backgrounds,prefix==='filter'?'全部背景':null);
    }
    $('upload-background').value='透明';$('server-origin').textContent=location.origin;
    await switchView(state.view);
  } catch(error) {$('loading').innerHTML=`${icon('info')}<p>连接未完成：${escapeHtml(error.message)}</p><button class="button secondary" id="retry-connection">重试</button>`;$('retry-connection').onclick=boot;}
}
$('auth-form').addEventListener('submit',async event=>{
  event.preventDefault();const setup=!state.status.configured;
  if(setup&&$('password').value!==$('password-confirm').value){$('auth-error').textContent='两次输入的密码不一致。';return;}
  $('auth-submit').disabled=true;$('auth-error').textContent='';
  try {await api(setup?'/api/setup':'/api/login',{method:'POST',body:JSON.stringify({username:$('username').value.trim(),password:$('password').value})});$('password').value='';$('password-confirm').value='';await boot();}
  catch(error){$('auth-error').textContent=error.message;}finally{$('auth-submit').disabled=false;}
});
$('logout').onclick=guarded(async()=>{await api('/api/logout',{method:'POST'});invalidateProductOptions();state.selected.clear();$('selection-bar').classList.add('hidden');$('token-secret').value='';$('new-token').classList.add('hidden');await boot();});
const viewInfo={library:['全部图片','YOUR PRODUCT ASSETS','每个产品，都有清晰的素材归属。'],unassigned:['待整理','A LITTLE ORGANIZATION','为这些图片关联产品，让下一次查找更准确。'],products:['产品目录','THE PRODUCT INDEX','用 SKU、名称与别名，建立统一的产品索引。'],integrations:['AI 取图','CONNECT YOUR WORKFLOW','让智能体通过受控接口，找到你需要的素材。'],activity:['操作记录','WORKSPACE ACTIVITY','上传、下载与资料修改，都有迹可循。'],team:['账号管理','TEAM ACCESS','内部成员可派发令牌，外部客户只能凭账号浏览下载。'],trash:['回收站','A SECOND CHANCE','移入回收站的图片仍保留原文件，可随时恢复。']};
function clearPageSearch() {
  delayedImageSearch.cancel();delayedProductSearch.cancel();
  // Responses from the previous page must not restore its search results.
  state.request++;state.productRequest++;
  state.productCode='';state.productCategory='';state.offset=0;state.productOffset=0;
  state.images=[];state.products=[];state.total=0;state.productTotal=0;state.productLoading=false;state.productError=false;
  $('search').value='';$('product-search').value='';$('product-filter-category').value='';
  for(const key of ['kind','angle','background','category'])$('filter-'+key).value='';
  for(const id of ['clear-search','reset-filters','reset-product-filter','empty','pagination'])$(id).classList.add('hidden');
  $('image-grid').innerHTML='';$('product-table').innerHTML='';$('result-count').textContent='正在加载…';
  renderProductPagination();
}
async function switchView(view, {productCode=''}={}) {
  const staffNow=state.status.role==='admin'||state.status.role==='staff';
  if(!staffNow&&['integrations','activity','team','trash'].includes(view))view='library';
  if(state.view==='integrations'&&view!=='integrations') {$('token-secret').value='';$('new-token').classList.add('hidden');}
  const navigation=++state.navigationRequest;
  clearPageSearch();
  if(view==='library'&&productCode){state.productCode=productCode;$('search').value=productCode;}
  state.view=view;state.offset=0;state.selected.clear();renderSelection();
  const [title,eyebrow,description]=viewInfo[view];$('breadcrumb-current').textContent=title;$('page-title').innerHTML=escapeHtml(title)+'<span class="title-dot">.</span>';$('page-eyebrow').textContent=eyebrow;$('page-description').textContent=description;
  document.querySelectorAll('.nav-item').forEach(button=>button.classList.toggle('active',button.dataset.view===view));
  const isLibrary=['library','unassigned','trash'].includes(view);
  $('library-view').classList.toggle('hidden',!isLibrary);$('products-view').classList.toggle('hidden',view!=='products');$('integrations-view').classList.toggle('hidden',view!=='integrations');$('activity-view').classList.toggle('hidden',view!=='activity');$('team-view').classList.toggle('hidden',view!=='team');
  // Internal members may read, download, upload and organise; deleting stays with the administrator.
  const canUpload=state.status.role==='admin'||state.status.role==='staff';
  $('open-upload').classList.toggle('hidden',!canUpload||['integrations','activity','trash'].includes(view));$('new-product').classList.toggle('hidden',!canUpload||['integrations','activity','trash'].includes(view));$('select-page').classList.remove('hidden');
  await loadOverview();
  if(navigation!==state.navigationRequest)return;
  renderSelection();if(isLibrary) await loadImages(); else if(view==='products'){await loadProductCategories();if(navigation!==state.navigationRequest)return;await loadProducts();} else if(view==='integrations') await loadTokens(); else if(view==='team') await loadTeam(); else await loadAudit();
}
// Delegate on the whole sidebar: some entries (账号管理) sit outside <nav>.
document.querySelector('.sidebar').addEventListener('click',event=>{const button=event.target.closest('[data-view]');if(button)guarded(switchView)(button.dataset.view);});
$('refresh').onclick=guarded(async()=>{invalidateProductOptions();await loadOverview();if(['library','unassigned','trash'].includes(state.view))await loadImages();else if(state.view==='products'){await loadProductCategories();await loadProducts();}else if(state.view==='activity')await loadAudit();else if(state.view==='team')await loadTeam();else await loadTokens();toast('已刷新');});
async function loadOverview() {
  const result=await api('/api/overview');
  for(const [key,label] of [['images','张'],['products','个'],['transparent','张']]) $('stat-'+key).innerHTML=result[key].toLocaleString()+'<small>'+label+'</small>';
  const size=bytes(result.total_bytes).split(' ');$('stat-size').innerHTML=size[0]+'<small>'+size[1]+'</small>';
  $('nav-images').textContent=result.images;$('nav-unassigned').textContent=result.unassigned;$('nav-trash').textContent=result.trash;
  const category=$('filter-category').value;options('filter-category',result.categories,'全部分类');$('filter-category').value=result.categories.includes(category)?category:'';
}
function filterParams() {
  const params=new URLSearchParams({q:$('search').value.trim(),offset:state.offset,limit:48});
  if(state.productCode)params.set('product_code',state.productCode);
  for(const key of ['kind','angle','background','category']) if($('filter-'+key).value)params.set(key,$('filter-'+key).value);
  if(state.view==='unassigned')params.set('unassigned','true');if(state.view==='trash')params.set('trash','true');return params;
}
async function loadImages() {
  const sequence=++state.request;
  const viewer=state.status.role!=='admin'&&state.status.role!=='staff';
  if(viewer&&state.view==='trash')return renderViewerNotice();
  const params=filterParams();const result=await api('/api/images?'+params);
  if(sequence!==state.request||!['library','unassigned','trash'].includes(state.view))return;
  state.images=result.items;state.total=result.total;
  const filtered=!!$('search').value.trim()||['kind','angle','background','category'].some(key=>$('filter-'+key).value);
  $('clear-search').classList.toggle('hidden',!$('search').value);$('reset-filters').classList.toggle('hidden',!filtered);
  $('result-title').textContent=filtered?'搜索结果':state.view==='trash'?'已移除素材':state.view==='unassigned'?'待关联产品':'所有素材';$('result-count').textContent=result.total+' 张图片';
  $('image-grid').innerHTML=result.items.map(item=>`<article class="image-card ${state.selected.has(item.id)?'selected':''}" data-image="${item.id}"><label class="card-select"><input type="checkbox" data-select="${item.id}" aria-label="选择 ${escapeHtml(item.original_name)}" ${state.selected.has(item.id)?'checked':''}></label><span class="card-kind">${escapeHtml(item.kind)}</span><button class="card-preview ${item.has_alpha?'checker':''}" data-detail="${item.id}" aria-label="查看 ${escapeHtml(item.original_name)}"><img src="${item.thumbnail_url}" alt="${escapeHtml(item.product_name||item.original_name)}" loading="lazy"></button><div class="card-body"><div class="card-code">${escapeHtml(item.product_code||'待关联产品')}</div><h3 title="${escapeHtml(item.product_name||item.original_name)}">${escapeHtml(item.product_name||item.original_name)}</h3><div class="card-bottom"><span>${item.width} × ${item.height} · ${item.extension.toUpperCase()}</span>${state.view==='trash'?`<button class="restore" data-restore="${item.id}">恢复图片</button>`:`<button data-download="${item.id}" aria-label="下载 ${escapeHtml(item.original_name)}">${icon('download')}</button>`}</div></div></article>`).join('');
  const empty=result.items.length===0;$('empty').classList.toggle('hidden',!empty);
  $('empty-upload').classList.toggle('hidden',viewer||filtered||state.view==='trash');
  $('empty-title').textContent=filtered?'没有找到符合条件的图片':state.view==='trash'?'回收站是空的':state.view==='unassigned'?'所有图片都已有归属':'给产品图片一个自己的位置';
  $('empty-description').innerHTML=filtered?'试试完整 SKU、产品别名，或清除部分筛选条件。<br>纯数字搜索只匹配产品 SKU。':state.view==='trash'?'移除的图片会出现在这里，可以恢复到素材库。':state.view==='unassigned'?'后续未关联产品的图片会出现在这里。':'上传第一张图片，关联产品 SKU。<br>下次需要时，一搜就找到。';
  $('empty-upload').innerHTML=icon('plus')+(state.view==='unassigned'?'上传图片':'上传第一张图片');
  $('pagination').classList.toggle('hidden',result.total<=48);$('page-info').textContent=`第 ${Math.floor(state.offset/48)+1} / ${Math.ceil(result.total/48)} 页`;$('prev-page').disabled=state.offset===0;$('next-page').disabled=state.offset+48>=result.total;
}
function renderViewerNotice(){
  // Visitors have no recycle bin; ask the administrator instead of showing an empty library.
  $('image-grid').innerHTML='';$('pagination').classList.add('hidden');$('empty').classList.remove('hidden');
  $('empty-upload').classList.add('hidden');
  $('empty-title').textContent='回收站仅管理员可见';
  $('empty-description').textContent='如需恢复图片，请联系素材库管理员。';
}
function resetFilters(){state.productCode='';$('search').value='';for(const key of ['kind','angle','background','category'])$('filter-'+key).value='';state.offset=0;guarded(loadImages)();}
const delayedImageSearch=debounce(()=>{state.productCode='';state.offset=0;guarded(loadImages)();});
$('search').oninput=delayedImageSearch;
for(const key of ['kind','angle','background','category']) $('filter-'+key).onchange=()=>{state.offset=0;guarded(loadImages)();};
$('reset-filters').onclick=resetFilters;$('clear-search').onclick=()=>{state.productCode='';$('search').value='';state.offset=0;guarded(loadImages)();};
$('prev-page').onclick=()=>{state.offset=Math.max(0,state.offset-48);guarded(loadImages)();};$('next-page').onclick=()=>{state.offset+=48;guarded(loadImages)();};
document.addEventListener('keydown',event=>{if(event.key==='/'&&!['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)&&!document.querySelector('dialog[open]')&&!$('app').classList.contains('hidden')&&['library','unassigned','trash'].includes(state.view)){event.preventDefault();$('search').focus();}});
function renderSelection(){const trash=state.view==='trash';$('batch-download').classList.toggle('hidden',trash);$('batch-delete').classList.toggle('hidden',!trash||state.status?.role!=='admin');$('selection-bar').classList.toggle('hidden',state.selected.size===0);$('selected-count').textContent=state.selected.size;document.querySelectorAll('[data-image]').forEach(card=>{const selected=state.selected.has(card.dataset.image);card.classList.toggle('selected',selected);const input=card.querySelector('input');if(input)input.checked=selected;});}
$('image-grid').onchange=event=>{if(event.target.dataset.select){event.target.checked?state.selected.add(event.target.dataset.select):state.selected.delete(event.target.dataset.select);renderSelection();}};
$('select-page').onclick=()=>{const all=state.images.every(item=>state.selected.has(item.id));state.images.forEach(item=>all?state.selected.delete(item.id):state.selected.add(item.id));renderSelection();};$('clear-selection').onclick=()=>{state.selected.clear();renderSelection();};
$('image-grid').onclick=guarded(async event=>{const download=event.target.closest('[data-download]');const restore=event.target.closest('[data-restore]');const detail=event.target.closest('[data-detail]');if(download)await downloadImage(download.dataset.download);else if(restore){await api(`/api/images/${restore.dataset.restore}/restore`,{method:'POST'});toast('图片已恢复');await loadOverview();await loadImages();}else if(detail&&state.view!=='trash')await openDetail(detail.dataset.detail);});
async function downloadResponse(response, fallback){if(!response.ok){let error={};try{error=await response.json();}catch{}throw new Error(error.detail||'下载失败，请重试。');}const blob=await response.blob();const disposition=response.headers.get('Content-Disposition')||'';const match=disposition.match(/filename\*=utf-8''([^;]+)/i);let filename=fallback;if(match){try{filename=decodeURIComponent(match[1]);}catch{}}const link=document.createElement('a');const url=URL.createObjectURL(blob);link.href=url;link.download=filename;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);}
async function downloadImage(id){await downloadResponse(await fetch(`/api/images/${id}/file`),'product-image');toast('已开始下载原图');}
$('batch-download').onclick=guarded(async()=>{if(state.selected.size>100){toast('每次最多打包 100 张，请减少选择。',true);return;}$('batch-download').disabled=true;try{const response=await fetch('/api/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image_ids:[...state.selected]})});await downloadResponse(response,'product-images.zip');toast('已开始下载压缩包');}finally{$('batch-download').disabled=false;}});
function closeDialog(id){if(id==='upload-dialog'&&state.uploading){toast('图片上传中，请等待当前批次完成。');return;}$(id).close();}
document.querySelectorAll('[data-close]').forEach(button=>button.onclick=()=>closeDialog(button.dataset.close));
document.querySelectorAll('dialog').forEach(dialog=>{dialog.addEventListener('click',event=>{if(event.target===dialog){const box=dialog.getBoundingClientRect();if(event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom)closeDialog(dialog.id);}});});
$('upload-dialog').addEventListener('cancel',event=>{if(state.uploading)event.preventDefault();});
function renderProductPagination(){
  const size=state.productPageSize;
  const pages=Math.max(1,Math.ceil(state.productTotal/size));
  const page=Math.floor(state.productOffset/size)+1;
  $('product-results-summary').textContent=state.productLoading?'正在加载产品…':state.productError?'加载未完成，请重试。':`共 ${state.productTotal} 个产品${state.productTotal?` · 当前显示 ${state.productOffset+1}–${Math.min(state.productOffset+state.products.length,state.productTotal)} 个`:''}`;
  $('product-page-info').textContent=state.productError?'—':`第 ${page} / ${pages} 页`;
  $('product-prev-page').disabled=state.productLoading||state.productError||state.productOffset===0;
  $('product-next-page').disabled=state.productLoading||state.productError||state.productOffset+size>=state.productTotal;
  $('product-page-number').max=pages;$('product-page-number').value=page;
  $('product-page-number').disabled=state.productLoading||state.productError||pages===1;
  $('product-page-go').disabled=state.productLoading||state.productError||pages===1;
  $('product-page-size').value=String(size);
  $('product-table').setAttribute('aria-busy',String(state.productLoading));
  $('product-table').classList.toggle('busy',state.productLoading);
  $('product-table').querySelectorAll('button').forEach(button=>button.disabled=state.productLoading);
}
async function loadProducts(){
  const seq=++state.productRequest;
  state.productLoading=true;state.productError=false;renderProductPagination();
  const params=new URLSearchParams({q:$('product-search').value.trim(),category:$('product-filter-category').value,
    limit:state.productPageSize,offset:state.productOffset});
  try{
    const result=await api('/api/products?'+params);
    if(seq!==state.productRequest||state.view!=='products')return;
    if(state.productOffset>0&&state.productOffset>=result.total){
      state.productOffset=Math.max(0,(Math.ceil(result.total/state.productPageSize)-1)*state.productPageSize);
      return await loadProducts();
    }
    state.products=result.items;state.productTotal=result.total;
    $('product-table').innerHTML=`<div class="table-wrap"><table><thead><tr><th>产品 SKU</th><th>产品名称</th><th>产品分类</th><th>图片</th><th>管理</th></tr></thead><tbody>${result.items.map(item=>`<tr><td><span class="code">${escapeHtml(item.code)}</span></td><td><strong>${escapeHtml(item.name)}</strong><div class="subtext">${escapeHtml(item.aliases.join(' · '))}</div></td><td>${escapeHtml(item.category||'未分类')}</td><td>${item.image_count} 张</td><td>${(state.status.role==='admin'||state.status.role==='staff')?`<button class="text-button" data-associate-product="${item.id}">去关联</button> <button class="text-button" data-edit-product="${item.id}">编辑</button>`:''}${state.status.role==='admin'?` <button class="text-button danger" data-delete-product="${item.id}">删除</button>`:''} <button class="text-button" data-product-images="${escapeHtml(item.code)}">查看图片</button></td></tr>`).join('')||'<tr><td colspan="5" class="table-empty">'+(($('product-search').value.trim()||$('product-filter-category').value)?'没有找到符合条件的产品，试试更换分类或清空搜索。':'暂无产品。点击「新建产品」，建立第一个产品索引。')+'</td></tr>'}</tbody></table></div>`;
  }catch(error){
    if(seq!==state.productRequest||state.view!=='products')return;
    state.products=[];state.productError=true;
    $('product-table').innerHTML=`<div class="product-load-error"><p>${escapeHtml(error.message)}</p><button type="button" class="button secondary" data-retry-products>重试加载</button></div>`;
  }finally{if(seq===state.productRequest){state.productLoading=false;renderProductPagination();}}
}
function resetProductPagination(){state.productOffset=0;return loadProducts();}
const delayedProductSearch=debounce(()=>guarded(resetProductPagination)());
$('product-search').oninput=()=>{state.productRequest++;state.productOffset=0;state.productLoading=true;state.productError=false;renderProductPagination();delayedProductSearch();};
async function turnProductPage(offset){
  if(state.productLoading||offset===state.productOffset)return;
  state.productOffset=offset;await loadProducts();
  if(state.view==='products')$('page-title').scrollIntoView({block:'start'});
}
$('product-prev-page').onclick=guarded(()=>turnProductPage(Math.max(0,state.productOffset-state.productPageSize)));
$('product-next-page').onclick=guarded(()=>turnProductPage(state.productOffset+state.productPageSize));
$('product-page-size').onchange=guarded(async()=>{
  const size=Number($('product-page-size').value);if(![20,50,100].includes(size))return;
  state.productPageSize=size;await resetProductPagination();
});
$('product-page-jump').onsubmit=guarded(async event=>{
  event.preventDefault();if(state.productLoading)return;
  const page=Number($('product-page-number').value);
  const pages=Math.max(1,Math.ceil(state.productTotal/state.productPageSize));
  if(!Number.isInteger(page)||page<1||page>pages){toast(`请输入 1 至 ${pages} 之间的页码。`,true);return;}
  await turnProductPage((page-1)*state.productPageSize);
});
async function loadProductCategories(){
  // Reuse the same category list as the image filters, plus a bucket for products without one.
  const choices=await api('/api/categories');
  if(state.productCategory&&state.productCategory!=='未分类'&&!choices.items.includes(state.productCategory)){state.productCategory='';state.productOffset=0;}
  options('product-filter-category',['未分类',...choices.items],'全部分类');
  $('product-filter-category').value=state.productCategory;
  $('reset-product-filter').classList.toggle('hidden',!state.productCategory);
}
$('product-filter-category').onchange=()=>{state.productCategory=$('product-filter-category').value;$('reset-product-filter').classList.toggle('hidden',!state.productCategory);guarded(resetProductPagination)();};
$('reset-product-filter').onclick=()=>{state.productCategory='';$('product-filter-category').value='';$('reset-product-filter').classList.add('hidden');guarded(resetProductPagination)();};
async function openProduct(product=null) {
  const choices=await api('/api/categories');
  $('product-form').reset();setCategoryCreator(false);
  $('edit-product-id').value=product?.id||'';
  $('product-dialog-title').textContent=product?'编辑产品':'新建产品';
  options('product-category',choices.items,'未分类');
  if(product){for(const key of ['code','name','category'])$('product-'+key).value=product[key];$('product-aliases').value=product.aliases.join('，');}
  $('product-dialog').showModal();
}
function setCategoryCreator(visible) {
  $('category-create').classList.toggle('hidden',!visible);
  $('show-category-create').setAttribute('aria-expanded',String(visible));
  $('category-error').textContent='';$('new-category-name').value='';
  if(visible)$('new-category-name').focus();
}
$('show-category-create').onclick=()=>setCategoryCreator(true);
$('cancel-category-create').onclick=()=>setCategoryCreator(false);
async function createCategory() {
  const name=$('new-category-name').value.trim();
  if(!name){$('category-error').textContent='请输入分类名称。';$('new-category-name').focus();return;}
  const controls=[$('create-category'),$('cancel-category-create'),$('new-category-name'),$('product-form').querySelector('[type="submit"]')];
  if($('create-category').disabled)return;
  controls.forEach(control=>control.disabled=true);$('category-error').textContent='';
  try {
    const result=await api('/api/categories',{method:'POST',body:JSON.stringify({name})});
    for(const id of ['product-category','filter-category','product-filter-category']) {
      const select=$(id);if(!Array.from(select.options).some(option=>option.value===result.name))select.add(new Option(result.name,result.name));
    }
    $('product-category').value=result.name;setCategoryCreator(false);
    toast(result.created?'分类已创建并选中':'已选择已有分类');
  } catch(error){$('category-error').textContent=error.message;}
  finally {controls.forEach(control=>control.disabled=false);}
}
$('create-category').onclick=createCategory;
$('new-category-name').onkeydown=event=>{if(event.key==='Enter'&&!event.isComposing){event.preventDefault();createCategory();}};
$('new-product').onclick=guarded(()=>openProduct());
$('product-table').onclick=guarded(async event=>{if(state.productLoading)return;if(event.target.closest('[data-retry-products]')){await loadProducts();return;}const associate=event.target.closest('[data-associate-product]');if(associate){await openAssociation(state.products.find(item=>item.id===associate.dataset.associateProduct));return;}const remove=event.target.closest('[data-delete-product]');if(remove){await openProductDelete(remove.dataset.deleteProduct);return;}const edit=event.target.closest('[data-edit-product]');const view=event.target.closest('[data-product-images]');if(edit)await openProduct(state.products.find(item=>item.id===edit.dataset.editProduct));if(view)await switchView('library',{productCode:view.dataset.productImages});});
const productDeleteUI={preview:null,busy:false};
const productDelete=document.createElement('dialog');
productDelete.id='product-delete';productDelete.className='category-delete';
productDelete.setAttribute('aria-labelledby','product-delete-title');
productDelete.innerHTML=`<div class="category-dialog-heading"><div><span class="eyebrow">DELETE PRODUCT</span><h2 id="product-delete-title">删除产品</h2></div><button type="button" id="product-delete-close" class="dialog-close" aria-label="关闭删除产品确认">×</button></div>`+
  `<p class="category-delete-name" id="product-delete-name"></p><div class="category-delete-counts"><div><strong id="product-delete-images">0</strong><span>张图片回到待整理</span></div><div><strong id="product-delete-trash">0</strong><span>张回收站图片解除关联</span></div></div>`+
  `<div class="category-delete-explanation"><p>产品记录会从目录中移除，图片原文件全部保留，只是不再关联到这个产品。</p><p>图片会回到「待整理」，可以重新关联到其他产品。此操作无法撤销。</p></div>`+
  `<div id="product-delete-error" class="form-error" role="alert"></div><div class="category-delete-footer"><button type="button" id="product-delete-cancel" class="button secondary">取消</button><button type="button" id="product-delete-submit" class="button category-danger">确认删除</button></div>`;
document.body.append(productDelete);
function closeProductDelete(){if(!productDeleteUI.busy)productDelete.close();}
$('product-delete-close').onclick=closeProductDelete;$('product-delete-cancel').onclick=closeProductDelete;
productDelete.addEventListener('close',()=>{productDeleteUI.preview=null;});
productDelete.addEventListener('cancel',event=>{if(productDeleteUI.busy)event.preventDefault();});
async function openProductDelete(id){
  $('product-delete-error').textContent='';$('product-delete-submit').disabled=true;
  $('product-delete-name').textContent='正在读取影响范围…';
  $('product-delete-images').textContent='0';$('product-delete-trash').textContent='0';
  productDelete.showModal();
  try {
    const impact=await api('/api/products/'+id+'/deletion-preview');
    productDeleteUI.preview=impact;
    $('product-delete-name').textContent=`将删除产品「${impact.code} ${impact.name}」`;
    $('product-delete-images').textContent=impact.image_count;
    $('product-delete-trash').textContent=impact.trashed_image_count;
    $('product-delete-submit').disabled=false;
  } catch(error){$('product-delete-error').textContent=error.message;}
}
$('product-delete-submit').onclick=guarded(async()=>{
  const impact=productDeleteUI.preview;if(!impact)return;
  productDeleteUI.busy=true;
  const controls=['product-delete-submit','product-delete-cancel','product-delete-close'];
  controls.forEach(id=>$(id).disabled=true);$('product-delete-submit').textContent='正在删除…';$('product-delete-error').textContent='';
  try {
    await api('/api/products/'+impact.id,{method:'DELETE'});invalidateProductOptions();
    productDeleteUI.busy=false;productDelete.close();
    toast(`产品「${impact.code}」已删除，${impact.image_count} 张图片回到待整理`);
    await loadProductCategories();await loadProducts();await loadOverview();
  } catch(error){$('product-delete-error').textContent=error.message;}
  finally {productDeleteUI.busy=false;controls.forEach(id=>$(id).disabled=false);$('product-delete-submit').textContent='确认删除';}
});
$('product-form').onsubmit=guarded(async event=>{event.preventDefault();if($('create-category').disabled)return;if(!$('category-create').classList.contains('hidden')&&$('new-category-name').value.trim()){toast('请先创建分类，或取消新增。',true);return;}const button=event.submitter||$('product-form').querySelector('[type="submit"]');button.disabled=true;try{const body={};for(const key of ['code','name','category'])body[key]=$('product-'+key).value;body.aliases=splitTags($('product-aliases').value);const id=$('edit-product-id').value;await api('/api/products'+(id?'/'+id:''),{method:id?'PUT':'POST',body:JSON.stringify(body)});invalidateProductOptions();$('product-dialog').close();toast(id?'产品资料已更新':'产品已创建');if(!id)state.productOffset=0;await loadOverview();if(state.view==='products')await loadProducts();else await loadImages();}finally{button.disabled=false;}});
// Product candidates: shared requests, bounded one-minute cache, explicit invalidation.
const productSelectRequests={};
const productOptionsCache=new Map();
let productOptionsGeneration=0;
function invalidateProductOptions(){productOptionsGeneration++;productOptionsCache.clear();}
function getProductOptions(q=''){
  const key=q.trim(),cached=productOptionsCache.get(key);
  if(cached&&(cached.pending||Date.now()-cached.time<60000))return cached.pending||Promise.resolve(cached.result);
  const generation=productOptionsGeneration,entry={time:0};
  entry.pending=api('/api/products?q='+encodeURIComponent(key)+'&limit=200').then(result=>{
    if(generation===productOptionsGeneration&&productOptionsCache.get(key)===entry){entry.result=result;entry.time=Date.now();entry.pending=null;}
    return result;
  }).catch(error=>{if(productOptionsCache.get(key)===entry)productOptionsCache.delete(key);throw error;});
  productOptionsCache.set(key,entry);
  while(productOptionsCache.size>25)productOptionsCache.delete(productOptionsCache.keys().next().value);
  return entry.pending;
}
function renderProductOptions(prefix,result,selected=''){
  const select=$(prefix+'-product');
  const previous=Array.from(select.options).find(option=>option.value===selected);
  select.replaceChildren(new Option('暂不关联产品',''));
  result.items.forEach(item=>select.add(new Option(`${item.code} · ${item.name}`,item.id)));
  if(selected&&!result.items.some(item=>item.id===selected)&&previous)select.add(new Option(previous.text,selected));
  select.value=selected;
}
async function fillProductSelect(prefix,selected='',q=''){
  const sequence=(productSelectRequests[prefix]||0)+1;productSelectRequests[prefix]=sequence;
  const result=await getProductOptions(q);
  if(sequence!==productSelectRequests[prefix])return;
  renderProductOptions(prefix,result,selected);
}
for(const prefix of ['upload','detail'])$(prefix+'-product-search').oninput=debounce(()=>guarded(fillProductSelect)(prefix,$(prefix+'-product').value,$(prefix+'-product-search').value));
// End product candidates.
async function openUpload(){state.uploadFiles=[];$('file-input').value='';$('upload-tags').value='';$('upload-product-search').value='';$('upload-kind').value='产品图';$('upload-angle').value='正面';$('upload-background').value='透明';await fillProductSelect('upload');renderUploadFiles();$('upload-dialog').showModal();}
$('open-upload').onclick=guarded(openUpload);$('empty-upload').onclick=guarded(openUpload);
function addFiles(files){if(state.uploading)return;for(const file of files){if(state.uploadFiles.length>=30){toast('每批最多 30 张图片。',true);break;}if(!/\.(jpe?g|png|webp)$/i.test(file.name)){toast(`${file.name}：仅支持 JPG、PNG、WebP。`,true);continue;}if(file.size>25*1024*1024){toast(`${file.name}：超过 25 MB。`,true);continue;}if(state.uploadFiles.some(item=>item.file.name===file.name&&item.file.size===file.size&&item.file.lastModified===file.lastModified))continue;state.uploadFiles.push({file,status:'等待上传',done:false,error:false});}renderUploadFiles();}
function renderUploadFiles(){$('upload-files').innerHTML=state.uploadFiles.map((item,index)=>`<div class="upload-row"><span class="file-name" title="${escapeHtml(item.file.name)}">${escapeHtml(item.file.name)}</span><small>${bytes(item.file.size)}</small><span class="file-status ${item.error?'error':''}">${escapeHtml(item.status)}</span>${!state.uploading&&!item.done?`<button data-remove-file="${index}" aria-label="移除文件">×</button>`:''}</div>`).join('');const done=state.uploadFiles.filter(item=>item.done).length;const count=state.uploadFiles.length;$('upload-summary').textContent=count?`${count} 张图片 · ${done} 张已处理`:'尚未选择文件';$('start-upload').disabled=!count||done===count||state.uploading;$('start-upload').innerHTML=icon('upload')+(state.uploading?'正在上传…':done>0&&done<count?'重试未完成图片':'开始上传');}
$('dropzone').onclick=()=>{if(!state.uploading)$('file-input').click();};$('dropzone').onkeydown=event=>{if(['Enter',' '].includes(event.key)){event.preventDefault();if(!state.uploading)$('file-input').click();}};$('file-input').onchange=event=>{addFiles(event.target.files);event.target.value='';};
for(const type of ['dragenter','dragover'])$('dropzone').addEventListener(type,event=>{event.preventDefault();$('dropzone').classList.add('dragover');});for(const type of ['dragleave','drop'])$('dropzone').addEventListener(type,event=>{event.preventDefault();$('dropzone').classList.remove('dragover');if(type==='drop')addFiles(event.dataTransfer.files);});
$('upload-files').onclick=event=>{const remove=event.target.closest('[data-remove-file]');if(remove&&!state.uploading){state.uploadFiles.splice(Number(remove.dataset.removeFile),1);renderUploadFiles();}};
function uploadRequest(form, item){return new Promise((resolve,reject)=>{const xhr=new XMLHttpRequest();xhr.open('POST','/api/images/upload');xhr.timeout=180000;xhr.upload.onprogress=event=>{if(event.lengthComputable){item.status=Math.round(event.loaded/event.total*100)+'% · 上传中';renderUploadFiles();}};xhr.onload=()=>{let result={};try{result=JSON.parse(xhr.responseText);}catch{}if(xhr.status>=200&&xhr.status<300)resolve(result);else reject(new Error(typeof result.detail==='string'?result.detail:'上传失败，请检查文件或重新登录。'));};xhr.onerror=()=>reject(new Error('连接中断，请重试。'));xhr.ontimeout=()=>reject(new Error('上传超时，请重试。'));xhr.send(form);});}
$('start-upload').onclick=guarded(async()=>{state.uploading=true;const inputs=['upload-product-search','upload-product','upload-kind','upload-angle','upload-background','upload-tags'];const values={};for(const key of ['product','kind','angle','background','tags'])values[key]=$('upload-'+key).value;inputs.forEach(id=>$(id).disabled=true);renderUploadFiles();try{for(const item of state.uploadFiles){if(item.done)continue;item.error=false;item.status='准备上传…';renderUploadFiles();const form=new FormData();form.append('file',item.file);for(const [key,value]of Object.entries(values))form.append(key==='product'?'product_id':key,value);try{await prepareCloudUpload(form,item.file);const result=await uploadRequest(form,item);item.done=true;item.status=result.duplicate?'已存在 · 已跳过':'上传成功';}catch(error){item.error=true;item.status=error.message;}renderUploadFiles();}await loadOverview();if(['library','unassigned','trash'].includes(state.view))await loadImages();else if(state.view==='products')await loadProducts();const failed=state.uploadFiles.filter(item=>!item.done).length;toast(failed?`${failed} 张未完成，可修改后重试。`:'本批图片已处理完成。',failed>0);}finally{state.uploading=false;inputs.forEach(id=>$(id).disabled=false);renderUploadFiles();}});
// Detail dialog opens immediately; stale responses can never replace another image.
const detailState={request:0,id:'',ready:false,saving:false};
function detailControls(){
  const readOnly=!['admin','staff'].includes(state.status.role);
  $('detail-form').querySelectorAll('input,select').forEach(control=>control.disabled=readOnly||!detailState.ready||detailState.saving);
  const submit=$('detail-form').querySelector('[type="submit"]');
  submit.classList.toggle('hidden',readOnly);submit.disabled=!detailState.ready||detailState.saving;
  $('detail-trash').classList.toggle('hidden',state.status.role!=='admin');
  $('detail-trash').disabled=!detailState.ready||detailState.saving;
  $('detail-form').setAttribute('aria-busy',String(!detailState.ready||detailState.saving));
}
function paintDetail(item){
  $('detail-id').value=item.id;$('detail-name').textContent=item.product_name||item.original_name;
  $('detail-image').src=item.thumbnail_url;$('detail-image').alt=item.product_name||item.original_name;
  $('detail-meta').innerHTML=`${escapeHtml(item.original_name)}<br>${item.width} × ${item.height} · ${item.extension.toUpperCase()} · ${bytes(item.size)}<br>上传于 ${date(item.created_at)} · 当前显示预览图`;
  const select=$('detail-product');select.replaceChildren(new Option('暂不关联产品',''));
  if(item.product_id)select.add(new Option(`${item.product_code} · ${item.product_name}`,item.product_id));
  select.value=item.product_id||'';
  for(const key of ['kind','angle','background'])$('detail-'+key).value=item[key];
  $('detail-tags').value=item.tags.join('，');$('detail-download').disabled=false;
}
async function openDetail(id){
  if(detailState.saving)return;
  const sequence=++detailState.request;
  detailState.id=id;detailState.ready=false;productSelectRequests.detail=(productSelectRequests.detail||0)+1;
  $('detail-id').value=id;$('detail-name').textContent='正在加载图片…';
  $('detail-image').removeAttribute('src');$('detail-image').alt='';$('detail-meta').textContent='';
  $('detail-product').replaceChildren(new Option('暂不关联产品',''));
  $('detail-product-search').value='';$('detail-tags').value='';
  for(const key of ['kind','angle','background'])$('detail-'+key).value='';
  $('detail-download').disabled=true;$('detail-retry').classList.add('hidden');
  $('detail-load-status').textContent='正在核对最新图片资料和加载产品…';$('detail-load-status').classList.remove('hidden','error');
  const cached=state.images.find(item=>item.id===id);if(cached)paintDetail(cached);
  detailControls();if(!$('detail-dialog').open)$('detail-dialog').showModal();
  const readOnly=!['admin','staff'].includes(state.status.role);
  const results=await Promise.allSettled([api('/api/images/'+id),readOnly?Promise.resolve(null):getProductOptions()]);
  if(sequence!==detailState.request||!$('detail-dialog').open)return;
  const [image,products]=results;
  if(image.status==='fulfilled')paintDetail(image.value);
  if(image.status==='fulfilled'&&products.status==='fulfilled'){
    if(products.value)renderProductOptions('detail',products.value,image.value.product_id||'');
    detailState.ready=true;$('detail-load-status').classList.add('hidden');
  }else{
    const message=image.status==='rejected'?image.reason.message:products.reason.message;
    $('detail-load-status').textContent='加载失败：'+message+'。请重试后再保存。';
    $('detail-load-status').classList.add('error');$('detail-retry').classList.remove('hidden');
  }
  detailControls();
}
$('detail-retry').onclick=guarded(()=>openDetail(detailState.id));
$('detail-dialog').addEventListener('close',()=>{detailState.request++;detailState.ready=false;productSelectRequests.detail=(productSelectRequests.detail||0)+1;});
$('detail-form').onsubmit=guarded(async event=>{
  event.preventDefault();if(!detailState.ready||detailState.saving)return;
  const body={product_id:$('detail-product').value||null,tags:splitTags($('detail-tags').value)};
  for(const key of ['kind','angle','background'])body[key]=$('detail-'+key).value;
  detailState.saving=true;detailControls();
  try{
    await api('/api/images/'+$('detail-id').value,{method:'PUT',body:JSON.stringify(body)});
    $('detail-dialog').close();toast('图片资料已保存');await loadOverview();await loadImages();
  }finally{detailState.saving=false;detailControls();}
});
// End detail loading.
$('detail-download').onclick=guarded(()=>downloadImage($('detail-id').value));
async function permanentlyDelete(ids) {
  const result=await api('/api/images/delete',{method:'POST',body:JSON.stringify({image_ids:ids})});
  ids.forEach(id=>state.selected.delete(id));renderSelection();$('detail-dialog').close();
  toast(result.cleanup_pending?`已移除 ${result.deleted} 张图片，${result.cleanup_pending} 张的文件暂被占用，释放占用后会自动清理。`:`已永久删除 ${result.deleted} 张图片`,!!result.cleanup_pending);await loadOverview();await loadImages();
}
$('detail-trash').onclick=guarded(async()=>{if(!confirm('将这张图片移入回收站？原文件会保留，可以恢复。'))return;const id=$('detail-id').value;await api('/api/images/'+id,{method:'DELETE'});toast('已移入回收站');await loadOverview();await loadImages();});
const confirmPermanentDelete=ids=>confirm(`永久删除 ${ids.length} 张图片？\n\n原文件会从磁盘移除，无法恢复，请先确认已有备份。`);
$('batch-delete').onclick=guarded(async()=>{const ids=[...state.selected];if(!ids.length)return;if(ids.length>100){toast('每次最多永久删除 100 张，请减少选择。',true);return;}if(!confirmPermanentDelete(ids))return;await permanentlyDelete(ids);});
async function loadTeam() {
  const network=await api("/api/network");
  const port=location.port?(location.port==="80"||location.port==="443"?"":":"+location.port):"";
  const urls=(network.addresses||[]).map(ip=>`${location.protocol}//${ip}${port}`);
  const current=location.hostname;
  const chosen=network.public_origin||urls.find(url=>url.includes("//"+current+port))||urls[0]||location.origin;
  $("team-address").textContent=chosen;
  $("team-address-note").textContent="请先在 Sites 站点设置中授予同事访问权限，再为其创建素材库账号。";
  await loadAccounts();
}
async function loadAccounts(){
  const result=await api("/api/accounts");
  const rows=result.items.map(item=>{
    const staff=item.role==="staff";
    const name=escapeHtml(item.username);
    const rights=staff?"浏览 · 下载 · 上传 · 创建令牌":"浏览 · 下载";
    return `<tr><td><strong>${name}</strong></td><td>${staff?"内部账号":"外部账号"}</td>`+
      `<td class="subtext">${rights}</td><td class="subtext">${date(item.created_at)}</td>`+
      `<td><button class="text-button" data-reset-account="${item.id}" data-account-name="${name}">重置密码</button> `+
      `<button class="text-button danger" data-delete-account="${item.id}" data-account-name="${name}">删除</button></td></tr>`;
  }).join("");
  const empty="<p class=\"small\">还没有创建任何账号。同事和客户目前只能使用管理员账号登录。</p>";
  $("account-table").innerHTML=rows?`<div class="table-wrap"><table><thead><tr><th>账号</th><th>类型</th><th>可用权限</th><th>创建时间</th><th>管理</th></tr></thead><tbody>${rows}</tbody></table></div>`:empty;
}
$("copy-address").onclick=guarded(async()=>{const text=$("team-address").textContent;if(navigator.clipboard&&window.isSecureContext)await navigator.clipboard.writeText(text);else{const input=document.createElement("textarea");input.value=text;document.body.append(input);input.select();document.execCommand("copy");input.remove();}toast("访问地址已复制");});
$("account-form").onsubmit=guarded(async event=>{
  event.preventDefault();const button=$("account-submit");button.disabled=true;$("account-error").textContent="";
  if($("account-password").value.length<10){$("account-error").textContent="密码至少需要 10 个字符。";button.disabled=false;return;}
  try {
    const body={username:$("account-username").value.trim(),password:$("account-password").value,role:$("account-role").value};
    await api("/api/accounts",{method:"POST",body:JSON.stringify(body)});
    toast(body.role==="staff"?"内部账号已创建":"外部账号已创建");
    $("account-username").value="";$("account-password").value="";$("account-role").value="external";await loadAccounts();
  } catch(error){$("account-error").textContent=error.message;}
  finally{button.disabled=false;}
});
$("account-table").onclick=guarded(async event=>{
  const reset=event.target.closest("[data-reset-account]");
  const remove=event.target.closest("[data-delete-account]");
  if(reset){
    const name=reset.dataset.accountName;
    const password=prompt(`为「${name}」设置新密码（至少 10 位）：`);
    if(password===null)return;
    if(password.length<10){toast("密码至少需要 10 个字符。",true);return;}
    await api("/api/accounts/"+reset.dataset.resetAccount,{method:"PUT",body:JSON.stringify({password})});
    toast(`「${name}」的密码已重置，该账号需要重新登录`);
    return;
  }
  if(remove){
    const name=remove.dataset.accountName;
    if(!confirm(`删除账号「${name}」？\n\n该账号将无法登录，它创建的令牌也会一并作废。`))return;
    await api("/api/accounts/"+remove.dataset.deleteAccount,{method:"DELETE"});
    toast(`账号「${name}」已删除`);await loadAccounts();
  }
});
async function loadTokens(){const result=await api('/api/tokens');$('token-list').innerHTML=result.items.map(item=>{const meta=[escapeHtml(item.prefix)+'••••',item.scope==='products:create'?'可新建产品':item.scope==='images:associate'?'可关联图片':'查询下载'+(item.owner?' / 上传':''),date(item.created_at),item.last_used_at?'最后使用 '+date(item.last_used_at):'尚未使用',item.owner&&state.status.role==='admin'?'由 '+escapeHtml(item.owner)+' 创建':''].filter(Boolean).join(' · ');return `<div class="token-item"><div>${escapeHtml(item.name)}<small>${meta}</small></div><button class="text-button danger" data-revoke="${item.id}">撤销</button></div>`;}).join('')||'<p class="small">还没有访问令牌。</p>';}
$('token-form').onsubmit=guarded(async event=>{event.preventDefault();const button=event.submitter;button.disabled=true;try{const scope=state.status.role==='admin'?$('token-scope').value:'read';const result=await api('/api/tokens',{method:'POST',body:JSON.stringify({name:$('token-name').value,scope})});$('token-secret').value=result.token;$('new-token').classList.remove('hidden');$('token-name').value='';await loadTokens();}finally{button.disabled=false;}});
$('copy-token').onclick=guarded(async()=>{const input=$('token-secret');if(navigator.clipboard&&window.isSecureContext)await navigator.clipboard.writeText(input.value);else{input.select();if(!document.execCommand('copy'))throw new Error('请选中令牌手动复制。');}toast('令牌已复制，请保存在工具的凭据配置中。');});
$('token-list').onclick=guarded(async event=>{const button=event.target.closest('[data-revoke]');if(!button||!confirm('撤销后，使用此令牌的工具将失去相应授权。确定撤销？'))return;await api('/api/tokens/'+button.dataset.revoke,{method:'DELETE'});await loadTokens();toast('令牌已撤销');});
async function loadAudit(){const result=await api('/api/audit');$('activity-table').innerHTML=`<div class="table-wrap"><table><thead><tr><th>操作</th><th>操作者</th><th>对象 / 详情</th><th>时间</th></tr></thead><tbody>${result.items.map(item=>`<tr><td><strong>${escapeHtml(item.action)}</strong></td><td>${item.actor==='admin'?'管理员':item.actor==='访客'?'访客账号':'授权工具'}</td><td><span class="subtext">${escapeHtml(item.detail||'—')}</span></td><td>${date(item.created_at)}</td></tr>`).join('')||'<tr><td colspan="4" class="table-empty">还没有操作记录。</td></tr>'}</tbody></table></div><p class="subtext">显示最近 100 条记录。</p>`;}
boot();
