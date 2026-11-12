import { build } from 'esbuild';
import { DatabaseSync } from 'node:sqlite';
import { readFileSync, mkdirSync, existsSync } from 'node:fs';
import { scryptSync,createHash } from 'node:crypto';
import assert from 'node:assert/strict';
mkdirSync('work',{recursive:true});
await build({entryPoints:['lib/library.ts'],outfile:'work/library-test.mjs',bundle:true,platform:'node',format:'esm'});
const {handleLibrary}=await import('../work/library-test.mjs?'+Date.now());
const db=new DatabaseSync(':memory:');
const migrations=JSON.parse(readFileSync('drizzle/meta/_journal.json','utf8')).entries;
db.exec(readFileSync(`drizzle/${migrations[0].tag}.sql`,'utf8').replaceAll('--> statement-breakpoint',''));
const legacyToken='img_legacy_read';
db.prepare('INSERT INTO tokens(id,name,hash,prefix,created_at,last_used_at) VALUES(?,?,?,?,?,?)').run('0'.repeat(32),'Legacy read token',createHash('sha256').update(legacyToken).digest('hex'),'img_legacy',123,456);
for(const migration of migrations.slice(1)){
  if(migration.idx===2)db.prepare('INSERT INTO tokens(id,name,hash,prefix,created_at,scope) VALUES(?,?,?,?,?,?)').run('9'.repeat(32),'Existing create grant','existing-create-hash','img_create',789,'products:create');
  if(migration.idx===3)db.prepare('INSERT INTO tokens(id,name,hash,prefix,created_at,scope) VALUES(?,?,?,?,?,?)').run('8'.repeat(32),'Existing association grant','existing-assoc-hash','img_assoc',987,'images:associate');
  db.exec(readFileSync(`drizzle/${migration.tag}.sql`,'utf8').replaceAll('--> statement-breakpoint',''));
}
assert.equal(db.prepare('SELECT scope FROM tokens WHERE id=?').get('9'.repeat(32)).scope,'products:create');
assert.equal(db.prepare('SELECT scope FROM tokens WHERE id=?').get('8'.repeat(32)).scope,'images:associate');
assert.deepEqual({...db.prepare('SELECT scope,created_at,last_used_at FROM tokens WHERE id=?').get('0'.repeat(32))},{scope:'read',created_at:123,last_used_at:456});
const D1={prepare(sql){return {bind(...args){return {async first(){return db.prepare(sql).get(...args)||null;},async all(){return {results:db.prepare(sql).all(...args)};},async run(){return {meta:{changes:Number(db.prepare(sql).run(...args).changes)}};},sql,args};},sql,args:[],async all(){return {results:db.prepare(sql).all()};},async first(){return db.prepare(sql).get()||null;},async run(){return {meta:{changes:Number(db.prepare(sql).run().changes)}};}};},async batch(statements){db.exec('BEGIN');try{const result=statements.map(s=>({meta:{changes:Number(db.prepare(s.sql).run(...s.args).changes)}}));db.exec('COMMIT');return result;}catch(e){db.exec('ROLLBACK');throw e;}}};
const files=new Map();const BUCKET={async put(key,data,opts){files.set(key,{data:new Uint8Array(data),...opts});},async get(key){const f=files.get(key);return f?{size:f.data.length,body:new Blob([f.data]).stream(),httpEtag:'"test"'}:null;},async head(key){const f=files.get(key);return f?{size:f.data.length,customMetadata:f.customMetadata}:null;},async delete(keys){for(const key of Array.isArray(keys)?keys:[keys])files.delete(key);}};
const env={DB:D1,BUCKET,MIGRATION_KEY:'test-only-migration-key'},salt='ab'.repeat(16),pass='test-only-password-123';
db.prepare('INSERT INTO settings(key,value) VALUES(?,?)').run('username','testadmin');db.prepare('INSERT INTO settings(key,value) VALUES(?,?)').run('salt',salt);db.prepare('INSERT INTO settings(key,value) VALUES(?,?)').run('password_hash',scryptSync(pass,Buffer.from(salt,'hex'),64).toString('hex'));
let calls=0;
async function call(path,method='GET',body,auth='',expected=200,extra={}){const req=new Request('https://library.test'+path,{method,headers:{...(body?{'Content-Type':'application/json'}:{}),...(auth.startsWith('img_')?{Authorization:'Bearer '+auth}:auth?{Cookie:auth}:{}),...extra},...(body?{body:JSON.stringify(body)}:{})});const r=await handleLibrary(req,env);const value=await r.json();assert.equal(r.status,expected,`${method} ${path}: ${JSON.stringify(value)}`);calls++;return {value,response:r};}
const login=await call('/api/login','POST',{username:'testadmin',password:pass});const admin=login.response.headers.get('set-cookie').split(';')[0];assert.match(admin,/asset_session=/);
await call('/api/products','GET',null,'');
const guestStatus=(await call('/api/status','GET')).value;assert.equal(guestStatus.logged_in,false);assert.equal(guestStatus.role,'anonymous');assert.equal(guestStatus.can_create_products,false);assert.equal(guestStatus.can_associate_images,false);
await call('/api/products','POST',{code:'evil',name:'bad'},admin,403,{Origin:'https://evil.test'});
await call('/api/categories','POST',{name:'主板'},admin);
const p1=(await call('/api/products','POST',{code:'001234',name:'测试主板',category:'主板',aliases:['黑色']},admin)).value;
const p2=(await call('/api/products','POST',{code:'1234',name:'另一主板',category:'主板'},admin)).value;
assert.equal((await call('/api/products?q=001234','GET',null,admin)).value.items[0].id,p1.id);
assert.equal((await call('/api/products?q=1234','GET',null,admin)).value.items[0].id,p2.id);
assert.equal((await call('/api/products?q=黑色','GET',null,admin)).value.total,1);
await call('/api/products','POST',{code:'001234',name:'重复'},admin,409);
const staff=(await call('/api/accounts','POST',{username:'staff1',password:pass,role:'staff'},admin)).value;
const external=(await call('/api/accounts','POST',{username:'external1',password:pass,role:'external'},admin)).value;
const staffLogin=await call('/api/login','POST',{username:'staff1',password:pass});const sc=staffLogin.response.headers.get('set-cookie').split(';')[0];
const externalLogin=await call('/api/login','POST',{username:'external1',password:pass});const ec=externalLogin.response.headers.get('set-cookie').split(';')[0];
await call('/api/products','POST',{code:'staff',name:'职员产品'},sc);
await call('/api/products/'+p1.id,'DELETE',null,sc,403);
await call('/api/accounts','GET',null,sc,403);await call('/api/tokens','POST',{name:'external'},ec,404);
// Old tool credentials are rejected even when their database rows still exist.
for(const credential of [legacyToken,'img_legacy_combined']){
  if(credential!==legacyToken)db.prepare('INSERT INTO tokens(id,name,hash,prefix,created_at,scope) VALUES(?,?,?,?,?,?)').run('7'.repeat(32),'Legacy combined',createHash('sha256').update(credential).digest('hex'),'img_legacy',1,'products:create+images:associate');
  await call('/api/products','GET',null,credential,401);
  await call('/api/products','POST',{code:'tool-denied',name:'Denied'},credential,401);
}
for(const path of ['/api/tokens','/api/tokens/'+'0'.repeat(32),'/api/openapi.json'])for(const auth of ['',admin,sc])await call(path,'GET',null,auth,404);
await call('/api/tokens','POST',{name:'Cannot issue'},admin,404);
await call('/api/tokens/'+'0'.repeat(32),'DELETE',null,admin,404);
await call('/api/products','POST',{code:'tool-with-cookie',name:'Denied'},admin,401,{Authorization:'Bearer '+legacyToken});
const key='a'.repeat(32),data=Buffer.from('fixture original data'),digest=createHash('sha256').update(data).digest('hex');
db.prepare('INSERT INTO images(id,product_id,original_name,extension,mime_type,width,height,size,sha256,kind,angle,background,has_alpha,tags,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)').run(key,null,'1234-file.png','png','image/png',2000,2000,data.length,digest,'产品图','正面','透明',1,'[]',1);
await BUCKET.put('originals/'+key+'.png',data,{customMetadata:{sha256:digest}});await BUCKET.put('thumbnails/'+key+'.webp',data,{});
assert.equal((await call('/api/images?filename=1234','GET',null,admin)).value.total,1);
assert.equal((await call('/api/images?filename=1234','GET')).value.total,1);
assert.equal((await call('/api/images/'+key,'GET')).value.original_name,'1234-file.png');
await call('/api/overview','GET');await call('/api/categories','GET');
for(const path of ['/api/network','/api/accounts','/api/audit','/api/categories/manage','/api/categories/deletion-preview?name=主板','/api/products/'+p1.id+'/deletion-preview'])await call(path,'GET',null,'',401);
for(const [path,method,body] of [
 ['/api/products','POST',{code:'anon-denied',name:'Denied'}],['/api/products/'+p1.id,'PUT',{}],['/api/products/'+p1.id,'DELETE',{}],
 ['/api/images/upload','POST',{}],['/api/images/'+key,'PUT',{}],['/api/images/'+key,'DELETE',{}],['/api/images/'+key+'/restore','POST',{}],['/api/images/delete','POST',{image_ids:[key]}],
 ['/api/products/'+p1.id+'/images/associate','POST',{image_ids:[key]}],['/api/categories','POST',{name:'Denied'}],['/api/categories','PUT',{}],['/api/categories','DELETE',{}],
 ['/api/accounts','POST',{}],['/api/accounts/'+staff.id,'PUT',{}],['/api/accounts/'+staff.id,'DELETE',{}]
])await call(path,method,body,'',401);
await call('/api/products','GET',null,'img_invalid',401);
await call('/api/export','POST',{image_ids:[key]},'img_invalid',401);
await call('/api/images?trash=true','GET',null,'',403);
await call('/api/export','POST',{image_ids:[key]},'',403,{Origin:'https://evil.test'});
const guestOriginal=await handleLibrary(new Request('https://library.test/api/images/'+key+'/file'),env);
assert.equal(guestOriginal.status,200);assert.deepEqual(Buffer.from(await guestOriginal.arrayBuffer()),data);
const guestThumb=await handleLibrary(new Request('https://library.test/api/images/'+key+'/file?variant=thumbnail'),env);assert.equal(guestThumb.status,200);
const guestZip=await handleLibrary(new Request('https://library.test/api/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image_ids:[key]})}),env);assert.equal(guestZip.status,200);assert(Buffer.from(await guestZip.arrayBuffer()).includes(data));
assert(db.prepare("SELECT id FROM audit WHERE actor='anonymous' AND action='下载原图'").get());
await call('/api/logout','POST',{},'');

await call('/api/products/'+p1.id+'/images/associate','POST',{image_ids:[key,'f'.repeat(32)]},sc,409);
assert.equal(db.prepare('SELECT product_id FROM images WHERE id=?').get(key).product_id,null);
await call('/api/products/'+p1.id+'/images/associate','POST',{image_ids:[]},sc,400);
await call('/api/products/'+p1.id+'/images/associate','POST',{image_ids:['invalid']},sc,400);
await call('/api/products/'+p1.id+'/images/associate','POST',{image_ids:Array(101).fill(key)},sc,400);
await call('/api/products/'+p1.id+'/images/associate','POST',{image_ids:[key]},sc);
await call('/api/products/'+p2.id+'/images/associate','POST',{image_ids:[key]},sc,409);
assert.equal((await call('/api/images?product_code=001234','GET',null,'')).value.total,1);
const original=await handleLibrary(new Request(`https://library.test/api/images/${key}/file`,{}),env);assert.deepEqual(Buffer.from(await original.arrayBuffer()),data);assert.equal(original.status,200);
const zip=await handleLibrary(new Request('https://library.test/api/export',{method:'POST',headers:{Cookie:admin,'Content-Type':'application/json'},body:JSON.stringify({image_ids:[key]})}),env);const zipBytes=Buffer.from(await zip.arrayBuffer());assert.equal(zipBytes.readUInt32LE(0),0x04034b50);assert.equal(zipBytes.readUInt32LE(zipBytes.length-22),0x06054b50);assert(zipBytes.includes(data));
const before=(await call('/api/categories/deletion-preview?name=主板','GET',null,admin)).value;
await call('/api/products','POST',{code:'race',name:'并发变更',category:'主板'},admin);
await call('/api/categories','DELETE',{name:'主板',preview_token:before.preview_token},admin,409);
const latest=(await call('/api/categories/deletion-preview?name=主板','GET',null,admin)).value;
await call('/api/categories','PUT',{name:'主板',new_name:'主板新品'},admin);
const renamed=(await call('/api/categories/deletion-preview?name=主板新品','GET',null,admin)).value;
await call('/api/categories','DELETE',{name:'主板新品',preview_token:renamed.preview_token},admin);
assert.equal(db.prepare('SELECT product_id FROM images WHERE id=?').get(key).product_id,null);
await call('/api/images/delete','POST',{image_ids:[key]},admin,409);await call('/api/images/'+key,'DELETE',null,admin);
await call('/api/images/'+key,'GET',null,'',404);await call('/api/images/'+key+'/file','GET',null,'',404);await call('/api/images/'+key+'/file?variant=thumbnail','GET',null,'',404);await call('/api/export','POST',{image_ids:[key]},'',404);await call('/api/images?trash=true','GET',null,ec,403);await call('/api/images/'+key+'/restore','POST',{},admin);
await call('/api/images/'+key,'DELETE',null,admin);await call('/api/images/delete','POST',{image_ids:[key]},admin);assert.equal(files.size,0);
await call('/api/accounts/'+staff.id,'DELETE',null,admin);await call('/api/products','GET',null,sc);await call('/api/products','POST',{code:'expired-staff',name:'Denied'},sc,401);
await call('/api/accounts/'+external.id,'PUT',{password:'new-test-password-456'},admin);await call('/api/products','GET',null,ec);assert.equal((await call('/api/status','GET',null,ec)).value.logged_in,false);
await call('/api/migration/verify','GET',null,'',401);
await call('/api/migration/records','POST',{},admin,404);
await call('/api/migration/complete','POST',{},admin,404);
await call('/api/logout','POST',{},admin);await call('/api/products','GET',null,admin);assert.equal((await call('/api/status','GET',null,admin)).value.role,'anonymous');
const html=readFileSync('lib/library.html','utf8'),client=readFileSync('public/static/app.js','utf8');
assert(!html.includes('integrations-view'));assert(!client.includes('loadTokens'));
for(const path of ['mcp_bridge.py','tools/authorize_mcp_admin.py','public/mcp_bridge.py','public/authorize_mcp_admin.py'])assert(!existsSync(path),`Retired script remains: ${path}`);
console.log(`PASS: ${calls} API assertions plus browser-role isolation, original bytes, ZIP, association conflicts and removed tool endpoints.`);
