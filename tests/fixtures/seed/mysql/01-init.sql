-- MySQL seed: init.sql
-- Creates 2 databases with tables and users.

-- Database 1: app_store
CREATE DATABASE IF NOT EXISTS app_store;
USE app_store;

CREATE TABLE products (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    price DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
    sku VARCHAR(50) UNIQUE,
    category VARCHAR(100),
    stock_quantity INT NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE categories (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    parent_id INT,
    sort_order INT DEFAULT 0,
    FOREIGN KEY (parent_id) REFERENCES categories(id)
);

CREATE TABLE suppliers (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    contact_email VARCHAR(200),
    contact_phone VARCHAR(50),
    address TEXT,
    country VARCHAR(100),
    active BOOLEAN DEFAULT TRUE
);

CREATE TABLE users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    email VARCHAR(200) UNIQUE NOT NULL,
    bio TEXT,
    phone VARCHAR(50),
    city VARCHAR(100),
    country VARCHAR(100),
    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP NULL
);

CREATE TABLE orders (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    product_id INT NOT NULL,
    quantity INT NOT NULL DEFAULT 1,
    total_price DECIMAL(10, 2) NOT NULL,
    status VARCHAR(50) DEFAULT 'pending',
    order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    shipped_date TIMESTAMP NULL,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (product_id) REFERENCES products(id)
);

CREATE TABLE reviews (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    product_id INT NOT NULL,
    rating INT CHECK (rating >= 1 AND rating <= 5),
    comment TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (product_id) REFERENCES products(id)
);

-- Database 2: analytics
CREATE DATABASE IF NOT EXISTS analytics;
USE analytics;

CREATE TABLE events (
    id INT AUTO_INCREMENT PRIMARY KEY,
    event_type VARCHAR(100) NOT NULL,
    payload JSON,
    source VARCHAR(100),
    session_id VARCHAR(200),
    user_id INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_event_type (event_type),
    INDEX idx_created_at (created_at)
);

CREATE TABLE daily_stats (
    id INT AUTO_INCREMENT PRIMARY KEY,
    stat_date DATE NOT NULL,
    metric_name VARCHAR(100) NOT NULL,
    metric_value DECIMAL(12, 2) NOT NULL,
    dimension VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_stat (stat_date, metric_name, dimension)
);

CREATE TABLE funnels (
    id INT AUTO_INCREMENT PRIMARY KEY,
    funnel_name VARCHAR(200) NOT NULL,
    step_number INT NOT NULL,
    step_name VARCHAR(200) NOT NULL,
    user_count INT NOT NULL DEFAULT 0,
    conversion_rate DECIMAL(5, 2),
    report_date DATE NOT NULL
);

-- Users/Roles
CREATE USER IF NOT EXISTS 'app_readonly'@'%' IDENTIFIED BY 'test-readonly-pass';
GRANT SELECT ON app_store.* TO 'app_readonly'@'%';

CREATE USER IF NOT EXISTS 'analytics_reader'@'%' IDENTIFIED BY 'test-analytics-pass';
GRANT SELECT ON analytics.* TO 'analytics_reader'@'%';

CREATE USER IF NOT EXISTS 'backup_user'@'%' IDENTIFIED BY 'test-backup-pass';
GRANT SELECT, RELOAD, LOCK TABLES, REPLICATION CLIENT, SHOW VIEW, EVENT, TRIGGER ON *.* TO 'backup_user'@'%';

FLUSH PRIVILEGES;
