'use strict';
const categoryUI={request:0,previewRequest:0,preview:null,previewing:false,deleting:false};
const categoryManager=document.createElement('dialog');
categoryManager.id='category-manager';categoryManager.className='category-manager';
categoryManager.setAttribute('aria-labelledby','category-manager-title');
categoryManager.innerHTML=`<div class="category-dialog-heading"><div><span class="eyebrow">PRODUCT CATEGORIES</span><h2 id="category-manager-title">管理分类</h2></div><button type="button" id="category-manager-close" class="dialog-close" aria-label="关闭分类管理">×</button></div>
  <p class="category-manager-lead">查看分类及关联数量。删除分类时，产品将改为未分类，相关图片自动解除产品关联。</p>
  <form id="category-create-form" class="category-create"><input id="category-create-input" maxlength="80" placeholder="输入新分类名称，例如：显示器 / 电竞屏" autocomplete="off" required><button type="submit" id="category-create-submit" class="button primary">新建分类</button></form>
  <div id="category-manager-error" class="form-error" role="alert"></div><div id="category-manager-list"></div>
  <div class="category-manager-footer"><span>仅管理员可新建、重命名和删除分类</span><button type="button" id="category-manager-refresh" class="text-button">刷新分类列表</button></div>`;
document.body.append(categoryManager);
const categoryDelete=document.createElement('dialog');
categoryDelete.id='category-delete';categoryDelete.className='category-delete';
categoryDelete.setAttribute('aria-labelledby','category-delete-title');
categoryDelete.innerHTML=`<div class="category-dialog-heading"><div><span class="eyebrow">DELETE CATEGORY</span><h2 id="category-delete-title">删除分类</h2></div><button type="button" id="category-delete-close" class="dialog-close" aria-label="关闭删除分类确认">×</button></div>
  <p class="category-delete-name" id="category-delete-name"></p><div class="category-delete-counts"><div><strong id="category-delete-products">0</strong><span>个产品改为未分类</span></div><div><strong id="category-delete-images">0</strong><span>张图片回到待整理</span></div></div>
  <div class="category-delete-explanation"><p>分类会从选项中移除。产品资料和图片文件保留，图片与产品的关联将解除。</p><p id="category-delete-trash" class="hidden"></p><p>删除后如需恢复关联，需要重新选择分类和图片。</p></div>
  <div id="category-delete-error" class="form-error" role="alert"></div><div class="category-delete-footer"><button type="button" id="category-delete-cancel" class="button secondary">取消</button><button type="button" id="category-delete-submit" class="button category-danger">确认删除并解绑</button></div>`;
document.body.append(categoryDelete);
const categoryRename=document.createElement('dialog');
categoryRename.id='category-rename';categoryRename.className='category-delete';
categoryRename.setAttribute('aria-labelledby','category-rename-title');
categoryRename.innerHTML=`<div class="category-dialog-heading"><div><span class="eyebrow">RENAME CATEGORY</span><h2 id="category-rename-title">修改分类名称</h2></div><button type="button" id="category-rename-close" class="dialog-close" aria-label="关闭修改分类">×</button></div>
  <form id="category-rename-form"><label>分类名称<input id="category-rename-input" maxlength="80" required autocomplete="off"></label>
  <p class="category-manager-lead" id="category-rename-note"></p>
  <div id="category-rename-error" class="form-error" role="alert"></div>
  <div class="category-delete-footer"><button type="button" id="category-rename-cancel" class="button secondary">取消</button><button type="submit" id="category-rename-submit" class="button primary">保存</button></div></form>`;
document.body.append(categoryRename);
const renameUI={original:'',productCount:0,busy:false};
function closeCategoryRename(){if(!renameUI.busy)categoryRename.close();}
$('category-rename-close').onclick=closeCategoryRename;$('category-rename-cancel').onclick=closeCategoryRename;
categoryRename.addEventListener('cancel',event=>{if(renameUI.busy)event.preventDefault();});
categoryRename.addEventListener('close',()=>{$('category-rename-error').textContent='';});

