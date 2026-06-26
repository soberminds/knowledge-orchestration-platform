-- KOP document library folder/file tables.
-- This script is a draft for the next document-library phase.
-- It depends on kop_user from KOP聊天记忆建表.sql.

CREATE DATABASE IF NOT EXISTS `KOP`
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE `KOP`;

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS `kop_doc_folder` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT 'Primary key',
  `user_id` bigint unsigned NOT NULL COMMENT 'Owner user id',
  `parent_id` bigint unsigned DEFAULT NULL COMMENT 'Parent folder id, null means root',
  `name` varchar(128) NOT NULL COMMENT 'Folder name',
  `path_cache` varchar(1024) NOT NULL DEFAULT '' COMMENT 'Display path cache, for example /project/contracts',
  `sort_order` int NOT NULL DEFAULT 0 COMMENT 'Sort order',
  `status` tinyint NOT NULL DEFAULT 1 COMMENT '1 active, 0 deleted',
  `created_at` datetime(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT 'Created time',
  `updated_at` datetime(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT 'Updated time',
  PRIMARY KEY (`id`),
  KEY `idx_kop_doc_folder_user_parent` (`user_id`, `parent_id`, `status`),
  KEY `idx_kop_doc_folder_parent` (`parent_id`),
  CONSTRAINT `fk_kop_doc_folder_user`
    FOREIGN KEY (`user_id`) REFERENCES `kop_user` (`id`)
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_kop_doc_folder_parent`
    FOREIGN KEY (`parent_id`) REFERENCES `kop_doc_folder` (`id`)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='KOP document folder';

CREATE TABLE IF NOT EXISTS `kop_doc_file` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT 'Primary key',
  `user_id` bigint unsigned NOT NULL COMMENT 'Owner user id',
  `folder_id` bigint unsigned DEFAULT NULL COMMENT 'Folder id, null means root',
  `display_name` varchar(255) NOT NULL COMMENT 'Display file name',
  `original_name` varchar(255) NOT NULL COMMENT 'Original uploaded file name',
  `stored_name` varchar(255) NOT NULL COMMENT 'Actual stored file name',
  `storage_path` varchar(1024) NOT NULL COMMENT 'Controlled relative storage path',
  `extension` varchar(32) NOT NULL DEFAULT '' COMMENT 'File extension',
  `mime_type` varchar(128) DEFAULT NULL COMMENT 'MIME type',
  `size_bytes` bigint unsigned NOT NULL DEFAULT 0 COMMENT 'File size',
  `sha256` char(64) DEFAULT NULL COMMENT 'Content SHA-256',
  `index_status` varchar(32) NOT NULL DEFAULT 'pending' COMMENT 'pending/indexing/success/failed',
  `index_message` text DEFAULT NULL COMMENT 'Index status message',
  `status` tinyint NOT NULL DEFAULT 1 COMMENT '1 active, 0 deleted',
  `created_at` datetime(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT 'Created time',
  `updated_at` datetime(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT 'Updated time',
  PRIMARY KEY (`id`),
  KEY `idx_kop_doc_file_user_folder` (`user_id`, `folder_id`, `status`, `updated_at`),
  KEY `idx_kop_doc_file_user_name` (`user_id`, `display_name`),
  KEY `idx_kop_doc_file_index_status` (`index_status`),
  CONSTRAINT `fk_kop_doc_file_user`
    FOREIGN KEY (`user_id`) REFERENCES `kop_user` (`id`)
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_kop_doc_file_folder`
    FOREIGN KEY (`folder_id`) REFERENCES `kop_doc_folder` (`id`)
    ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='KOP document file';
