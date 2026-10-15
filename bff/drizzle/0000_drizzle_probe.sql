CREATE SCHEMA "ui";
--> statement-breakpoint
CREATE TABLE "ui"."drizzle_probe" (
	"id" serial PRIMARY KEY NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
