-- KOP 数据库初始化脚本
-- 版本：v1
-- 作用：从零重建数据库，适配当前这套设计

CREATE DATABASE IF NOT EXISTS `KOP`
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_general_ci;

USE `KOP`;

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

DROP TABLE IF EXISTS
  `kop_chat_memory_fact`,
  `kop_chat_conversation_summary`,
  `kop_chat_message`,
  `kop_chat_conversation`,
  `kop_document_chunk`,
  `kop_document_file`,
  `kop_document_folder`,
  `kop_kb`,
  `kop_workspace`,
  `kop_user`;

CREATE TABLE `kop_user` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '用户ID',
  `username` VARCHAR(64) NOT NULL COMMENT '用户名',
  `password_hash` VARCHAR(255) DEFAULT NULL COMMENT '密码哈希值',
  `nickname` VARCHAR(128) DEFAULT NULL COMMENT '用户昵称',
  `avatar_url` VARCHAR(255) DEFAULT NULL COMMENT '头像地址',
  `user_type` VARCHAR(32) NOT NULL DEFAULT 'local' COMMENT '用户类型：本地用户或注册用户',
  `is_default` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否默认本地用户',
  `status` TINYINT NOT NULL DEFAULT 1 COMMENT '用户状态，1=启用，0=禁用',
  `last_login_at` DATETIME DEFAULT NULL COMMENT '最后登录时间',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_kop_user_username` (`username`),
  KEY `idx_kop_user_status` (`status`),
  KEY `idx_kop_user_default` (`is_default`),
  KEY `idx_kop_user_type` (`user_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='用户表，保存本地用户和注册用户信息';

CREATE TABLE `kop_workspace` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '工作区ID',
  `user_id` BIGINT UNSIGNED NOT NULL COMMENT '所属用户ID',
  `workspace_key` VARCHAR(128) NOT NULL COMMENT '工作区唯一键',
  `workspace_name` VARCHAR(255) NOT NULL COMMENT '工作区名称',
  `description` VARCHAR(512) DEFAULT NULL COMMENT '工作区描述',
  `is_default` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否默认工作区',
  `status` TINYINT NOT NULL DEFAULT 1 COMMENT '工作区状态，1=启用，0=禁用',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_kop_workspace_key` (`workspace_key`),
  UNIQUE KEY `uk_kop_workspace_user_name` (`user_id`, `workspace_name`),
  KEY `idx_kop_workspace_user_default` (`user_id`, `is_default`),
  KEY `idx_kop_workspace_user_status` (`user_id`, `status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='工作区表，保存用户创建的工作区信息';

