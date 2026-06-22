CREATE TABLE sample_device (
  id BIGINT PRIMARY KEY,
  device_code VARCHAR(64) NOT NULL,
  device_name VARCHAR(128) NOT NULL,
  site_name VARCHAR(128) NOT NULL,
  status VARCHAR(32) NOT NULL,
  updated_at DATETIME NOT NULL
);

INSERT INTO sample_device (id, device_code, device_name, site_name, status, updated_at) VALUES
(1, 'SB-001', 'Camera A01', 'North Canal Gate', 'OK', '2026-06-22 09:30:00'),
(2, 'SB-002', 'Sensor B02', 'East Pump Station', 'RECOVERED', '2026-06-22 09:40:00');