function closeCategoryDelete(){if(!categoryUI.deleting)categoryDelete.close();}
$('category-delete-close').onclick=closeCategoryDelete;$('category-delete-cancel').onclick=closeCategoryDelete;
$('category-manager-close').onclick=()=>{if(!categoryUI.deleting)categoryManager.close();};
categoryDelete.addEventListener('close',()=>{categoryUI.preview=null;categoryUI.previewRequest++;});
categoryDelete.addEventListener('cancel',event=>{if(categoryUI.deleting)event.preventDefault();});
categoryManager.addEventListener('close',()=>{categoryUI.request++;categoryUI.previewRequest++;});
for(const dialog of [categoryManager,categoryDelete])dialog.addEventListener('click',event=>{
  if(event.target!==dialog||categoryUI.deleting)return;
  const box=dialog.getBoundingClientRect();
  if(event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom)dialog.close();
});

async function loadManagedCategories(){
  const sequence=++categoryUI.request;
  $('category-manager-refresh').disabled=true;
  try{
    const result=await api('/api/categories/manage');
    if(sequence!==categoryUI.request||!categoryManager.open||state.status?.role!=='admin')return;
    $('category-manager-list').innerHTML=result.items.length?`<div class="category-manager-table"><table><thead><tr><th>分类名称</th><th>产品</th><th>关联图片</th><th>操作</th></tr></thead><tbody>${result.items.map(item=>`<tr><td><strong>${escapeHtml(item.name)}</strong></td><td>${item.product_count} 个</td><td>${item.image_count} 张${item.trashed_image_count?`<small>另有 ${item.trashed_image_count} 张在回收站</small>`:''}</td><td><button type="button" class="text-button" data-rename-category="${escapeHtml(item.name)}" aria-label="重命名分类 ${escapeHtml(item.name)}">重命名</button> <button type="button" class="text-button danger" data-delete-category="${escapeHtml(item.name)}" aria-label="删除分类 ${escapeHtml(item.name)}">删除分类</button></td></tr>`).join('')}</tbody></table></div>`:'<div class="category-manager-empty">暂无分类。可在新建或编辑产品时创建分类选项。</div>';
    $('category-manager-error').textContent='';
  }catch(error){if(sequence===categoryUI.request&&categoryManager.open)$('category-manager-error').textContent=error.message;}
  finally{if(sequence===categoryUI.request)$('category-manager-refresh').disabled=false;}
}
function showCategoryImpact(impact){
  categoryUI.preview=impact;
  $('category-delete-submit').disabled=categoryUI.deleting;
  $('category-delete-name').textContent='将删除分类「'+impact.name+'」';
  $('category-delete-products').textContent=impact.product_count;
  $('category-delete-images').textContent=impact.image_count;
  $('category-delete-trash').classList.toggle('hidden',!impact.trashed_image_count);
  $('category-delete-trash').textContent=`另有 ${impact.trashed_image_count} 张回收站图片也会解绑，仍保留在回收站。`;
}
$('manage-categories').onclick=guarded(async()=>{
  if(state.status?.role!=='admin')return;
  $('category-manager-list').textContent='正在加载分类…';$('category-manager-error').textContent='';
  categoryManager.showModal();await loadManagedCategories();
});
$('category-create-form').onsubmit=async event=>{
  event.preventDefault();
  const name=$('category-create-input').value.trim();
  const submit=$('category-create-submit');
  if(!name){$('category-manager-error').textContent='分类名称不能为空。';return;}
  if(submit.disabled)return;
  submit.disabled=true;submit.textContent='正在新建…';$('category-manager-error').textContent='';
  try{
    const result=await api('/api/categories',{method:'POST',body:JSON.stringify({name})});
    $('category-create-input').value='';
    toast(result.created?`已新建分类「${result.name}」。`:`分类「${result.name}」已存在。`);
    await loadManagedCategories();
    await loadOverview();await loadProductCategories();
    const choices=await api('/api/categories');options('product-category',choices.items,'未分类');
    if(state.view==='products')await loadProducts();
  }catch(error){
    $('category-manager-error').textContent=error.message;
  }finally{
    submit.disabled=false;submit.textContent='新建分类';
    if(categoryManager.open)$('category-create-input').focus();
  }
};
$('category-manager-refresh').onclick=guarded(loadManagedCategories);
$('category-manager-list').onclick=guarded(async event=>{
  const renameButton=event.target.closest('[data-rename-category]');
  if(renameButton){
    if(categoryUI.previewing||categoryUI.deleting||renameUI.busy)return;
    const row=renameButton.closest('tr');
    const countText=row?row.children[1].textContent.trim():'';
    renameUI.original=renameButton.dataset.renameCategory;
    renameUI.productCount=parseInt(countText,10)||0;
    $('category-rename-input').value=renameUI.original;
    $('category-rename-note').textContent=renameUI.productCount
      ? `改名后 ${renameUI.productCount} 个产品会同步使用新名称，图片关联不受影响。`
      : '该分类下暂无产品，改名后立即可用。';
    $('category-rename-error').textContent='';
    categoryRename.showModal();
    const input=$('category-rename-input');input.focus();input.select();
    return;
  }
  const button=event.target.closest('[data-delete-category]');
  if(!button||categoryUI.previewing||categoryUI.deleting)return;
  const sequence=++categoryUI.previewRequest;categoryUI.previewing=true;
  button.disabled=true;$('category-manager-error').textContent='';
  try{
    const impact=await api('/api/categories/deletion-preview?'+new URLSearchParams({name:button.dataset.deleteCategory}));
    if(sequence!==categoryUI.previewRequest||!categoryManager.open||state.status?.role!=='admin')return;
    showCategoryImpact(impact);$('category-delete-error').textContent='';categoryDelete.showModal();
  }catch(error){if(sequence===categoryUI.previewRequest&&categoryManager.open)$('category-manager-error').textContent=error.message;}
  finally{categoryUI.previewing=false;button.disabled=false;}
});
$('category-rename-form').onsubmit=async event=>{
  event.preventDefault();
  if(renameUI.busy)return;
  const value=$('category-rename-input').value.trim();
  if(!value){$('category-rename-error').textContent='分类名称不能为空。';return;}
  if(value===renameUI.original){closeCategoryRename();return;}
  renameUI.busy=true;
  const controls=['category-rename-submit','category-rename-cancel','category-rename-close','category-rename-input'];
  controls.forEach(id=>$(id).disabled=true);$('category-rename-submit').textContent='正在保存…';$('category-rename-error').textContent='';
  try{
    const result=await api('/api/categories',{method:'PUT',body:JSON.stringify({name:renameUI.original,new_name:value})});
    renameUI.busy=false;categoryRename.close();
    toast(result.renamed?`分类已改名为「${result.name}」，${result.product_count} 个产品同步更新。`:'分类名称未改变。');
    await loadManagedCategories();
    await loadOverview();await loadProductCategories();
    const choices=await api('/api/categories');options('product-category',choices.items,'未分类');
    if(state.view==='products')await loadProducts();
  }catch(error){
    $('category-rename-error').textContent=error.message;
  }finally{
    renameUI.busy=false;controls.forEach(id=>$(id).disabled=false);
    $('category-rename-submit').textContent='保存';
  }
};
$('category-delete-submit').onclick=async()=>{
  if(!categoryUI.preview||categoryUI.deleting)return;
  const impact=categoryUI.preview;categoryUI.deleting=true;
  const controls=['category-delete-submit','category-delete-cancel','category-delete-close'];
  controls.forEach(id=>$(id).disabled=true);$('category-delete-submit').textContent='正在删除…';$('category-delete-error').textContent='';
  try{
    const result=await api('/api/categories',{method:'DELETE',body:JSON.stringify({name:impact.name,preview_token:impact.preview_token})});
    categoryUI.deleting=false;categoryDelete.close();
    toast(`已删除「${result.name}」，${result.product_count} 个产品改为未分类，${result.image_count} 张图片回到待整理。`);
    await loadManagedCategories();
    if(state.status?.role!=='admin')return;
    await loadOverview();await loadProductCategories();
    const choices=await api('/api/categories');options('product-category',choices.items,'未分类');
    if(state.view==='products')await loadProducts();
  }catch(error){
    if(!categoryDelete.open){toast(error.message,true);return;}
    $('category-delete-error').textContent=error.message;
    if(error.status===409){
      try{showCategoryImpact(await api('/api/categories/deletion-preview?'+new URLSearchParams({name:impact.name})));}
      catch(refreshError){categoryUI.preview=null;$('category-delete-error').textContent=refreshError.message;}
    }else if(error.status===404){categoryUI.preview=null;}
  }finally{
    categoryUI.deleting=false;controls.forEach(id=>$(id).disabled=false);
    $('category-delete-submit').disabled=!categoryUI.preview;$('category-delete-submit').textContent='确认删除并解绑';
  }
};
