-- MySQL schema for vehicle inventory (docker-compose init)

CREATE TABLE IF NOT EXISTS runs (
    run_id INT AUTO_INCREMENT PRIMARY KEY,
    queried_at TEXT NOT NULL,
    source VARCHAR(32) NOT NULL DEFAULT 'graphql',
    zip_code VARCHAR(16) NOT NULL,
    distance INT NOT NULL,
    page_size INT NOT NULL,
    lead_id TEXT,
    series_codes_json TEXT NOT NULL,
    archive_dir TEXT,
    notes TEXT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS series (
    series_code VARCHAR(64) PRIMARY KEY,
    marketing_series TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS model_catalog (
    model_code VARCHAR(64) PRIMARY KEY,
    series TEXT,
    title TEXT,
    year TEXT,
    msrp TEXT,
    image TEXT,
    as_shown TEXT,
    top_label TEXT,
    last_synced_at TEXT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS dealers (
    dealer_cd VARCHAR(32) PRIMARY KEY,
    dealer_marketing_name TEXT,
    dealer_website TEXT,
    dealer_category TEXT,
    distributor_cd TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS vehicles (
    vin VARCHAR(32) PRIMARY KEY,
    brand TEXT,
    series_code VARCHAR(64) NOT NULL,
    marketing_series TEXT,
    grade TEXT,
    dealer_trim TEXT,
    year INT,
    model_cd TEXT,
    model_marketing_name TEXT,
    model_marketing_title TEXT,
    transmission_type TEXT,
    fuel_type_code TEXT,
    fuel_type_name TEXT,
    engine_cd TEXT,
    engine_name TEXT,
    drivetrain_code TEXT,
    drivetrain_title TEXT,
    exterior_color_cd TEXT,
    exterior_color_name TEXT,
    exterior_color_hex TEXT,
    exterior_color_swatch TEXT,
    interior_color_cd TEXT,
    interior_color_name TEXT,
    interior_color_swatch TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    is_active TINYINT NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (series_code) REFERENCES series(series_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS vehicle_runs (
    vehicle_run_id INT AUTO_INCREMENT PRIMARY KEY,
    run_id INT NOT NULL,
    vin VARCHAR(32) NOT NULL,
    dealer_cd VARCHAR(32),
    stock_num TEXT,
    inventory_status TEXT,
    is_pre_sold TINYINT,
    is_smart_path TINYINT,
    is_unlock_price_dealer TINYINT,
    distance INT,
    inventory_mileage INT,
    vdp_url TEXT,
    family_json TEXT,
    cab_json TEXT,
    bed_json TEXT,
    mpg_city INT,
    mpg_highway INT,
    mpg_combined INT,
    allocation_stage_code VARCHAR(16),
    allocation_stage_label VARCHAR(64),
    created_at TEXT NOT NULL,
    UNIQUE KEY uq_vehicle_runs_run_vin (run_id, vin),
    FOREIGN KEY (run_id) REFERENCES runs(run_id),
    FOREIGN KEY (vin) REFERENCES vehicles(vin),
    FOREIGN KEY (dealer_cd) REFERENCES dealers(dealer_cd)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS vehicle_prices (
    vehicle_price_id INT AUTO_INCREMENT PRIMARY KEY,
    run_id INT NOT NULL,
    vin VARCHAR(32) NOT NULL,
    advertized_price DOUBLE,
    non_sp_advertized_price DOUBLE,
    total_msrp DOUBLE,
    selling_price DOUBLE,
    dph DOUBLE,
    dio_total_msrp DOUBLE,
    dio_total_dealer_selling_price DOUBLE,
    dealer_cash_applied DOUBLE,
    base_msrp DOUBLE,
    created_at TEXT NOT NULL,
    UNIQUE KEY uq_vehicle_prices_run_vin (run_id, vin),
    FOREIGN KEY (run_id) REFERENCES runs(run_id),
    FOREIGN KEY (vin) REFERENCES vehicles(vin)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS options (
    option_cd VARCHAR(64) PRIMARY KEY,
    marketing_name TEXT,
    marketing_long_name TEXT,
    option_type TEXT,
    package_ind TINYINT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS vehicle_options (
    vin VARCHAR(32) NOT NULL,
    option_cd VARCHAR(64) NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    PRIMARY KEY (vin, option_cd),
    FOREIGN KEY (vin) REFERENCES vehicles(vin),
    FOREIGN KEY (option_cd) REFERENCES options(option_cd)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS media (
    media_id INT AUTO_INCREMENT PRIMARY KEY,
    href TEXT NOT NULL,
    media_type TEXT,
    media_size TEXT,
    image_tag TEXT,
    source TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE KEY uq_media_href (href(255))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS vehicle_media (
    vin VARCHAR(32) NOT NULL,
    media_id INT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    PRIMARY KEY (vin, media_id),
    FOREIGN KEY (vin) REFERENCES vehicles(vin),
    FOREIGN KEY (media_id) REFERENCES media(media_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS vehicle_snapshots (
    snapshot_id INT AUTO_INCREMENT PRIMARY KEY,
    run_id INT NOT NULL,
    vin VARCHAR(32) NOT NULL,
    payload_gzip LONGBLOB NOT NULL,
    payload_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE KEY uq_vehicle_snapshots_run_vin (run_id, vin),
    FOREIGN KEY (run_id) REFERENCES runs(run_id),
    FOREIGN KEY (vin) REFERENCES vehicles(vin)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS job_runs (
    job_run_id INT AUTO_INCREMENT PRIMARY KEY,
    job_type VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL,
    started_at VARCHAR(64) NOT NULL,
    finished_at VARCHAR(64),
    duration_sec DOUBLE,
    params_json TEXT NOT NULL,
    result_json TEXT,
    error TEXT,
    message TEXT,
    trigger_source VARCHAR(32) NOT NULL DEFAULT 'ui'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE INDEX idx_vehicle_series ON vehicles(series_code);
CREATE INDEX idx_vehicle_active ON vehicles(is_active);
CREATE INDEX idx_vehicle_runs_vin ON vehicle_runs(vin);
CREATE INDEX idx_vehicle_prices_vin ON vehicle_prices(vin);
CREATE INDEX idx_vehicle_options_vin ON vehicle_options(vin);
CREATE INDEX idx_vehicle_runs_vin_run ON vehicle_runs(vin, run_id);
CREATE INDEX idx_vehicle_prices_vin_run ON vehicle_prices(vin, run_id);
CREATE INDEX idx_vehicle_runs_run_id ON vehicle_runs(run_id);
CREATE INDEX idx_vehicle_runs_dealer ON vehicle_runs(dealer_cd);
CREATE INDEX idx_vehicle_runs_stage_code ON vehicle_runs(allocation_stage_code);
CREATE INDEX idx_vehicles_active_series ON vehicles(is_active, series_code);
CREATE INDEX idx_job_runs_type_started ON job_runs(job_type, started_at);
CREATE INDEX idx_job_runs_started ON job_runs(started_at);

CREATE TABLE IF NOT EXISTS dealer_geo_cache (
    dealer_cd VARCHAR(32) PRIMARY KEY,
    query_text TEXT,
    latitude DOUBLE,
    longitude DOUBLE,
    postal_code TEXT,
    city TEXT,
    state TEXT,
    geocoded_at TEXT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS series_latest_runs (
    series_code VARCHAR(64) PRIMARY KEY,
    run_id INT NOT NULL,
    refreshed_at TEXT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE INDEX idx_series_latest_runs_run_id ON series_latest_runs(run_id);
