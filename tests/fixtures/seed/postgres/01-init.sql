-- PostgreSQL seed: init.sql
-- Creates 2 databases with schemas, tables, and roles.

-- Database 1: app_store
CREATE DATABASE app_store;
\c app_store

CREATE SCHEMA inventory;
CREATE SCHEMA customers;

CREATE TABLE inventory.products (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    price NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    sku VARCHAR(50) UNIQUE,
    category VARCHAR(100),
    stock_quantity INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE inventory.categories (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    parent_id INTEGER REFERENCES inventory.categories(id),
    sort_order INTEGER DEFAULT 0
);

CREATE TABLE inventory.suppliers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    contact_email VARCHAR(200),
    contact_phone VARCHAR(50),
    address TEXT,
    country VARCHAR(100),
    active BOOLEAN DEFAULT TRUE
);

CREATE TABLE customers.users (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    email VARCHAR(200) UNIQUE NOT NULL,
    bio TEXT,
    phone VARCHAR(50),
    address TEXT,
    city VARCHAR(100),
    country VARCHAR(100),
    joined_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_login TIMESTAMP WITH TIME ZONE
);

CREATE TABLE customers.orders (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES customers.users(id),
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    total_price NUMERIC(10, 2) NOT NULL,
    status VARCHAR(50) DEFAULT 'pending',
    order_date TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    shipped_date TIMESTAMP WITH TIME ZONE
);

CREATE TABLE customers.reviews (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES customers.users(id),
    product_id INTEGER NOT NULL,
    rating INTEGER CHECK (rating >= 1 AND rating <= 5),
    comment TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Database 2: analytics
CREATE DATABASE analytics;
\c analytics

CREATE SCHEMA reporting;

CREATE TABLE reporting.events (
    id SERIAL PRIMARY KEY,
    event_type VARCHAR(100) NOT NULL,
    payload JSONB,
    source VARCHAR(100),
    session_id VARCHAR(200),
    user_id INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE reporting.daily_stats (
    id SERIAL PRIMARY KEY,
    stat_date DATE NOT NULL,
    metric_name VARCHAR(100) NOT NULL,
    metric_value NUMERIC(12, 2) NOT NULL,
    dimension VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(stat_date, metric_name, dimension)
);

CREATE TABLE reporting.funnels (
    id SERIAL PRIMARY KEY,
    funnel_name VARCHAR(200) NOT NULL,
    step_number INTEGER NOT NULL,
    step_name VARCHAR(200) NOT NULL,
    user_count INTEGER NOT NULL DEFAULT 0,
    conversion_rate NUMERIC(5, 2),
    report_date DATE NOT NULL
);

-- Roles
\c postgres
CREATE ROLE app_readonly LOGIN PASSWORD 'test-readonly-pass';
GRANT CONNECT ON DATABASE app_store TO app_readonly;

CREATE ROLE analytics_reader LOGIN PASSWORD 'test-analytics-pass';
GRANT CONNECT ON DATABASE analytics TO analytics_reader;

CREATE ROLE backup_user LOGIN PASSWORD 'test-backup-pass' REPLICATION;
