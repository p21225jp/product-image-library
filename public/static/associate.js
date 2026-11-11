'use strict';
const association = {product:null, mode:'pending', selected:new Set(), items:[], offset:0, total:0, request:0, loading:false, saving:false};
const associationDialog = document.createElement('dialog');
associationDialog.id='associate-dialog';associationDialog.className='associate-dialog';
associationDialog.setAttribute('aria-labelledby','associate-title');
associationDialog.innerHTML=`<div class="associate-head"><div><span class="eyebrow">CONNECT PRODUCT ASSETS</span><h2 id="associate-title">关联产品图片</h2></div><button type="button" class="dialog-close" id="associate-close" aria-label="关闭关联窗口">×</button></div>
  <div class="associate-target"><span class="associate-target-label">关联到产品</span><strong id="associate-product-name"></strong><span id="associate-product-code" class="code"></span><small id="associate-existing"></small></div>
  <div class="associate-tabs" role="tablist" aria-label="产品图片"><button type="button" role="tab" id="associate-pending-tab" aria-selected="true" aria-controls="associate-panel">待关联</button><button type="button" role="tab" id="associate-linked-tab" aria-selected="false" aria-controls="associate-panel" tabindex="-1">已关联 <span id="associate-linked-count">0</span></button></div>
  <div id="associate-panel" role="tabpanel" aria-labelledby="associate-pending-tab">
  <div class="associate-toolbar"><div class="search-field"><span>${icon('search')}</span><input id="associate-search" aria-label="搜索待关联图片文件名" placeholder="搜索图片文件名，例如 SKU、型号或正面…" maxlength="200"></div><button type="button" class="button secondary" id="associate-select-page">全选本页</button></div>
  <div class="associate-filters"><label>类型<select id="associate-kind"></select></label><label>角度<select id="associate-angle"></select></label><label>背景<select id="associate-background"></select></label><button type="button" class="text-button" id="associate-reset">清除筛选</button></div>
  <div class="associate-results"><strong id="associate-results-title">待整理图片</strong><span id="associate-total" role="status" aria-live="polite"></span><span id="associate-results-note">只显示尚未关联产品的图片</span></div>
  <div id="associate-grid" class="associate-grid"></div><div id="associate-empty" class="associate-empty hidden"></div>
  <div id="associate-pagination" class="associate-pagination hidden"><button type="button" class="button secondary" id="associate-prev">上一页</button><span id="associate-page-info"></span><button type="button" class="button secondary" id="associate-next">下一页</button></div>
  </div>
  <div id="associate-error" class="form-error" role="alert"></div>
  <div class="associate-footer"><div><strong id="associate-selected">已选 0 张</strong><small id="associate-selection-note">跨页及筛选保留选择 · 每批最多 100 张</small></div><button type="button" class="text-button" id="associate-clear">清空选择</button><div class="associate-footer-actions"><button type="button" class="button secondary" id="associate-cancel">取消</button><button type="button" class="button primary" id="associate-submit" disabled>确认关联</button></div></div>`;
document.body.append(associationDialog);

function closeAssociation(){
  if(association.saving)return;
  associationDialog.close();
}
associationDialog.addEventListener('close',()=>{delayedAssociationSearch.cancel();association.request++;association.selected.clear();association.product=null;});
associationDialog.addEventListener('cancel',event=>{if(association.saving)event.preventDefault();});
associationDialog.addEventListener('click',event=>{
  if(event.target!==associationDialog)return;
  const box=associationDialog.getBoundingClientRect();
  if(event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom)closeAssociation();
});
$('associate-close').onclick=closeAssociation;$('associate-cancel').onclick=closeAssociation;

