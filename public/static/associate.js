'use strict';
const association = {product:null, selected:new Set(), items:[], offset:0, total:0, request:0, loading:false, saving:false};
const associationDialog = document.createElement('dialog');
associationDialog.id='associate-dialog';associationDialog.className='associate-dialog';
associationDialog.setAttribute('aria-labelledby','associate-title');
associationDialog.innerHTML=`<div class="associate-head"><div><span class="eyebrow">CONNECT PRODUCT ASSETS</span><h2 id="associate-title">关联产品图片</h2></div><button type="button" class="dialog-close" id="associate-close" aria-label="关闭关联窗口">×</button></div>
  <div class="associate-target"><span class="associate-target-label">关联到产品</span><strong id="associate-product-name"></strong><span id="associate-product-code" class="code"></span><small id="associate-existing"></small></div>
  <div class="associate-toolbar"><div class="search-field"><span>${icon('search')}</span><input id="associate-search" aria-label="搜索待关联图片文件名" placeholder="搜索图片文件名，例如 SKU、型号或正面…" maxlength="200"></div><button type="button" class="button secondary" id="associate-select-page">全选本页</button></div>
  <div class="associate-filters"><label>类型<select id="associate-kind"></select></label><label>角度<select id="associate-angle"></select></label><label>背景<select id="associate-background"></select></label><button type="button" class="text-button" id="associate-reset">清除筛选</button></div>
  <div class="associate-results"><strong>待整理图片</strong><span id="associate-total" role="status" aria-live="polite"></span><span>只显示尚未关联产品的图片</span></div>
  <div id="associate-grid" class="associate-grid"></div><div id="associate-empty" class="associate-empty hidden"></div>
  <div id="associate-pagination" class="associate-pagination hidden"><button type="button" class="button secondary" id="associate-prev">上一页</button><span id="associate-page-info"></span><button type="button" class="button secondary" id="associate-next">下一页</button></div>
  <div id="associate-error" class="form-error" role="alert"></div>
  <div class="associate-footer"><div><strong id="associate-selected">已选 0 张</strong><small id="associate-selection-note">跨页及筛选保留选择 · 每批最多 100 张</small></div><button type="button" class="text-button" id="associate-clear">清空选择</button><div class="associate-footer-actions"><button type="button" class="button secondary" id="associate-cancel">取消</button><button type="button" class="button primary" id="associate-submit" disabled>确认关联</button></div></div>`;
document.body.append(associationDialog);

function closeAssociation(){
  if(association.saving)return;
  associationDialog.close();
}
associationDialog.addEventListener('close',()=>{association.request++;association.selected.clear();association.product=null;});
associationDialog.addEventListener('cancel',event=>{if(association.saving)event.preventDefault();});
associationDialog.addEventListener('click',event=>{
  if(event.target!==associationDialog)return;
  const box=associationDialog.getBoundingClientRect();
  if(event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom)closeAssociation();
});
$('associate-close').onclick=closeAssociation;$('associate-cancel').onclick=closeAssociation;

async function openAssociation(product){
  if(state.status?.role!=='admin'||!product)return;
  association.product=product;association.selected.clear();association.offset=0;association.items=[];association.total=0;
  $('associate-product-name').textContent=product.name;$('associate-product-code').textContent='SKU '+product.code;
  $('associate-existing').textContent='当前已关联 '+product.image_count+' 张';
  $('associate-search').value='';$('associate-error').textContent='';
  options('associate-kind',state.status.kinds,'全部类型');
  options('associate-angle',state.status.angles,'全部角度');
  options('associate-background',state.status.backgrounds,'全部背景');
  associationDialog.showModal();
  await loadAssociationImages();
}
function renderAssociationSelection(){
  $('associate-selected').textContent='已选 '+association.selected.size+' 张';
  const elsewhere=association.selected.size-association.items.filter(item=>association.selected.has(item.id)).length;
  $('associate-selection-note').textContent=!association.loading&&elsewhere>0?`含其他页或筛选中的 ${elsewhere} 张 · 每批最多 100 张`:'跨页及筛选保留选择 · 每批最多 100 张';
  $('associate-submit').textContent=association.saving?'正在关联…':association.selected.size?'确认关联 '+association.selected.size+' 张':'确认关联';
  $('associate-submit').disabled=association.saving||association.loading||!association.selected.size;
  $('associate-clear').disabled=association.saving||!association.selected.size;
  $('associate-select-page').disabled=association.saving||association.loading||!association.items.length;
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
  association.loading=true;association.items=[];renderAssociationSelection();
  $('associate-total').textContent='正在查找…';$('associate-grid').replaceChildren();
  $('associate-empty').classList.add('hidden');$('associate-pagination').classList.add('hidden');
  const params=new URLSearchParams({unassigned:'true',filename:$('associate-search').value.trim(),offset:association.offset,limit:24});
  for(const key of ['kind','angle','background'])if($('associate-'+key).value)params.set(key,$('associate-'+key).value);
  try{
    const result=await api('/api/images?'+params);
    if(sequence!==association.request||!associationDialog.open)return;
    // Another administrator may have associated images while this page was open.
    if(association.offset&&association.offset>=result.total){association.offset=0;return await loadAssociationImages();}
    association.items=result.items;association.total=result.total;
    $('associate-total').textContent='共 '+result.total+' 张';
    $('associate-grid').innerHTML=result.items.map(item=>`<label class="associate-card${association.selected.has(item.id)?' selected':''}"><input type="checkbox" value="${item.id}" aria-label="选择 ${escapeHtml(item.original_name)}"${association.selected.has(item.id)?' checked':''}><div class="associate-preview checker"><img src="${item.thumbnail_url}" alt="" loading="lazy"></div><div class="associate-card-info"><strong title="${escapeHtml(item.original_name)}">${escapeHtml(item.original_name)}</strong><span>${escapeHtml(item.kind)} · ${escapeHtml(item.angle)} · ${escapeHtml(item.background)}</span><small>${item.width} × ${item.height} · ${item.extension.toUpperCase()}</small></div></label>`).join('');
    $('associate-empty').classList.toggle('hidden',!!result.items.length);
    $('associate-empty').textContent=$('associate-search').value.trim()||['kind','angle','background'].some(key=>$('associate-'+key).value)
      ?'没有找到符合条件的待整理图片，试试清除筛选。':'暂时没有待整理图片。可以先上传未关联产品的图片，再来这里批量选择。';
    $('associate-pagination').classList.toggle('hidden',result.total<=24);
    $('associate-page-info').textContent=`第 ${Math.floor(association.offset/24)+1} / ${Math.max(1,Math.ceil(result.total/24))} 页`;
  }catch(error){
    if(sequence===association.request&&associationDialog.open){$('associate-error').textContent=error.message;$('associate-total').textContent='加载失败，可刷新筛选重试';}
  }finally{
    if(sequence===association.request){association.loading=false;renderAssociationSelection();}
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
  const input=event.target.closest('input[type="checkbox"]');if(!input)return;
  if(input.checked){if(association.selected.size>=100){input.checked=false;toast('每批最多关联 100 张，请先完成当前批次。',true);}else association.selected.add(input.value);}
  else association.selected.delete(input.value);
  renderAssociationSelection();
};
$('associate-select-page').onclick=()=>{
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
  if(association.saving||association.loading||!association.selected.size||!association.product)return;
  association.saving=true;$('associate-error').textContent='';
  const controls=['search','kind','angle','background','reset','close','cancel'];
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