CREATE TABLE `kop_kb` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '知识库ID',
  `user_id` BIGINT UNSIGNED NOT NULL COMMENT '所属用户ID',
  `workspace_id` BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '所属工作区ID',
  `folder_id` BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '所属文件夹ID',
  `kb_name` VARCHAR(255) NOT NULL COMMENT '知识库名称',
  `description` VARCHAR(512) DEFAULT NULL COMMENT '知识库描述',
  `status` TINYINT NOT NULL DEFAULT 1 COMMENT '知识库状态，1=启用，0=禁用',
  `is_deleted` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否删除',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_kop_kb_user_workspace_name` (`user_id`, `workspace_id`, `kb_name`),
  KEY `idx_kop_kb_user_workspace` (`user_id`, `workspace_id`),
  KEY `idx_kop_kb_user_folder` (`user_id`, `folder_id`),
  KEY `idx_kop_kb_user_deleted` (`user_id`, `is_deleted`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='知识库表，保存工作区和文件夹下的知识库信息';

CREATE TABLE `kop_document_folder` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '文件夹ID',
  `user_id` BIGINT UNSIGNED NOT NULL COMMENT '所属用户ID',
  `parent_id` BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '父文件夹ID，0 表示根目录',
  `folder_name` VARCHAR(255) NOT NULL COMMENT '文件夹名称',
  `sort_order` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '排序值',
  `is_deleted` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否删除',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_kop_document_folder_user_parent_name` (`user_id`, `parent_id`, `folder_name`),
  KEY `idx_kop_document_folder_user_parent` (`user_id`, `parent_id`),
  KEY `idx_kop_document_folder_user_deleted` (`user_id`, `is_deleted`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='文档文件夹表，保存用户自己的文件夹树';

CREATE TABLE `kop_document_file` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '文件ID',
  `user_id` BIGINT UNSIGNED NOT NULL COMMENT '所属用户ID',
  `folder_id` BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '所属文件夹ID，0 表示根目录',
  `kb_id` BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '所属知识库ID',
  `original_name` VARCHAR(255) NOT NULL COMMENT '原始文件名',
  `stored_name` VARCHAR(255) DEFAULT NULL COMMENT '存储文件名',
  `file_path` VARCHAR(1024) NOT NULL COMMENT '文件存储路径',
  `file_ext` VARCHAR(32) DEFAULT NULL COMMENT '文件扩展名',
  `mime_type` VARCHAR(128) DEFAULT NULL COMMENT '文件 MIME 类型',
  `file_size` BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '文件大小，字节',
  `file_hash` VARCHAR(128) DEFAULT NULL COMMENT '文件哈希值',
  `source_type` VARCHAR(32) NOT NULL DEFAULT 'upload' COMMENT '来源类型，例如 upload、sample',
  `parse_status` VARCHAR(32) NOT NULL DEFAULT 'pending' COMMENT '解析状态',
  `index_status` VARCHAR(32) NOT NULL DEFAULT 'pending' COMMENT '索引状态',
  `parse_error` TEXT NULL COMMENT '解析错误信息',
  `last_indexed_at` DATETIME DEFAULT NULL COMMENT '最后索引时间',
  `is_deleted` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否删除',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_kop_document_file_user_folder` (`user_id`, `folder_id`),
  KEY `idx_kop_document_file_user_kb` (`user_id`, `kb_id`),
  KEY `idx_kop_document_file_user_status` (`user_id`, `parse_status`),
  KEY `idx_kop_document_file_user_hash` (`user_id`, `file_hash`),
  KEY `idx_kop_document_file_user_deleted` (`user_id`, `is_deleted`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='文档文件表，保存用户上传或内置的原始文件信息';

CREATE TABLE `kop_document_chunk` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '切片ID',
  `user_id` BIGINT UNSIGNED NOT NULL COMMENT '所属用户ID',
  `document_file_id` BIGINT UNSIGNED NOT NULL COMMENT '所属文件ID',
  `chunk_index` INT UNSIGNED NOT NULL COMMENT '切片序号',
  `page_no` INT UNSIGNED DEFAULT NULL COMMENT '页码',
  `sheet_name` VARCHAR(128) DEFAULT NULL COMMENT '工作表名称',
  `slide_no` INT UNSIGNED DEFAULT NULL COMMENT '幻灯片页码',
  `char_count` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '字符数',
  `content_hash` VARCHAR(128) DEFAULT NULL COMMENT '内容哈希值',
  `content` LONGTEXT NOT NULL COMMENT '切片内容',
  `metadata_json` LONGTEXT NULL COMMENT '切片元数据 JSON',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_kop_document_chunk_file_index` (`document_file_id`, `chunk_index`),
  KEY `idx_kop_document_chunk_user_file` (`user_id`, `document_file_id`),
  KEY `idx_kop_document_chunk_user_hash` (`user_id`, `content_hash`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='文档切片表，保存解析后按页或按块切分的内容';

CREATE TABLE `kop_chat_conversation` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '会话ID',
  `user_id` BIGINT UNSIGNED NOT NULL COMMENT '所属用户ID',
  `title` VARCHAR(255) NOT NULL DEFAULT 'New chat' COMMENT '会话标题',
  `workspace_key` VARCHAR(128) DEFAULT NULL COMMENT '工作区键',
  `model_name` VARCHAR(128) DEFAULT NULL COMMENT '模型名称',
  `scope_type` VARCHAR(32) NOT NULL DEFAULT 'all' COMMENT '会话范围类型：all、folder、workspace、kb',
  `scope_id` BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '会话范围ID，0 表示全部范围',
  `summary` MEDIUMTEXT NULL COMMENT '会话摘要',
  `summary_updated_at` DATETIME DEFAULT NULL COMMENT '摘要更新时间',
  `status` TINYINT NOT NULL DEFAULT 1 COMMENT '会话状态，1=启用，0=禁用',
  `last_message_at` DATETIME DEFAULT NULL COMMENT '最后消息时间',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_kop_chat_conversation_user_last_message` (`user_id`, `last_message_at`),
  KEY `idx_kop_chat_conversation_user_scope` (`user_id`, `scope_type`, `scope_id`),
  KEY `idx_kop_chat_conversation_scope` (`scope_type`, `scope_id`),
  KEY `idx_kop_chat_conversation_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='会话表，保存用户聊天会话及其检索范围信息';

CREATE TABLE `kop_chat_message` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '消息ID',
  `conversation_id` BIGINT UNSIGNED NOT NULL COMMENT '所属会话ID',
  `sender_user_id` BIGINT UNSIGNED DEFAULT NULL COMMENT '发送用户ID',
  `role` VARCHAR(20) NOT NULL COMMENT '消息角色，例如 user、assistant、system、tool',
  `content` LONGTEXT NOT NULL COMMENT '消息内容',
  `seq_no` BIGINT UNSIGNED NOT NULL COMMENT '消息序号',
  `meta_json` LONGTEXT NULL COMMENT '附加元数据 JSON',
  `citations_json` LONGTEXT NULL COMMENT '引用信息 JSON',
  `token_count` INT UNSIGNED DEFAULT NULL COMMENT '消息 token 数量',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_kop_chat_message_conversation_seq` (`conversation_id`, `seq_no`),
  KEY `idx_kop_chat_message_conversation_created` (`conversation_id`, `created_at`),
  KEY `idx_kop_chat_message_sender_created` (`sender_user_id`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='会话消息表，保存每一轮用户和助手消息';

CREATE TABLE `kop_chat_conversation_summary` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '摘要ID',
  `conversation_id` BIGINT UNSIGNED NOT NULL COMMENT '所属会话ID',
  `summary_text` MEDIUMTEXT NOT NULL COMMENT '摘要内容',
  `covered_to_message_id` BIGINT UNSIGNED DEFAULT NULL COMMENT '摘要覆盖到的消息ID',
  `version` INT UNSIGNED NOT NULL DEFAULT 1 COMMENT '摘要版本号',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_kop_chat_conversation_summary_conversation` (`conversation_id`),
  KEY `idx_kop_chat_conversation_summary_covered` (`covered_to_message_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='会话摘要表，保存长会话压缩后的摘要内容';

CREATE TABLE `kop_chat_memory_fact` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '记忆事实ID',
  `user_id` BIGINT UNSIGNED NOT NULL COMMENT '所属用户ID',
  `fact_text` TEXT NOT NULL COMMENT '记忆内容',
  `confidence` DECIMAL(5,2) NOT NULL DEFAULT 0.50 COMMENT '置信度，0 到 1 之间',
  `source_message_id` BIGINT UNSIGNED DEFAULT NULL COMMENT '来源消息ID',
  `embedding_ref` VARCHAR(255) DEFAULT NULL COMMENT '向量引用',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_kop_chat_memory_fact_user_created` (`user_id`, `created_at`),
  KEY `idx_kop_chat_memory_fact_user_confidence` (`user_id`, `confidence`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='聊天长期记忆表，保存稳定的用户偏好和事实';

INSERT INTO `kop_user`
  (`id`, `username`, `password_hash`, `nickname`, `avatar_url`, `user_type`, `is_default`, `status`, `last_login_at`)
SELECT
  1, 'local-user', NULL, 'Local User', NULL, 'local', 1, 1, NULL
FROM DUAL
WHERE NOT EXISTS (
  SELECT 1 FROM `kop_user` WHERE `username` = 'local-user'
);

SET FOREIGN_KEY_CHECKS = 1;

