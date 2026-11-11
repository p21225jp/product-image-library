// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 jacksonYWJ. Cloud adaptation of product-image-library.
import { createHash, randomBytes, scryptSync, timingSafeEqual } from 'node:crypto';
import { zipStream } from './zip';
import { inspectImage } from './image-format';

type Env = { DB:D1Database; BUCKET:R2Bucket };
type Actor = { role:string; id?:string|null; token?:boolean; upload?:boolean; createProducts?:boolean; associateImages?:boolean };
type Row = Record<string,any>;
const KINDS=['产品图','场景图','其他'], ANGLES=['正面','背面','侧面','俯视','仰视','其他'], BACKGROUNDS=['透明','其他'];
const COMBINED_SCOPE='products:create+images:associate';
const now=()=>Math.floor(Date.now()/1000), id=()=>randomBytes(16).toString('hex');
const hash=(v:string|Uint8Array)=>createHash('sha256').update(v).digest('hex');
const norm=(v:any)=>String(v??'').normalize('NFKC').trim();
function fail(status:number,detail:string):never {throw Object.assign(new Error(detail),{status});}
const json=(data:any,status=200,headers:Record<string,string>={})=>Response.json(data,{status,headers});
const equal=(a:string,b:string)=>a.length===b.length&&timingSafeEqual(Buffer.from(a),Buffer.from(b));
const passwordHash=(password:string,salt:string)=>scryptSync(password,Buffer.from(salt,'hex'),64,{N:16384,r:8,p:1}).toString('hex');
const like=(q:string)=>'%'+q.replace(/!/g,'!!').replace(/%/g,'!%').replace(/_/g,'!_')+'%';
const marks=(values:any[])=>values.map(()=>'?').join(',');
const text=(v:any,min=0,max=200)=>{if(typeof v!=='string'||v.length<min||v.length>max)fail(422,'请检查必填项和输入长度。');return v;};
const strings=(v:any,limit:number,length:number)=>{if(!Array.isArray(v)||v.length>limit||v.some(x=>typeof x!=='string'))fail(422,'列表内容或数量无效。');return [...new Set(v.map((x:string)=>norm(x).slice(0,length)).filter(Boolean))];};
const imageIds=(v:any)=>{if(!Array.isArray(v)||!v.length||v.length>100||v.some(x=>typeof x!=='string'||!/^[a-f0-9]{32}$/.test(x)))fail(400,'请选择 1 至 100 张有效图片。');return [...new Set(v)] as string[];};
const choices=(b:Row)=>{if(!KINDS.includes(b.kind)||!ANGLES.includes(b.angle)||!BACKGROUNDS.includes(b.background))fail(400,'图片类型、角度或背景无效。');};
const staff=(a:Actor)=>{if(a.token||!['admin','staff'].includes(a.role))fail(403,'此操作需要内部账号登录。');};
const admin=(a:Actor)=>{if(a.token||a.role!=='admin')fail(403,'此操作需要管理员登录。');};
const productCreator=(a:Actor)=>{if(a.token){if(!a.createProducts)fail(403,'新建产品需要管理员签发的 products:create 或新建产品与关联图片的联合授权令牌。');}else staff(a);};
const imageAssociator=(a:Actor)=>{if(a.token){if(!a.associateImages)fail(403,'关联图片需要管理员签发的 images:associate 或新建产品与关联图片的联合授权令牌。');}else staff(a);};
const label=(a:Actor)=>a.token?'token:'+a.id:a.role+(a.id?':'+a.id:'');
const accountJSON=(r:Row)=>({id:r.id,username:r.username,role:r.role,created_at:r.created_at,disabled:!!r.disabled_at});
const productJSON=(r:Row)=>({...r,aliases:JSON.parse(r.aliases)});
const imageJSON=(r:Row)=>{const {sha256,...rest}=r;return {...rest,tags:JSON.parse(r.tags),has_alpha:!!r.has_alpha,thumbnail_url:`/api/images/${r.id}/file?variant=thumbnail`,download_url:`/api/images/${r.id}/file`};};
const SELECT_IMAGE='SELECT i.*,p.code product_code,p.name product_name,p.category FROM images i LEFT JOIN products p ON p.id=i.product_id';
const filename=(r:Row)=>`${((r.product_code||'未关联')+'_'+r.kind+'_'+r.angle).replace(/[<>:"/\\|?*\x00-\x1f]/g,'_').slice(0,100).replace(/[. ]+$/,'')}_${r.id.slice(0,8)}.${r.extension}`;
function query(env:Env){
  const stmt=(s:string,...v:any[])=>env.DB.prepare(s).bind(...v);
  return {stmt,one:async(s:string,...v:any[])=>await stmt(s,...v).first<Row>(),all:async(s:string,...v:any[])=>(await stmt(s,...v).all<Row>()).results,run:async(s:string,...v:any[])=>stmt(s,...v).run()};
}
function bound(q:URLSearchParams,name:string,defaultValue:number,min:number,max:number){const raw=q.get(name);const n=raw===null?defaultValue:Number(raw);if(!Number.isInteger(n)||n<min||n>max)fail(422,'分页或筛选参数无效。');return n;}
async function body(req:Request){try{return await req.json() as Row;}catch{fail(400,'请求内容不是有效的 JSON。');}}
async function actor(req:Request,env:Env,optional=false):Promise<Actor|null>{
  const db=query(env), authorization=req.headers.get('authorization')||'';
  if(authorization.startsWith('Bearer ')){
    const r=await db.one('SELECT t.*,a.role owner_role,a.disabled_at,a.id owner_id FROM tokens t LEFT JOIN accounts a ON a.id=t.account_id WHERE t.hash=?',hash(authorization.slice(7)));
    if(r&&(!r.account_id||(r.owner_id&&r.disabled_at===null))){await db.run('UPDATE tokens SET last_used_at=? WHERE id=?',now(),r.id);return {role:'token',id:r.id,token:true,upload:r.owner_role==='staff',createProducts:['products:create',COMBINED_SCOPE].includes(r.scope)&&(!r.account_id||r.owner_role==='admin'),associateImages:['images:associate',COMBINED_SCOPE].includes(r.scope)&&(!r.account_id||r.owner_role==='admin')};}
  }else{
    const cookie=(req.headers.get('cookie')||'').split(';').map(x=>x.trim()).find(x=>x.startsWith('asset_session='))?.slice(14);
    if(cookie){const s=await db.one('SELECT * FROM sessions WHERE hash=? AND expires>?',hash(cookie),now());if(s){if(s.role==='admin'&&!s.account_id)return {role:'admin'};const a=await db.one('SELECT * FROM accounts WHERE id=? AND disabled_at IS NULL',s.account_id);if(a)return {role:a.role,id:a.id};}}
  }
  if(optional)return null;fail(401,'请先登录，或提供有效的访问令牌。');
}
async function cleanup(env:Env){const db=query(env);for(const r of await db.all('SELECT * FROM pending_deletes LIMIT 100')){try{await env.BUCKET.delete([`originals/${r.id}.${r.extension}`,`thumbnails/${r.id}.webp`]);await db.run('DELETE FROM pending_deletes WHERE id=?',r.id);}catch{/* Durable queue is retried on subsequent requests. */}}}
async function image(env:Env,key:string,deleted=false){const row=await query(env).one(SELECT_IMAGE+' WHERE i.id=?'+(deleted?'':' AND i.deleted_at IS NULL'),key);if(!row)fail(404,'图片不存在或已移入回收站。');return row;}
async function checkProduct(env:Env,key:any){if(key&&!await query(env).one('SELECT id FROM products WHERE id=?',key))fail(400,'所选产品不存在。');}
async function productValues(env:Env,b:Row){
  const code=norm(text(b.code,1,80)),name=norm(text(b.name,1,160));if(!code||!name)fail(400,'产品 SKU 和名称不能为空。');
  let category=norm(text(b.category??'',0,80));if(category){const r=await query(env).one('SELECT name FROM categories WHERE name=? COLLATE NOCASE',category);if(!r)fail(400,'请选择已有分类，或先创建分类。');category=r.name;}
  return [code,name,category,JSON.stringify(strings(b.aliases??[],30,100))];
}
async function mutation(env:Env,condition:string,values:any[],statements:D1PreparedStatement[]){
  const key=id(),db=query(env);
  try{await env.DB.batch([db.stmt(`INSERT INTO mutation_guards(id,ok) VALUES(?,CASE WHEN (${condition}) THEN 1 ELSE 0 END)`,key,...values),...statements,db.stmt('DELETE FROM mutation_guards WHERE id=?',key)]);}
  catch(e){if(String(e).includes('mutation_ok'))fail(409,'数据已发生变化，本次未修改。请刷新后重新确认。');throw e;}
}
async function categorySnapshot(env:Env,name:string){
  const db=query(env),category=await db.one('SELECT name FROM categories WHERE name=? COLLATE NOCASE',name)||await db.one('SELECT name FROM categories WHERE name=? COLLATE NOCASE',norm(name));if(!category)fail(404,'分类不存在或已被删除。');
  const sql=`SELECT json_array(?,json((SELECT json_group_array(id) FROM (SELECT id FROM products WHERE category=? COLLATE NOCASE ORDER BY id))),json((SELECT json_group_array(json_array(id,product_id,deleted_at)) FROM (SELECT i.id,i.product_id,i.deleted_at FROM images i JOIN products p ON p.id=i.product_id WHERE p.category=? COLLATE NOCASE ORDER BY i.id)))) snapshot`;
  const snap=(await db.one(sql,category.name,category.name,category.name))!.snapshot;
  const parsed=JSON.parse(snap),active=parsed[2].filter((r:any[])=>r[2]===null).length;
  return {sql,raw:snap,impact:{name:category.name,product_count:parsed[1].length,image_count:active,trashed_image_count:parsed[2].length-active,total_unlinked:parsed[2].length,preview_token:hash(snap)}};
}

