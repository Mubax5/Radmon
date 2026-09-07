-- Additive schema for Python Radmon admin/alarm/synchronization services.
-- Existing device/rawdata/measurement/alarm tables are not modified or removed.

CREATE TABLE IF NOT EXISTS `radmon_alarm_event` (
  `eventid` BIGINT NOT NULL AUTO_INCREMENT,
  `serid` INT NOT NULL,
  `state` VARCHAR(16) NOT NULL,
  `severity` VARCHAR(16) NOT NULL,
  `started_at` DATETIME NOT NULL,
  `ended_at` DATETIME DEFAULT NULL,
  `last_value` DOUBLE DEFAULT NULL,
  `threshold_value` DOUBLE DEFAULT NULL,
  `acknowledged_at` DATETIME DEFAULT NULL,
  `acknowledged_by` VARCHAR(128) DEFAULT NULL,
  `acknowledgement_note` VARCHAR(1000) DEFAULT NULL,
  `updated_at` DATETIME NOT NULL,
  PRIMARY KEY (`eventid`),
  KEY `idx_radmon_alarm_active` (`serid`, `ended_at`),
  KEY `idx_radmon_alarm_started` (`started_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `radmon_sync_queue` (
  `queueid` BIGINT NOT NULL AUTO_INCREMENT,
  `sample_key` CHAR(64) NOT NULL,
  `serid` INT NOT NULL,
  `dtom` DATETIME NOT NULL,
  `doserate` DOUBLE NOT NULL,
  `previnterval` INT NOT NULL DEFAULT 2,
  `stat` INT NOT NULL DEFAULT 0,
  `attempts` INT NOT NULL DEFAULT 0,
  `last_error` VARCHAR(1000) DEFAULT NULL,
  `sent_at` DATETIME DEFAULT NULL,
  `created_at` DATETIME NOT NULL,
  PRIMARY KEY (`queueid`),
  UNIQUE KEY `uk_radmon_sync_sample` (`sample_key`),
  KEY `idx_radmon_sync_pending` (`sent_at`, `queueid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `radmon_sync_receipt` (
  `sample_key` CHAR(64) NOT NULL,
  `received_at` DATETIME NOT NULL,
  `source_name` VARCHAR(128) DEFAULT NULL,
  PRIMARY KEY (`sample_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
