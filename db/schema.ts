import { sqliteTable, text, integer, index, check, uniqueIndex } from 'drizzle-orm/sqlite-core';
import { sql } from 'drizzle-orm';
export const settings = sqliteTable('settings', { key:text().primaryKey(), value:text().notNull() });
export const categories = sqliteTable('categories', { name:text().primaryKey() },t=>[uniqueIndex('category_name_nocase').on(sql`lower(${t.name})`)]);
export const products = sqliteTable('products', {
  id:text().primaryKey(), code:text().notNull(), name:text().notNull(), brand:text().notNull().default(''),
  category:text().notNull().default(''), aliases:text().notNull().default('[]'), created_at:integer().notNull()
}, t=>[uniqueIndex('products_code_nocase').on(sql`lower(${t.code})`)]);
export const images = sqliteTable('images', {
  id:text().primaryKey(), product_id:text().references(()=>products.id), original_name:text().notNull(),
  extension:text().notNull(), mime_type:text().notNull(), width:integer().notNull(), height:integer().notNull(),
  size:integer().notNull(), sha256:text().notNull(), kind:text().notNull(), angle:text().notNull(),
  background:text().notNull(), has_alpha:integer().notNull(), tags:text().notNull().default('[]'),
  created_at:integer().notNull(), deleted_at:integer()
},t=>[index('image_product').on(t.product_id),index('image_hash').on(t.sha256),index('image_created').on(t.created_at)]);
export const accounts = sqliteTable('accounts', {
  id:text().primaryKey(), username:text().notNull(), salt:text().notNull(), password_hash:text().notNull(),
  role:text().notNull(), created_at:integer().notNull(), disabled_at:integer()
},t=>[check('account_role',sql`${t.role} in ('staff','external')`),uniqueIndex('account_name_nocase').on(sql`lower(${t.username})`)]);
export const sessions = sqliteTable('sessions', { hash:text().primaryKey(), expires:integer().notNull(), role:text().notNull().default('admin'), account_id:text() });
export const tokens = sqliteTable('tokens', { id:text().primaryKey(), name:text().notNull(), hash:text().notNull().unique(), prefix:text().notNull(), created_at:integer().notNull(), account_id:text(), last_used_at:integer(), scope:text().notNull().default('read') },t=>[check('token_scope',sql`${t.scope} in ('read','products:create','images:associate','products:create+images:associate')`)]);
export const audit = sqliteTable('audit', { id:integer().primaryKey({autoIncrement:true}), action:text().notNull(), actor:text().notNull(), detail:text().notNull(), created_at:integer().notNull() });
export const pendingDeletes = sqliteTable('pending_deletes',{ id:text().primaryKey(), extension:text().notNull(), created_at:integer().notNull() });
export const loginAttempts = sqliteTable('login_attempts',{ key:text().primaryKey(), attempts:integer().notNull(), started_at:integer().notNull() });
export const mutationGuards = sqliteTable('mutation_guards',{ id:text().primaryKey(), ok:integer().notNull() },t=>[check('mutation_ok',sql`${t.ok}=1`)]);
