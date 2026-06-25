-- KOP 聊天记忆与会话存储建表脚本
-- 说明：
-- 1. 适用于数据库 KOP。
-- 2. 当前阶段先覆盖：用户 -> 会话 -> 消息 -> 摘要 -> 长期记忆。
-- 3. Redis 不需要建表，Redis 只负责最近消息、摘要等热数据缓存。
-- 4. 本脚本不删除已有表，避免误删历史聊天记录。

CREATE DATABASE IF NOT EXISTS `KOP`
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE `KOP`;

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS `kop_user` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT '主键',
  `username` varchar(64) NOT NULL COMMENT '登录账号或本地默认用户名',
  `password_hash` varchar(255) DEFAULT NULL COMMENT '密码哈希，当前本地阶段可为空',
  `nickname` varchar(128) DEFAULT NULL COMMENT '昵称',
  `avatar_url` varchar(512) DEFAULT NULL COMMENT '头像地址',
  `status` tinyint NOT NULL DEFAULT '1' COMMENT '状态：1 启用，0 禁用',
  `last_login_at` datetime(3) DEFAULT NULL COMMENT '最近登录时间',
  `created_at` datetime(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` datetime(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_kop_user_username` (`username`),
  KEY `idx_kop_user_status_created` (`status`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='KOP 用户表';

CREATE TABLE IF NOT EXISTS `kop_chat_conversation` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT '主键',
  `user_id` bigint unsigned NOT NULL COMMENT '所属用户',
  `title` varchar(255) NOT NULL DEFAULT '' COMMENT '会话标题',
  `workspace_key` varchar(128) DEFAULT NULL COMMENT '会话所属工作区或知识库标识',
  `model_name` varchar(128) DEFAULT NULL COMMENT '最近使用的模型名',
  `summary` longtext DEFAULT NULL COMMENT '当前会话摘要',
  `summary_updated_at` datetime(3) DEFAULT NULL COMMENT '摘要更新时间',
  `status` tinyint NOT NULL DEFAULT '1' COMMENT '状态：1 正常，0 删除',
  `last_message_at` datetime(3) DEFAULT NULL COMMENT '最近消息时间',
  `created_at` datetime(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` datetime(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_kop_chat_conversation_user_last_message` (`user_id`, `last_message_at`),
  KEY `idx_kop_chat_conversation_user_created` (`user_id`, `created_at`),
  KEY `idx_kop_chat_conversation_workspace` (`workspace_key`),
  CONSTRAINT `fk_kop_chat_conversation_user`
    FOREIGN KEY (`user_id`) REFERENCES `kop_user` (`id`)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='KOP 聊天会话表';

CREATE TABLE IF NOT EXISTS `kop_chat_message` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT '主键',
  `conversation_id` bigint unsigned NOT NULL COMMENT '所属会话',
  `role` varchar(20) NOT NULL COMMENT '消息角色：user/assistant/system/tool',
  `content` longtext NOT NULL COMMENT '消息正文',
  `seq_no` int NOT NULL COMMENT '会话内顺序号，从 1 开始',
  `content_type` varchar(32) NOT NULL DEFAULT 'text' COMMENT '内容类型：text/json/markdown 等',
  `meta_json` json DEFAULT NULL COMMENT '扩展元数据，例如改写问题、usage 等',
  `citations_json` json DEFAULT NULL COMMENT '引用片段列表',
  `token_count` int DEFAULT NULL COMMENT '估算或实际 token 数',
  `model_name` varchar(128) DEFAULT NULL COMMENT '生成该消息时使用的模型',
  `created_at` datetime(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` datetime(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_kop_chat_message_conversation_seq` (`conversation_id`, `seq_no`),
  KEY `idx_kop_chat_message_conversation_created` (`conversation_id`, `created_at`),
  KEY `idx_kop_chat_message_role` (`role`),
  CONSTRAINT `fk_kop_chat_message_conversation`
    FOREIGN KEY (`conversation_id`) REFERENCES `kop_chat_conversation` (`id`)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='KOP 聊天消息表';

CREATE TABLE IF NOT EXISTS `kop_chat_conversation_summary` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT '主键',
  `conversation_id` bigint unsigned NOT NULL COMMENT '所属会话',
  `version` int NOT NULL DEFAULT '1' COMMENT '摘要版本号',
  `summary_text` longtext NOT NULL COMMENT '摘要内容',
  `covered_to_message_id` bigint unsigned DEFAULT NULL COMMENT '摘要覆盖到的最后一条消息 ID',
  `summary_tokens` int DEFAULT NULL COMMENT '摘要 token 数',
  `created_at` datetime(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` datetime(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_kop_chat_conversation_summary_version` (`conversation_id`, `version`),
  KEY `idx_kop_chat_conversation_summary_conversation` (`conversation_id`, `updated_at`),
  CONSTRAINT `fk_kop_chat_conversation_summary_conversation`
    FOREIGN KEY (`conversation_id`) REFERENCES `kop_chat_conversation` (`id`)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='KOP 会话摘要表';

CREATE TABLE IF NOT EXISTS `kop_chat_memory_fact` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT '主键',
  `user_id` bigint unsigned NOT NULL COMMENT '所属用户',
  `fact_type` varchar(64) DEFAULT NULL COMMENT '事实类型：preference/project/environment/other',
  `fact_text` text NOT NULL COMMENT '长期记忆内容',
  `confidence` decimal(4,3) DEFAULT NULL COMMENT '置信度，范围 0 到 1',
  `source_conversation_id` bigint unsigned DEFAULT NULL COMMENT '来源会话',
  `source_message_id` bigint unsigned DEFAULT NULL COMMENT '来源消息',
  `embedding_ref` varchar(128) DEFAULT NULL COMMENT '后续向量引用标识',
  `status` tinyint NOT NULL DEFAULT '1' COMMENT '状态：1 启用，0 禁用',
  `created_at` datetime(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` datetime(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_kop_chat_memory_fact_user_status` (`user_id`, `status`, `created_at`),
  KEY `idx_kop_chat_memory_fact_user_type` (`user_id`, `fact_type`),
  KEY `idx_kop_chat_memory_fact_source` (`source_conversation_id`, `source_message_id`),
  CONSTRAINT `fk_kop_chat_memory_fact_user`
    FOREIGN KEY (`user_id`) REFERENCES `kop_user` (`id`)
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_kop_chat_memory_fact_source_conversation`
    FOREIGN KEY (`source_conversation_id`) REFERENCES `kop_chat_conversation` (`id`)
    ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_kop_chat_memory_fact_source_message`
    FOREIGN KEY (`source_message_id`) REFERENCES `kop_chat_message` (`id`)
    ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='KOP 长期记忆事实表';

-- 当前代码已经直接使用：
-- kop_user
-- kop_chat_conversation
-- kop_chat_message
--
-- 以下表属于后续阶段预留：
-- kop_chat_conversation_summary
-- kop_chat_memory_fact