async function route(req:Request,env:Env){
  if(!env.DB||!env.BUCKET)fail(503,'云端存储尚未就绪。');
  const u=new URL(req.url),path=u.pathname.replace(/\/$/,''),method=req.method,q=u.searchParams,db=query(env);
  if(method!=='GET'&&method!=='HEAD'){
    const origin=req.headers.get('origin');if(origin&&origin!==u.origin)fail(403,'拒绝跨站请求。');
    if(req.headers.get('sec-fetch-site')==='cross-site')fail(403,'拒绝跨站请求。');
  }
  const a=await actor(req,env,true);
  if(path==='/api/status'&&method==='GET')return json({configured:!!await db.one("SELECT value FROM settings WHERE key='password_hash'"),logged_in:!!a&&!a.token,role:a&&!a.token?a.role:null,can_setup:false,can_issue_tokens:!!a&&!a.token&&['admin','staff'].includes(a.role),can_associate_images:!!a&&(a.token?!!a.associateImages:['admin','staff'].includes(a.role)),can_create_products:!!a&&(a.token?!!a.createProducts:['admin','staff'].includes(a.role)),max_upload_mb:25,kinds:KINDS,angles:ANGLES,backgrounds:BACKGROUNDS,cloud:true});
  if(path==='/api/login'&&method==='POST'){
    const b=await body(req);text(b.username,3,40);text(b.password,1,200);
    const key=hash((req.headers.get('cf-connecting-ip')||'unknown')+':'+b.username.toLowerCase()),t=now();
    const attempt=await db.one('INSERT INTO login_attempts(key,attempts,started_at) VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET attempts=CASE WHEN started_at<? THEN 1 ELSE attempts+1 END,started_at=CASE WHEN started_at<? THEN ? ELSE started_at END RETURNING attempts',key,t,t-900,t-900,t);
    if(attempt!.attempts>8)fail(429,'尝试次数过多，请 15 分钟后再试。');
    const config=Object.fromEntries((await db.all("SELECT key,value FROM settings WHERE key IN ('username','salt','password_hash')")).map(r=>[r.key,r.value]));
    let account:Row|null=null;
    if(b.username===config.username&&config.salt&&equal(passwordHash(b.password,config.salt),config.password_hash))account={role:'admin',id:null};
    if(!account){const row=await db.one('SELECT * FROM accounts WHERE username=? COLLATE NOCASE AND disabled_at IS NULL',b.username);if(row&&equal(passwordHash(b.password,row.salt),row.password_hash))account=row;}
    if(!account)fail(401,'账号或密码不正确。');
    const secret=randomBytes(40).toString('base64url');await env.DB.batch([db.stmt('DELETE FROM login_attempts WHERE key=?',key),db.stmt('DELETE FROM sessions WHERE expires<=?',now()),db.stmt('INSERT INTO sessions(hash,expires,role,account_id) VALUES(?,?,?,?)',hash(secret),now()+28800,account.role,account.id)]);
    return json({ok:true,role:account.role},200,{'Set-Cookie':`asset_session=${secret}; Path=/; HttpOnly; SameSite=Strict; Max-Age=28800${u.protocol==='https:'?'; Secure':''}`});
  }
  if(path==='/api/setup')fail(403,'云端使用已迁移的管理员账号。');
  if(!a)fail(401,'请先登录，或提供有效的访问令牌。');
  const audit=async(action:string,detail='')=>db.run('INSERT INTO audit(action,actor,detail,created_at) VALUES(?,?,?,?)',action,label(a),detail.slice(0,500),now());
  if(path==='/api/logout'&&method==='POST'){
    if(a.token)fail(403,'请使用浏览器账号退出。');
    const cookie=(req.headers.get('cookie')||'').split(';').map(x=>x.trim()).find(x=>x.startsWith('asset_session='))?.slice(14)||'';await db.run('DELETE FROM sessions WHERE hash=?',hash(cookie));return json({ok:true},200,{'Set-Cookie':'asset_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0'});
  }
  if(path==='/api/network'){admin(a);return json({addresses:[u.origin],public_origin:u.origin});}
  if(path==='/api/overview'){
    if(a.token)fail(403,'概览需要浏览器账号登录。');
    const counts=await db.one('SELECT count(*) images,coalesce(sum(size),0) total_bytes,coalesce(sum(CASE WHEN product_id IS NULL THEN 1 ELSE 0 END),0) unassigned,coalesce(sum(has_alpha),0) transparent FROM images WHERE deleted_at IS NULL');
    return json({...counts,products:(await db.one('SELECT count(*) n FROM products'))!.n,trash:a.role==='admin'?(await db.one('SELECT count(*) n FROM images WHERE deleted_at IS NOT NULL'))!.n:0,categories:(await db.all('SELECT name FROM categories ORDER BY name')).map(r=>r.name)});
  }
  if(path==='/api/accounts'){
    admin(a);if(method==='GET')return json({items:(await db.all('SELECT * FROM accounts ORDER BY created_at DESC')).map(accountJSON)});
    if(method==='POST'){const b=await body(req);if(!/^[A-Za-z0-9_.-]{3,40}$/.test(b.username))fail(400,'账号使用 3 至 40 位字母、数字、下划线、点或短横线。');text(b.password,10,200);if(!['staff','external'].includes(b.role))fail(400,'账号角色无效。');if(await db.one("SELECT value FROM settings WHERE key='username' AND value=? COLLATE NOCASE",b.username))fail(409,'账号名与管理员相同。');const key=id(),salt=randomBytes(16).toString('hex');await db.run('INSERT INTO accounts(id,username,salt,password_hash,role,created_at) VALUES(?,?,?,?,?,?)',key,b.username,salt,passwordHash(b.password,salt),b.role,now());await audit('创建账号',b.username);return json(accountJSON((await db.one('SELECT * FROM accounts WHERE id=?',key))!));}
  }
  let m=path.match(/^\/api\/accounts\/([a-f0-9]{32})$/);
  if(m){admin(a);const row=await db.one('SELECT * FROM accounts WHERE id=?',m[1]);if(!row)fail(404,'账号不存在。');if(method==='PUT'){const b=await body(req);text(b.password,10,200);const salt=randomBytes(16).toString('hex');await env.DB.batch([db.stmt('UPDATE accounts SET salt=?,password_hash=? WHERE id=?',salt,passwordHash(b.password,salt),m[1]),db.stmt('DELETE FROM sessions WHERE account_id=?',m[1])]);await audit('重置账号密码',row.username);return json({ok:true});}if(method==='DELETE'){await env.DB.batch([db.stmt('DELETE FROM tokens WHERE account_id=?',m[1]),db.stmt('DELETE FROM sessions WHERE account_id=?',m[1]),db.stmt('DELETE FROM accounts WHERE id=?',m[1])]);await audit('删除账号',row.username);return json({ok:true});}}
  if(path==='/api/categories/manage'){admin(a);return json({items:await db.all('SELECT c.name,(SELECT count(*) FROM products p WHERE p.category=c.name COLLATE NOCASE) product_count,(SELECT count(*) FROM images i JOIN products p ON p.id=i.product_id WHERE p.category=c.name COLLATE NOCASE AND i.deleted_at IS NULL) image_count,(SELECT count(*) FROM images i JOIN products p ON p.id=i.product_id WHERE p.category=c.name COLLATE NOCASE AND i.deleted_at IS NOT NULL) trashed_image_count FROM categories c ORDER BY c.name')});}
  if(path==='/api/categories/deletion-preview'){admin(a);return json((await categorySnapshot(env,text(q.get('name'),1,80))).impact);}
  if(path==='/api/categories'){
    if(method==='GET')return json({items:(await db.all('SELECT name FROM categories ORDER BY name')).map(r=>r.name)});
    const b=await body(req),name=norm(text(b.name,1,80));if(!name)fail(400,'分类名称不能为空。');
    if(method==='POST'){staff(a);const result=await db.run('INSERT OR IGNORE INTO categories(name) VALUES(?)',name);const row=await db.one('SELECT name FROM categories WHERE name=? COLLATE NOCASE',name);if(result.meta.changes)await audit('新建分类',name);return json({name:row!.name,created:!!result.meta.changes});}
    admin(a);
    if(method==='PUT'){const existing=await db.one('SELECT name FROM categories WHERE name=? COLLATE NOCASE',b.name)||await db.one('SELECT name FROM categories WHERE name=? COLLATE NOCASE',name);if(!existing)fail(404,'分类不存在。');const next=norm(text(b.new_name,1,80));if(!next)fail(400,'分类名称不能为空。');const clash=await db.one('SELECT name FROM categories WHERE name=? COLLATE NOCASE AND name<>? COLLATE BINARY',next,existing.name);if(clash)fail(409,'此分类名称已存在。');const count=(await db.one('SELECT count(*) n FROM products WHERE category=? COLLATE NOCASE',existing.name))!.n;await env.DB.batch([db.stmt('UPDATE products SET category=? WHERE category=? COLLATE NOCASE',next,existing.name),db.stmt('UPDATE categories SET name=? WHERE name=?',next,existing.name)]);await audit('修改分类名称',`${existing.name} → ${next}`);return json({name:next,previous:existing.name,renamed:next!==existing.name,product_count:count});}
    if(method==='DELETE'){const snap=await categorySnapshot(env,b.name);if(b.preview_token!==snap.impact.preview_token)fail(409,'分类下的资料已变化，请重新确认删除范围。');const n=snap.impact.name;await mutation(env,`(${snap.sql})=?`,[n,n,n,snap.raw],[db.stmt('UPDATE images SET product_id=NULL WHERE product_id IN (SELECT id FROM products WHERE category=? COLLATE NOCASE)',n),db.stmt("UPDATE products SET category='' WHERE category=? COLLATE NOCASE",n),db.stmt('DELETE FROM categories WHERE name=?',n)]);await audit('删除分类并解绑图片',n);const {preview_token,...impact}=snap.impact;return json({deleted:true,...impact});}
  }
  if(path==='/api/products'){
    if(method==='GET'){
      const search=norm(text(q.get('q')??'',0,200)),category=norm(text(q.get('category')??'',0,80)),params:any[]=[],clauses=[];
      if(search){if(/^\p{Decimal_Number}+$/u.test(search)){clauses.push('p.code=? COLLATE NOCASE');params.push(search);}else{clauses.push("(p.code LIKE ? ESCAPE '!' OR p.name LIKE ? ESCAPE '!' OR EXISTS (SELECT 1 FROM json_each(p.aliases) WHERE value LIKE ? ESCAPE '!'))");params.push(...Array(3).fill(like(search)));}}
      if(category==='未分类')clauses.push("p.category=''");else if(category){clauses.push('p.category=? COLLATE NOCASE');params.push(category);}
      const where=clauses.length?' WHERE '+clauses.join(' AND '):'';const total=(await db.one('SELECT count(*) n FROM products p'+where,...params))!.n;
      const rows=await db.all('SELECT p.*,(SELECT count(*) FROM images i WHERE i.product_id=p.id AND i.deleted_at IS NULL) image_count FROM products p'+where+' ORDER BY (p.code=? COLLATE NOCASE) DESC,p.created_at DESC,p.id LIMIT ? OFFSET ?',...params,search,bound(q,'limit',100,1,200),bound(q,'offset',0,0,1e9));return json({items:rows.map(productJSON),total});
    }
    if(method==='POST'){productCreator(a);const b=await body(req),values=await productValues(env,b),key=id();await db.run('INSERT INTO products(id,code,name,category,aliases,created_at) VALUES(?,?,?,?,?,?)',key,...values,now());await audit('新建产品',values[0]);return json(productJSON((await db.one('SELECT * FROM products WHERE id=?',key))!));}
  }
  m=path.match(/^\/api\/products\/([a-f0-9]{32})(?:\/(deletion-preview|images\/associate))?$/);
  if(m){const key=m[1],row=await db.one('SELECT * FROM products WHERE id=?',key);if(!row)fail(404,'产品不存在，请刷新产品目录。');
    if(m[2]==='images/associate'&&method==='POST'){
      imageAssociator(a);const ids=imageIds((await body(req)).image_ids);const existing=await db.all(`SELECT id,product_id,deleted_at FROM images WHERE id IN (${marks(ids)})`,...ids);
      if(existing.length!==ids.length||existing.some(r=>r.deleted_at!==null||(r.product_id&&r.product_id!==key)))fail(409,'部分图片已删除或关联到其他产品，本次未关联任何图片。');
      const pending=existing.filter(r=>!r.product_id).length;
      await mutation(env,`EXISTS(SELECT 1 FROM products WHERE id=?) AND (SELECT count(*) FROM images WHERE id IN (${marks(ids)}) AND deleted_at IS NULL AND (product_id IS NULL OR product_id=?))=?`,[key,...ids,key,ids.length],[db.stmt(`UPDATE images SET product_id=? WHERE id IN (${marks(ids)}) AND product_id IS NULL`,key,...ids)]);
      await audit('批量关联产品图片',row.code);return json({ok:true,associated:pending,already_associated:ids.length-pending,product_id:key,image_count:(await db.one('SELECT count(*) n FROM images WHERE product_id=? AND deleted_at IS NULL',key))!.n});
    }
    if(m[2]==='deletion-preview'||method==='DELETE'){admin(a);const count=await db.one('SELECT sum(CASE WHEN deleted_at IS NULL THEN 1 ELSE 0 END) active,sum(CASE WHEN deleted_at IS NOT NULL THEN 1 ELSE 0 END) trashed FROM images WHERE product_id=?',key);const impact={id:key,code:row.code,name:row.name,image_count:count!.active||0,trashed_image_count:count!.trashed||0};if(method==='DELETE'){await env.DB.batch([db.stmt('UPDATE images SET product_id=NULL WHERE product_id=?',key),db.stmt('DELETE FROM products WHERE id=?',key)]);await audit('删除产品',row.code);return json({deleted:true,...impact});}return json(impact);}
    if(method==='PUT'){staff(a);const values=await productValues(env,await body(req));await db.run('UPDATE products SET code=?,name=?,category=?,aliases=? WHERE id=?',...values,key);await audit('修改产品',values[0]);return json({ok:true});}
  }
  if(path==='/api/images'&&method==='GET'){
    const trash=['true','1'].includes(q.get('trash')||''),clauses=[trash?'i.deleted_at IS NOT NULL':'i.deleted_at IS NULL'],params:any[]=[];if(trash)admin(a);
    for(const [column,param] of [['p.code','product_code'],['i.product_id','product_id'],['i.kind','kind'],['i.angle','angle'],['i.background','background'],['p.category','category']]){const value=norm(q.get(param));if(value){clauses.push(column+'=? COLLATE NOCASE');params.push(value);}}
    if(['true','1'].includes(q.get('unassigned')||''))clauses.push('i.product_id IS NULL');
    if(norm(q.get('filename'))){clauses.push("i.original_name LIKE ? ESCAPE '!'");params.push(like(norm(q.get('filename'))));}
    const minWidth=bound(q,'min_width',0,0,100000);if(minWidth){clauses.push('i.width>=?');params.push(minWidth);}
    const search=norm(text(q.get('q')??'',0,200));if(search){if(/^\p{Decimal_Number}+$/u.test(search)){clauses.push('p.code=? COLLATE NOCASE');params.push(search);}else{clauses.push("(p.code LIKE ? ESCAPE '!' OR p.name LIKE ? ESCAPE '!' OR i.original_name LIKE ? ESCAPE '!' OR EXISTS(SELECT 1 FROM json_each(p.aliases) WHERE value LIKE ? ESCAPE '!') OR EXISTS(SELECT 1 FROM json_each(i.tags) WHERE value LIKE ? ESCAPE '!'))");params.push(...Array(5).fill(like(search)));}}
    const where=' WHERE '+clauses.join(' AND '),total=(await db.one('SELECT count(*) n FROM images i LEFT JOIN products p ON p.id=i.product_id'+where,...params))!.n;
    return json({items:(await db.all(SELECT_IMAGE+where+' ORDER BY (p.code=? COLLATE NOCASE) DESC,i.created_at DESC,i.id LIMIT ? OFFSET ?',...params,search,bound(q,'limit',48,1,100),bound(q,'offset',0,0,1e9))).map(imageJSON),total});
  }
  if(path==='/api/images/upload'&&method==='POST'){
    if(!['admin','staff'].includes(a.role)&&!a.upload)fail(403,'外部账号和只读令牌不可上传图片。');
    const length=Number(req.headers.get('content-length'));if(!Number.isFinite(length)||length>28*1024*1024)fail(413,'上传内容超过允许大小。');
    const form=await req.formData(),file=form.get('file') as File,thumb=form.get('thumbnail') as File;
    if(!file||typeof file.arrayBuffer!=='function'||!file.size||file.size>25*1024*1024)fail(400,'请选择 25 MB 以内的 JPG、PNG 或 WebP 图片。');
    if(!thumb||typeof thumb.arrayBuffer!=='function'||thumb.size>2*1024*1024)fail(400,'请使用云端网页上传，或随请求提供 WebP 缩略图。');
    const b={product_id:String(form.get('product_id')||''),kind:String(form.get('kind')||'产品图'),angle:String(form.get('angle')||'正面'),background:String(form.get('background')||'透明')};choices(b);await checkProduct(env,b.product_id);
    const bytes=new Uint8Array(await file.arrayBuffer()),info=inspectImage(bytes);if(info.width*info.height>40000000)fail(400,'图片不能超过 4000 万像素。');
    const alpha=form.get('has_alpha')==='true';if(alpha&&!info.alphaPossible)fail(400,'此文件没有透明通道。');if(b.background==='透明'&&!alpha)fail(400,'此文件没有透明像素，请改选「其他」背景。');
    const thumbBytes=new Uint8Array(await thumb.arrayBuffer()),ti=inspectImage(thumbBytes);if(ti.extension!=='webp'||ti.width>720||ti.height>720)fail(400,'缩略图格式或尺寸无效。');
    const w=Number(form.get('display_width')),h=Number(form.get('display_height'));if(!((w===info.width&&h===info.height)||(w===info.height&&h===info.width)))fail(400,'图片尺寸校验失败。');
    const digest=hash(bytes),duplicate=await db.one('SELECT id FROM images WHERE sha256=? AND coalesce(product_id,\'\')=? AND deleted_at IS NULL',digest,b.product_id);
    if(duplicate)return json({duplicate:true,image:imageJSON(await image(env,duplicate.id))});
    const key=id(),original=`originals/${key}.${info.extension}`,thumbnail=`thumbnails/${key}.webp`;
    try{
      await env.BUCKET.put(original,bytes,{httpMetadata:{contentType:info.mime},customMetadata:{sha256:digest}});await env.BUCKET.put(thumbnail,thumbBytes,{httpMetadata:{contentType:'image/webp'}});
      const tags=strings(String(form.get('tags')||'').split(/[,，]/),20,40);
      await db.run('INSERT INTO images(id,product_id,original_name,extension,mime_type,width,height,size,sha256,kind,angle,background,has_alpha,tags,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',key,b.product_id||null,file.name.slice(0,200),info.extension,info.mime,w,h,file.size,digest,b.kind,b.angle,alpha?'透明':'其他',alpha?1:0,JSON.stringify(tags),now());
    }catch(e){await env.BUCKET.delete([original,thumbnail]);throw e;}
    await audit('上传图片',key);return json({duplicate:false,image:imageJSON(await image(env,key))});
  }
  if(path==='/api/images/delete'&&method==='POST'){
    admin(a);const ids=imageIds((await body(req)).image_ids);const rows=await db.all(`SELECT id,extension FROM images WHERE id IN (${marks(ids)}) AND deleted_at IS NOT NULL`,...ids);if(rows.length!==ids.length)fail(409,'请先把全部图片移入回收站，再永久删除。');
    await mutation(env,`(SELECT count(*) FROM images WHERE id IN (${marks(ids)}) AND deleted_at IS NOT NULL)=?`,[...ids,ids.length],[...rows.map(r=>db.stmt('INSERT INTO pending_deletes(id,extension,created_at) VALUES(?,?,?)',r.id,r.extension,now())),db.stmt(`DELETE FROM images WHERE id IN (${marks(ids)})`,...ids)]);await cleanup(env);await audit('永久删除图片',ids.join(','));return json({ok:true,deleted:ids.length,cleanup_pending:(await db.one('SELECT count(*) n FROM pending_deletes'))!.n});
  }
  m=path.match(/^\/api\/images\/([a-f0-9]{32})(?:\/(file|restore))?$/);
  if(m){
    const key=m[1],variant=q.get('variant')||'original',row=await image(env,key,(a.role==='admin'&&!a.token)&&(m[2]==='restore'||variant==='thumbnail'));
    if(m[2]==='file'&&method==='GET'){
      if(!['original','thumbnail'].includes(variant))fail(422,'图片版本无效。');
      const object=await env.BUCKET.get(variant==='thumbnail'?`thumbnails/${key}.webp`:`originals/${key}.${row.extension}`);if(!object)fail(404,'图片文件不存在。');if(variant==='original')await audit('下载原图',key);
      return new Response(object.body,{headers:{'Content-Type':variant==='thumbnail'?'image/webp':row.mime_type,'Content-Length':String(object.size),'ETag':object.httpEtag,...(variant==='original'?{'Content-Disposition':`attachment; filename="product-${key.slice(0,8)}.${row.extension}"; filename*=UTF-8''${encodeURIComponent(filename(row))}`}:{})}});
    }
    if(m[2]==='restore'&&method==='POST'){admin(a);await db.run('UPDATE images SET deleted_at=NULL WHERE id=?',key);await audit('恢复图片',key);return json({ok:true});}
    if(!m[2]){
      if(method==='GET')return json(imageJSON(row));
      if(method==='PUT'){staff(a);const b=await body(req);choices(b);await checkProduct(env,b.product_id);if((b.background==='透明')!==!!row.has_alpha)fail(400,'背景分类必须与文件的透明属性一致。');await db.run('UPDATE images SET product_id=?,kind=?,angle=?,background=?,tags=? WHERE id=?',b.product_id||null,b.kind,b.angle,b.background,JSON.stringify(strings(b.tags??[],20,40)),key);await audit('修改图片资料',key);return json(imageJSON(await image(env,key)));}
      if(method==='DELETE'){admin(a);await db.run('UPDATE images SET deleted_at=? WHERE id=?',now(),key);await audit('移入回收站',key);return json({ok:true});}
    }
  }
  if(path==='/api/export'&&method==='POST'){
    const ids=imageIds((await body(req)).image_ids),rows=[];for(const key of ids)rows.push(await image(env,key));if(rows.reduce((s,r)=>s+r.size,0)>500*1024*1024)fail(400,'单次打包上限为 500 MB，请分批下载。');
    // Resolve every object before returning a streaming response, so missing files yield a clear error.
    const objects=[];for(const row of rows){const object=await env.BUCKET.get(`originals/${row.id}.${row.extension}`);if(!object)fail(404,'部分原图不存在。');objects.push({object,name:filename(row)});}
    await audit('批量下载',ids.join(','));return new Response(zipStream(objects),{headers:{'Content-Type':'application/zip','Content-Disposition':'attachment; filename="product-images.zip"'}});
  }
  if(path==='/api/tokens'){
    staff(a);
    if(method==='GET')return json({items:await db.all('SELECT t.id,t.name,t.prefix,t.scope,t.created_at,t.last_used_at,a.username owner FROM tokens t LEFT JOIN accounts a ON a.id=t.account_id'+(a.role==='admin'?'':' WHERE t.account_id=?')+' ORDER BY t.created_at DESC',...(a.role==='admin'?[]:[a.id]))});
    if(method==='POST'){
      const b=await body(req),name=text(b.name,1,60).trim(),scope=b.scope??'read';if(!name)fail(400,'令牌名称不能为空。');
      if(!['read','products:create','images:associate',COMBINED_SCOPE].includes(scope))fail(400,'令牌权限无效。');if(scope!=='read')admin(a);
      const key=id(),secret='img_'+randomBytes(32).toString('base64url');await db.run('INSERT INTO tokens(id,name,hash,prefix,created_at,account_id,scope) VALUES(?,?,?,?,?,?,?)',key,name,hash(secret),secret.slice(0,10),now(),a.id||null,scope);await audit(scope===COMBINED_SCOPE?'授权工具新建产品和关联图片':scope==='products:create'?'授权工具新建产品':scope==='images:associate'?'授权工具关联图片':'创建令牌',name);return json({id:key,token:secret,name,scope});
    }
  }
  m=path.match(/^\/api\/tokens\/([a-f0-9]{32})$/);if(m&&method==='DELETE'){staff(a);const row=await db.one('SELECT * FROM tokens WHERE id=?',m[1]);if(!row)fail(404,'令牌不存在。');if(a.role!=='admin'&&row.account_id!==a.id)fail(403,'只能撤销自己创建的令牌。');await db.run('DELETE FROM tokens WHERE id=?',m[1]);await audit('撤销令牌',row.name);return json({ok:true});}
  if(path==='/api/audit'){admin(a);await cleanup(env);return json({items:await db.all('SELECT * FROM audit ORDER BY id DESC LIMIT 100')});}
  if(path==='/api/openapi.json'){
    const paths:Record<string,any>=Object.fromEntries(['/api/products','/api/categories','/api/images','/api/images/{id}','/api/images/{id}/file'].map(p=>[p,{get:{responses:{200:{description:'查询结果'}},security:[{bearerAuth:[]}]}}]));
    paths['/api/products'].post={summary:'新建产品',description:'MCP 调用需要管理员签发的 products:create 或 products:create+images:associate 令牌。重复 SKU 返回 409，不覆盖已有产品；分类必须已存在。',security:[{bearerAuth:[]}],requestBody:{required:true,content:{'application/json':{schema:{type:'object',required:['code','name'],properties:{code:{type:'string',minLength:1,maxLength:80,description:'产品 SKU，保留前导零'},name:{type:'string',minLength:1,maxLength:160},category:{type:'string',maxLength:80,default:''},aliases:{type:'array',maxItems:30,items:{type:'string',maxLength:100},default:[]}}}}}},responses:{200:{description:'已创建产品'},401:{description:'令牌无效'},403:{description:'未获管理员新建产品授权'},409:{description:'SKU 已存在'}}};
    paths['/api/products/{id}/images/associate']={post:{summary:'批量关联已有图片',description:'需要管理员签发的 images:associate 或 products:create+images:associate 令牌；每批 1～100 张，已关联同一产品时跳过；任一图片已关联其他产品、在回收站或不存在时整批拒绝。',security:[{bearerAuth:[]}],requestBody:{required:true,content:{'application/json':{schema:{type:'object',required:['image_ids'],properties:{image_ids:{type:'array',minItems:1,maxItems:100,items:{type:'string',pattern:'^[a-f0-9]{32}$'}}}}}}},responses:{200:{description:'关联结果'},403:{description:'未授权'},409:{description:'图片归属冲突，整批未关联'}}}};
    return json({openapi:'3.1.0',info:{title:'MKT团队素材空间',version:'1.1.0-cloud'},servers:[{url:u.origin}],paths,components:{securitySchemes:{bearerAuth:{type:'http',scheme:'bearer'}}}});
  }
  fail(404,'接口不存在。');
}
export async function handleLibrary(req:Request,env:Env){
  let response:Response;
  try{response=await route(req,env);}catch(error:any){
    if(error.status)response=json({detail:error.message},error.status);
    else if(/UNIQUE constraint failed/.test(String(error)))response=json({detail:'SKU、账号或分类名称已存在。'},409);
    else{console.error('library_request_failed',new URL(req.url).pathname,error);response=json({detail:'服务暂时无法完成请求，请稍后重试。'},500);}
  }
  response.headers.set('Cache-Control','private, no-store');response.headers.set('X-Content-Type-Options','nosniff');response.headers.set('Referrer-Policy','no-referrer');return response;
}
