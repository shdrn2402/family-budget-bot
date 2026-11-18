-- Production schema snapshot (schema only: no data, owners or privileges).
-- Source: pg_dump --schema-only of the production database, 2026-11-18.
-- Used by tests/integration/test_migrations.py to check that the Alembic
-- baseline revision reproduces production exactly. Do not edit by hand.

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

CREATE SCHEMA budget;

CREATE FUNCTION budget.update_item_alias_on_category_change() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF NEW.category_id IS DISTINCT FROM OLD.category_id AND NEW.category_id IS NOT NULL THEN
        INSERT INTO item_aliases (name, category_id)
        VALUES (trim(lower(NEW.description)), NEW.category_id)
        ON CONFLICT (name) DO UPDATE 
        SET category_id = EXCLUDED.category_id;
    END IF;
    RETURN NEW;
END;
$$;

SET default_tablespace = '';

SET default_table_access_method = heap;

CREATE TABLE budget.account_aliases (
    id integer NOT NULL,
    name character varying(255) NOT NULL,
    account_id integer
);

CREATE SEQUENCE budget.account_aliases_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE budget.account_aliases_id_seq OWNED BY budget.account_aliases.id;

CREATE TABLE budget.accounts (
    id integer NOT NULL,
    owner_id bigint,
    name jsonb NOT NULL,
    type character varying(50) NOT NULL
);

CREATE SEQUENCE budget.accounts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE budget.accounts_id_seq OWNED BY budget.accounts.id;

CREATE TABLE budget.categories (
    id integer NOT NULL,
    name jsonb NOT NULL,
    parent_id integer
);

CREATE SEQUENCE budget.categories_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE budget.categories_id_seq OWNED BY budget.categories.id;

CREATE TABLE budget.item_aliases (
    id integer NOT NULL,
    name character varying(255) NOT NULL,
    category_id integer
);

CREATE SEQUENCE budget.item_aliases_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE budget.item_aliases_id_seq OWNED BY budget.item_aliases.id;

CREATE TABLE budget.transactions (
    id integer NOT NULL,
    user_id bigint,
    account_id integer,
    category_id integer,
    amount numeric(12,2) NOT NULL,
    description text,
    comment text,
    date timestamp with time zone NOT NULL,
    external_id character varying(255),
    source_type character varying(20),
    status character varying(20) DEFAULT 'confirmed'::character varying,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT transactions_source_type_check CHECK (((source_type)::text = ANY ((ARRAY['manual'::character varying, 'import_xls'::character varying, 'import_bit'::character varying, 'manual_text'::character varying, 'manual_voice'::character varying])::text[]))),
    CONSTRAINT transactions_status_check CHECK (((status)::text = ANY (ARRAY[('draft'::character varying)::text, ('pending'::character varying)::text, ('confirmed'::character varying)::text, ('adjustment'::character varying)::text])))
);

CREATE SEQUENCE budget.transactions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE budget.transactions_id_seq OWNED BY budget.transactions.id;

CREATE TABLE budget.users (
    id bigint NOT NULL,
    name character varying(255),
    is_admin boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE ONLY budget.account_aliases ALTER COLUMN id SET DEFAULT nextval('budget.account_aliases_id_seq'::regclass);

ALTER TABLE ONLY budget.accounts ALTER COLUMN id SET DEFAULT nextval('budget.accounts_id_seq'::regclass);

ALTER TABLE ONLY budget.categories ALTER COLUMN id SET DEFAULT nextval('budget.categories_id_seq'::regclass);

ALTER TABLE ONLY budget.item_aliases ALTER COLUMN id SET DEFAULT nextval('budget.item_aliases_id_seq'::regclass);

ALTER TABLE ONLY budget.transactions ALTER COLUMN id SET DEFAULT nextval('budget.transactions_id_seq'::regclass);

ALTER TABLE ONLY budget.account_aliases
    ADD CONSTRAINT account_aliases_name_key UNIQUE (name);

ALTER TABLE ONLY budget.account_aliases
    ADD CONSTRAINT account_aliases_pkey PRIMARY KEY (id);

ALTER TABLE ONLY budget.accounts
    ADD CONSTRAINT accounts_pkey PRIMARY KEY (id);

ALTER TABLE ONLY budget.categories
    ADD CONSTRAINT categories_pkey PRIMARY KEY (id);

ALTER TABLE ONLY budget.item_aliases
    ADD CONSTRAINT item_aliases_name_key UNIQUE (name);

ALTER TABLE ONLY budget.item_aliases
    ADD CONSTRAINT item_aliases_pkey PRIMARY KEY (id);

ALTER TABLE ONLY budget.transactions
    ADD CONSTRAINT transactions_external_id_key UNIQUE (external_id);

ALTER TABLE ONLY budget.transactions
    ADD CONSTRAINT transactions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY budget.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);

CREATE TRIGGER trg_update_item_alias AFTER UPDATE OF category_id ON budget.transactions FOR EACH ROW EXECUTE FUNCTION budget.update_item_alias_on_category_change();

ALTER TABLE ONLY budget.account_aliases
    ADD CONSTRAINT account_aliases_account_id_fkey FOREIGN KEY (account_id) REFERENCES budget.accounts(id) ON DELETE CASCADE;

ALTER TABLE ONLY budget.accounts
    ADD CONSTRAINT accounts_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES budget.users(id);

ALTER TABLE ONLY budget.categories
    ADD CONSTRAINT categories_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES budget.categories(id);

ALTER TABLE ONLY budget.item_aliases
    ADD CONSTRAINT item_aliases_category_id_fkey FOREIGN KEY (category_id) REFERENCES budget.categories(id) ON DELETE CASCADE;

ALTER TABLE ONLY budget.transactions
    ADD CONSTRAINT transactions_account_id_fkey FOREIGN KEY (account_id) REFERENCES budget.accounts(id);

ALTER TABLE ONLY budget.transactions
    ADD CONSTRAINT transactions_category_id_fkey FOREIGN KEY (category_id) REFERENCES budget.categories(id);

ALTER TABLE ONLY budget.transactions
    ADD CONSTRAINT transactions_user_id_fkey FOREIGN KEY (user_id) REFERENCES budget.users(id);
