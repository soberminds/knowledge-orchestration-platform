-- KOP v1 增量迁移：索引任务与文件级进度表
-- 用途：已有数据库不重建时，执行本脚本增加后台索引任务追踪能力。

USE `KOP`;

CREATE TABLE IF NOT EXISTS `kop_index_job` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '索引任务ID',
  `user_id` BIGINT UNSIGNED NOT NULL COMMENT '所属用户ID',
  `job_type` VARCHAR(32) NOT NULL DEFAULT 'files' COMMENT '任务类型：files、full、office',
  `status` VARCHAR(32) NOT NULL DEFAULT 'queued' COMMENT '任务状态：queued、running、success、failed、cancelled',
  `total_files` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '文件总数',
  `finished_files` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '已完成文件数，包含成功和失败',
  `failed_files` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '失败文件数',
  `total_chunks` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '切片总数',
  `indexed_chunks` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '已写入切片数',
  `message` VARCHAR(512) DEFAULT NULL COMMENT '任务消息',
  `error_message` TEXT NULL COMMENT '任务错误信息',
  `started_at` DATETIME DEFAULT NULL COMMENT '开始时间',
  `finished_at` DATETIME DEFAULT NULL COMMENT '结束时间',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_kop_index_job_user_status` (`user_id`, `status`),
  KEY `idx_kop_index_job_user_created` (`user_id`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='索引任务表，保存后台索引任务整体进度';

CREATE TABLE IF NOT EXISTS `kop_index_job_file` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '索引任务文件ID',
  `job_id` BIGINT UNSIGNED NOT NULL COMMENT '所属索引任务ID',
  `user_id` BIGINT UNSIGNED NOT NULL COMMENT '所属用户ID',
  `document_file_id` BIGINT UNSIGNED NOT NULL COMMENT '文档文件ID',
  `file_path` VARCHAR(1024) NOT NULL COMMENT '文件路径快照',
  `display_name` VARCHAR(255) DEFAULT NULL COMMENT '文件名快照',
  `status` VARCHAR(32) NOT NULL DEFAULT 'queued' COMMENT '文件任务状态：queued、running、success、failed',
  `stage` VARCHAR(32) NOT NULL DEFAULT 'queued' COMMENT '执行阶段：queued、loading、parsing、splitting、embedding、writing、success、failed',
  `progress` TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '进度百分比',
  `total_chunks` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '切片总数',
  `indexed_chunks` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '已写入切片数',
  `error_message` TEXT NULL COMMENT '错误信息',
  `started_at` DATETIME DEFAULT NULL COMMENT '开始时间',
  `finished_at` DATETIME DEFAULT NULL COMMENT '结束时间',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_kop_index_job_file` (`job_id`, `document_file_id`),
  KEY `idx_kop_index_job_file_user_status` (`user_id`, `status`),
  KEY `idx_kop_index_job_file_file` (`document_file_id`),
  KEY `idx_kop_index_job_file_job_status` (`job_id`, `status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='索引任务文件进度表，保存每个文件的索引阶段和进度';
