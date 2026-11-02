USE cs528_hw5;

CREATE TABLE IF NOT EXISTS countries (
  country_id   INT UNSIGNED NOT NULL AUTO_INCREMENT,
  country_name VARCHAR(64)  NOT NULL,
  is_banned    BOOLEAN      NOT NULL DEFAULT FALSE,
  PRIMARY KEY (country_id),
  UNIQUE KEY uq_country_name (country_name)
);

CREATE TABLE IF NOT EXISTS ip_addresses (
  client_ip  VARCHAR(45)  NOT NULL,
  country_id INT UNSIGNED NOT NULL,
  PRIMARY KEY (client_ip),
  FOREIGN KEY (country_id) REFERENCES countries (country_id)
);

CREATE TABLE IF NOT EXISTS requests (
  id             INT          NOT NULL,
  client_ip      VARCHAR(45)  NOT NULL,
  gender         VARCHAR(16)  NOT NULL,
  age            VARCHAR(32)  NOT NULL,
  income         VARCHAR(32)  NOT NULL,
  time_of_day    DATETIME     NOT NULL,
  requested_file VARCHAR(255) NOT NULL,
  PRIMARY KEY (id),
  FOREIGN KEY (client_ip) REFERENCES ip_addresses (client_ip)
);

INSERT IGNORE INTO countries (country_name, is_banned)
SELECT country, MAX(is_banned)
FROM successful_requests
GROUP BY country;

INSERT IGNORE INTO ip_addresses (client_ip, country_id)
SELECT s.client_ip, MIN(c.country_id)
FROM successful_requests s
JOIN countries c ON c.country_name = s.country
GROUP BY s.client_ip;

INSERT IGNORE INTO requests (id, client_ip, gender, age, income, time_of_day, requested_file)
SELECT id, client_ip, gender, age, income, time_of_day, requested_file
FROM successful_requests;