async function openAssociation(product){
  if(state.status?.role!=='admin'||!product)return;
  delayedAssociationSearch.cancel();association.mode='pending';association.product=product;association.selected.clear();association.offset=0;association.items=[];association.total=0;
  $('associate-product-name').textContent=product.name;$('associate-product-code').textContent='SKU '+product.code;
  $('associate-existing').textContent='当前已关联 '+product.image_count+' 张';
  $('associate-linked-count').textContent=product.image_count;
  $('associate-search').value='';$('associate-error').textContent='';
  options('associate-kind',state.status.kinds,'全部类型');
  options('associate-angle',state.status.angles,'全部角度');
  options('associate-background',state.status.backgrounds,'全部背景');
  renderAssociationMode();
  associationDialog.showModal();
  await loadAssociationImages();
}
function renderAssociationMode(){
  const linked=association.mode==='linked';
  for(const mode of ['pending','linked']){
    const tab=$('associate-'+mode+'-tab'),active=association.mode===mode;
    tab.setAttribute('aria-selected',String(active));tab.setAttribute('tabindex',active?'0':'-1');tab.disabled=association.saving;
  }
  $('associate-panel').setAttribute('aria-labelledby','associate-'+association.mode+'-tab');
  $('associate-search').setAttribute('aria-label',linked?'搜索已关联图片文件名':'搜索待关联图片文件名');
  $('associate-results-title').textContent=linked?'已关联图片':'待整理图片';
  $('associate-results-note').textContent=linked?'当前产品的图片 · 点击预览查看大图':'只显示尚未关联产品的图片';
  for(const id of ['associate-select-page','associate-clear','associate-submit'])$(id).classList.toggle('hidden',linked);
}
async function switchAssociationMode(mode){
  if(association.saving||association.mode===mode)return;
  delayedAssociationSearch.cancel();association.mode=mode;association.offset=0;
  $('associate-search').value='';$('associate-error').textContent='';
  for(const key of ['kind','angle','background'])$('associate-'+key).value='';
  renderAssociationMode();await loadAssociationImages();
}
for(const mode of ['pending','linked']){
  const tab=$('associate-'+mode+'-tab');
  tab.onclick=()=>switchAssociationMode(mode);
  tab.onkeydown=event=>{
    if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)||association.saving)return;
    event.preventDefault();const next=event.key==='Home'?'pending':event.key==='End'?'linked':mode==='pending'?'linked':'pending';
    $('associate-'+next+'-tab').focus();switchAssociationMode(next);
  };
}
function renderAssociationSelection(){
  const linked=association.mode==='linked';
  $('associate-selected').textContent=(linked?'待关联已选 ':'已选 ')+association.selected.size+' 张';
  const elsewhere=association.selected.size-association.items.filter(item=>association.selected.has(item.id)).length;
  $('associate-selection-note').textContent=linked?'返回「待关联」可继续选择图片。':!association.loading&&elsewhere>0?`含其他页或筛选中的 ${elsewhere} 张 · 每批最多 100 张`:'跨页及筛选保留选择 · 每批最多 100 张';
  $('associate-submit').textContent=association.saving?'正在关联…':association.selected.size?'确认关联 '+association.selected.size+' 张':'确认关联';
  $('associate-submit').disabled=linked||association.saving||association.loading||!association.selected.size;
  $('associate-clear').disabled=association.saving||!association.selected.size;
  $('associate-select-page').disabled=linked||association.saving||association.loading||!association.items.length;
  const all=association.items.length&&association.items.every(item=>association.selected.has(item.id));
  $('associate-select-page').textContent=all?'取消本页选择':'全选本页';
  $('associate-grid').querySelectorAll('input[type="checkbox"]').forEach(input=>{
    input.checked=association.selected.has(input.value);input.disabled=association.saving;
    input.closest('.associate-card').classList.toggle('selected',input.checked);
  });
  $('associate-prev').disabled=association.loading||association.saving||association.offset===0;
  $('associate-next').disabled=association.loading||association.saving||association.offset+24>=association.total;
}
async function loadAssociationImages(){
  if(!associationDialog.open||!association.product)return;
  const sequence=++association.request;
  $('associate-panel').setAttribute('aria-busy','true');
  association.loading=true;association.items=[];renderAssociationSelection();
  $('associate-total').textContent='正在查找…';$('associate-grid').replaceChildren();
  $('associate-empty').classList.add('hidden');$('associate-pagination').classList.add('hidden');
  const linked=association.mode==='linked';
  const params=new URLSearchParams({filename:$('associate-search').value.trim(),offset:association.offset,limit:24});
  if(linked)params.set('product_id',association.product.id);else params.set('unassigned','true');
  for(const key of ['kind','angle','background'])if($('associate-'+key).value)params.set(key,$('associate-'+key).value);
  try{
    const result=await api('/api/images?'+params);
    if(sequence!==association.request||!associationDialog.open)return;
    // Another administrator may have associated images while this page was open.
    if(association.offset&&association.offset>=result.total){association.offset=0;return await loadAssociationImages();}
    association.items=result.items;association.total=result.total;
    if(linked&&!$('associate-search').value.trim()&&!['kind','angle','background'].some(key=>$('associate-'+key).value)){
      association.product.image_count=result.total;$('associate-linked-count').textContent=result.total;$('associate-existing').textContent='当前已关联 '+result.total+' 张';
    }
    $('associate-total').textContent='共 '+result.total+' 张';
    $('associate-grid').innerHTML=result.items.map(item=>linked
      ?`<article class="associate-card is-linked"><span class="associate-badge">已关联</span><a class="associate-preview${item.has_alpha?' checker':''}" href="${escapeHtml(item.thumbnail_url)}" target="_blank" rel="noopener" aria-label="查看大图 ${escapeHtml(item.original_name)}"><img src="${escapeHtml(item.thumbnail_url)}" alt="${escapeHtml(item.original_name)}" loading="lazy"></a><div class="associate-card-info"><strong title="${escapeHtml(item.original_name)}">${escapeHtml(item.original_name)}</strong><span>${escapeHtml(item.kind)} · ${escapeHtml(item.angle)} · ${escapeHtml(item.background)}</span><small>${item.width} × ${item.height} · ${item.extension.toUpperCase()}</small></div></article>`
      :`<label class="associate-card${association.selected.has(item.id)?' selected':''}"><input type="checkbox" value="${item.id}" aria-label="选择 ${escapeHtml(item.original_name)}"${association.selected.has(item.id)?' checked':''}><div class="associate-preview checker"><img src="${item.thumbnail_url}" alt="" loading="lazy"></div><div class="associate-card-info"><strong title="${escapeHtml(item.original_name)}">${escapeHtml(item.original_name)}</strong><span>${escapeHtml(item.kind)} · ${escapeHtml(item.angle)} · ${escapeHtml(item.background)}</span><small>${item.width} × ${item.height} · ${item.extension.toUpperCase()}</small></div></label>`).join('');
    $('associate-empty').classList.toggle('hidden',!!result.items.length);
    const filtered=$('associate-search').value.trim()||['kind','angle','background'].some(key=>$('associate-'+key).value);
    $('associate-empty').textContent=linked?(filtered?'没有找到符合条件的已关联图片，试试清除筛选。':'当前产品尚未关联图片，可切换到「待关联」选择。'):(filtered?'没有找到符合条件的待整理图片，试试清除筛选。':'暂时没有待整理图片。可以先上传未关联产品的图片，再来这里批量选择。');
    $('associate-pagination').classList.toggle('hidden',result.total<=24);
    $('associate-page-info').textContent=`第 ${Math.floor(association.offset/24)+1} / ${Math.max(1,Math.ceil(result.total/24))} 页`;
  }catch(error){
    if(sequence===association.request&&associationDialog.open){$('associate-error').textContent=error.message;$('associate-total').textContent='加载失败，可刷新筛选重试';}
  }finally{
    if(sequence===association.request){association.loading=false;$('associate-panel').setAttribute('aria-busy','false');renderAssociationSelection();}
  }
}
function filterAssociation(){if(association.saving)return;association.offset=0;$('associate-error').textContent='';return loadAssociationImages();}
$('associate-search').oninput=()=>{
  // Invalidate the previous request immediately, even during the debounce interval.
  association.request++;association.loading=true;renderAssociationSelection();delayedAssociationSearch();
};
const delayedAssociationSearch=debounce(()=>filterAssociation(),250);
for(const key of ['kind','angle','background'])$('associate-'+key).onchange=filterAssociation;
$('associate-reset').onclick=()=>{$('associate-search').value='';for(const key of ['kind','angle','background'])$('associate-'+key).value='';filterAssociation();};
$('associate-prev').onclick=()=>{association.offset=Math.max(0,association.offset-24);loadAssociationImages();};
$('associate-next').onclick=()=>{association.offset+=24;loadAssociationImages();};
$('associate-grid').onchange=event=>{
  if(association.mode!=='pending'||association.saving||association.loading)return;
  const input=event.target.closest('input[type="checkbox"]');if(!input)return;
  if(input.checked){if(association.selected.size>=100){input.checked=false;toast('每批最多关联 100 张，请先完成当前批次。',true);}else association.selected.add(input.value);}
  else association.selected.delete(input.value);
  renderAssociationSelection();
};
$('associate-select-page').onclick=()=>{
  if(association.mode!=='pending'||association.saving||association.loading)return;
  const all=association.items.every(item=>association.selected.has(item.id));
  for(const item of association.items){
    if(all)association.selected.delete(item.id);
    else if(association.selected.size<100)association.selected.add(item.id);
  }
  if(!all&&association.items.some(item=>!association.selected.has(item.id)))toast('已选满 100 张，请先完成当前批次。');
  renderAssociationSelection();
};
$('associate-clear').onclick=()=>{association.selected.clear();renderAssociationSelection();};
$('associate-submit').onclick=async()=>{
  if(association.mode!=='pending'||association.saving||association.loading||!association.selected.size||!association.product)return;
  association.saving=true;$('associate-error').textContent='';
  const controls=['search','kind','angle','background','reset','close','cancel','pending-tab','linked-tab'];
  controls.forEach(key=>$('associate-'+key).disabled=true);renderAssociationSelection();
  const target=association.product;
  try{
    const result=await api('/api/products/'+target.id+'/images/associate',{method:'POST',body:JSON.stringify({image_ids:[...association.selected]})});
    association.saving=false;closeAssociation();
    toast(result.associated?`已将 ${result.associated} 张图片关联到 ${target.code}。`:'所选图片已关联到该产品。');
    await loadOverview();if(state.view==='products')await loadProducts();
  }catch(error){
    if(associationDialog.open){
      $('associate-error').textContent=error.message;
      if(error.status===409){association.selected.clear();await loadAssociationImages();}
    }else if(state.status?.logged_in)toast(error.message,true);
  }finally{association.saving=false;controls.forEach(key=>$('associate-'+key).disabled=false);renderAssociationSelection();}
};
