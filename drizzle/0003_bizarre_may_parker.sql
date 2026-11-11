PRAGMA foreign_keys=OFF;--> statement-breakpoint
CREATE TABLE `__new_tokens` (
	`id` text PRIMARY KEY NOT NULL,
	`name` text NOT NULL,
	`hash` text NOT NULL,
	`prefix` text NOT NULL,
	`created_at` integer NOT NULL,
	`account_id` text,
	`last_used_at` integer,
	`scope` text DEFAULT 'read' NOT NULL,
	CONSTRAINT "token_scope" CHECK("__new_tokens"."scope" in ('read','products:create','images:associate','products:create+images:associate'))
);
--> statement-breakpoint
INSERT INTO `__new_tokens`("id", "name", "hash", "prefix", "created_at", "account_id", "last_used_at", "scope") SELECT "id", "name", "hash", "prefix", "created_at", "account_id", "last_used_at", "scope" FROM `tokens`;--> statement-breakpoint
DROP TABLE `tokens`;--> statement-breakpoint
ALTER TABLE `__new_tokens` RENAME TO `tokens`;--> statement-breakpoint
PRAGMA foreign_keys=ON;--> statement-breakpoint
CREATE UNIQUE INDEX `tokens_hash_unique` ON `tokens` (`hash`);