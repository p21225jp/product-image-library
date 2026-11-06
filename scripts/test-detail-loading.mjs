import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source=readFileSync('public/static/app.js','utf8');
const picker=source.slice(source.indexOf('// Product candidates:'),source.indexOf('// End product candidates.'));
const detail=source.slice(source.indexOf('// Detail dialog opens'),source.indexOf('// End detail loading.'));
function deferred(){let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};}
function fixture(role='admin'){
  const elements=new Map(),requests=[];
  function $(id){
    if(!elements.has(id)){
      const classes=new Set(),listeners={};
      elements.set(id,{id,value:'',options:[],disabled:false,open:false,textContent:'',innerHTML:'',
        classList:{add:(...names)=>names.forEach(x=>classes.add(x)),remove:(...names)=>names.forEach(x=>classes.delete(x)),contains:x=>classes.has(x),toggle:(x,on)=>on?classes.add(x):classes.delete(x)},
        replaceChildren(...options){this.options=options;this.value=options[0]?.value||'';},add(option){this.options.push(option);},
        setAttribute(name,value){this[name]=value;},removeAttribute(name){delete this[name];},
        querySelector(){return $('submit');},querySelectorAll(){return ['product','product-search','kind','angle','background','tags'].map(key=>$('detail-'+key));},
        addEventListener(name,fn){listeners[name]=fn;},showModal(){this.open=true;},close(){this.open=false;listeners.close?.();}});
    }
    return elements.get(id);
  }
  const image=id=>({id,product_id:'p1',product_code:'001',product_name:'Cached '+id,original_name:id+'.png',thumbnail_url:'/thumb/'+id,width:5000,height:5000,extension:'png',size:1000,created_at:1,kind:'产品图',angle:'正面',background:'透明',tags:[]});
  const state={status:{role},images:[image('a'),image('b')]};
  const context=vm.createContext({$,state,Date:{now:()=>context.now},now:0,Option:function(text,value){this.text=text;this.value=value;},
    api:(route,options)=>{const job=deferred();requests.push({route,options,...job});return job.promise;},
    debounce:fn=>fn,guarded:fn=>fn,escapeHtml:x=>x,bytes:x=>x,date:x=>x,splitTags:x=>x.split('，'),toast:()=>{},loadOverview:async()=>{},loadImages:async()=>{}});
  vm.runInContext(picker+detail,context);
  const candidates={items:[{id:'p1',code:'001',name:'One'},{id:'p2',code:'002',name:'Two'}]};
  return {context,$,requests,state,image,candidates};
}
const test=async(name,fn)=>{await fn();console.log('PASS:',name);};

await test('dialog opens from list data before either request resolves; requests run concurrently; save waits for fresh data',async()=>{
  const f=fixture(),pending=f.context.openDetail('a');
  assert.equal(f.$('detail-dialog').open,true);
  assert.equal(f.$('detail-name').textContent,'Cached a');
  assert.equal(f.requests.length,2);
  assert.equal(f.$('submit').disabled,true);
  await f.$('detail-form').onsubmit({preventDefault(){}});
  assert.equal(f.requests.length,2);
  f.requests[1].resolve(f.candidates);
  f.requests[0].resolve({...f.image('a'),product_id:'p2',product_code:'002',product_name:'Fresh'});
  await pending;
  assert.equal(f.$('detail-name').textContent,'Fresh');
  assert.equal(f.$('detail-product').value,'p2');
  assert.equal(f.$('submit').disabled,false);
});

await test('subsequent images reuse cached candidates but still fetch current image details',async()=>{
  const f=fixture(),first=f.context.openDetail('a');
  f.requests[0].resolve(f.image('a'));f.requests[1].resolve(f.candidates);await first;
  f.$('detail-dialog').close();const next=f.context.openDetail('b');
  assert.equal(f.$('detail-name').textContent,'Cached b');
  assert.equal(f.requests.length,3);
  assert.equal(f.requests[2].route,'/api/images/b');
  f.requests[2].resolve(f.image('b'));await next;
});

await test('closing and reopening another image rejects late results from the first dialog',async()=>{
  const f=fixture(),first=f.context.openDetail('a');f.$('detail-dialog').close();
  const next=f.context.openDetail('b');
  f.requests[1].resolve(f.candidates);f.requests[2].resolve({...f.image('b'),product_name:'New B'});await next;
  f.requests[0].resolve({...f.image('a'),product_name:'Late A'});await first;
  assert.equal(f.$('detail-name').textContent,'New B');assert.equal(f.$('detail-id').value,'b');
});

await test('failed detail request disables saving and offers a retry without reloading successful candidates',async()=>{
  const f=fixture(),first=f.context.openDetail('a');
  f.requests[0].reject(new Error('unavailable'));f.requests[1].resolve(f.candidates);await first;
  assert.equal(f.$('submit').disabled,true);assert.equal(f.$('detail-retry').classList.contains('hidden'),false);
  const retry=f.$('detail-retry').onclick();assert.equal(f.requests.length,3);
  f.requests[2].resolve(f.image('a'));await retry;assert.equal(f.$('submit').disabled,false);
});

await test('failed product candidates are not cached and can be retried',async()=>{
  const f=fixture(),first=f.context.openDetail('a');
  f.requests[0].resolve(f.image('a'));f.requests[1].reject(new Error('products failed'));await first;
  assert.equal(f.$('submit').disabled,true);
  const retry=f.$('detail-retry').onclick();assert.equal(f.requests.length,4);
  f.requests[2].resolve(f.image('a'));f.requests[3].resolve(f.candidates);await retry;
  assert.equal(f.$('submit').disabled,false);
});

await test('candidate cache expires and an invalidated in-flight result cannot overwrite newer options',async()=>{
  const f=fixture();const one=f.context.getProductOptions(),shared=f.context.getProductOptions();assert.equal(one,shared);
  f.requests[0].resolve(f.candidates);await one;f.context.now=60001;
  const old=f.context.getProductOptions();assert.equal(f.requests.length,2);
  f.context.invalidateProductOptions();const newer=f.context.getProductOptions();assert.equal(f.requests.length,3);
  const fresh={items:[{id:'new',code:'003',name:'Fresh'}]};
  f.requests[2].resolve(fresh);await newer;f.requests[1].resolve(f.candidates);await old;
  assert.equal(await f.context.getProductOptions(),fresh);
});

await test('read-only viewers fetch no editable candidates and keep mutation controls disabled',async()=>{
  const f=fixture('external'),pending=f.context.openDetail('a');assert.equal(f.requests.length,1);
  f.requests[0].resolve(f.image('a'));await pending;
  assert.equal(f.$('submit').classList.contains('hidden'),true);assert.equal(f.$('detail-product').disabled,true);
  assert.equal(f.$('detail-trash').classList.contains('hidden'),true);
});
console.log('7 detail-loading and cache scenarios passed.');
