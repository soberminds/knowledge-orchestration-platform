-- ----------------------------
-- Chat2DB export data , export time: 2026-06-27 11:00:34
-- ----------------------------
SET FOREIGN_KEY_CHECKS=0;
-- ----------------------------
-- Table structure for table kop_chat_conversation
-- ----------------------------
DROP TABLE IF EXISTS `kop_chat_conversation`;
CREATE TABLE `kop_chat_conversation` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT '主键',
  `user_id` bigint unsigned NOT NULL COMMENT '所属用户',
  `title` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '' COMMENT '会话标题',
  `workspace_key` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '会话所属工作区或知识库标识',
  `model_name` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '使用的模型',
  `summary` longtext COLLATE utf8mb4_unicode_ci COMMENT '会话摘要',
  `summary_updated_at` datetime(3) DEFAULT NULL COMMENT '摘要更新时间',
  `status` tinyint NOT NULL DEFAULT '1' COMMENT '状态：1正常，0删除',
  `last_message_at` datetime(3) DEFAULT NULL COMMENT '最近消息时间',
  `created_at` datetime(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` datetime(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_kop_chat_conversation_user_last_message` (`user_id`,`last_message_at`),
  KEY `idx_kop_chat_conversation_user_created` (`user_id`,`created_at`),
  KEY `idx_kop_chat_conversation_workspace` (`workspace_key`),
  CONSTRAINT `fk_kop_chat_conversation_user` FOREIGN KEY (`user_id`) REFERENCES `kop_user` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=24 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='KOP 聊天会话表';

-- ----------------------------
-- Table structure for table kop_chat_conversation_summary
-- ----------------------------
DROP TABLE IF EXISTS `kop_chat_conversation_summary`;
CREATE TABLE `kop_chat_conversation_summary` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT '主键',
  `conversation_id` bigint unsigned NOT NULL COMMENT '所属会话',
  `version` int NOT NULL DEFAULT '1' COMMENT '摘要版本号',
  `summary_text` longtext COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '摘要内容',
  `covered_to_message_id` bigint unsigned DEFAULT NULL COMMENT '摘要覆盖到的最后一条消息 ID',
  `summary_tokens` int DEFAULT NULL COMMENT '摘要 token 数',
  `created_at` datetime(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` datetime(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_kop_chat_conversation_summary_version` (`conversation_id`,`version`),
  KEY `idx_kop_chat_conversation_summary_conversation` (`conversation_id`,`updated_at`),
  CONSTRAINT `fk_kop_chat_conversation_summary_conversation` FOREIGN KEY (`conversation_id`) REFERENCES `kop_chat_conversation` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='KOP 会话摘要表';

-- ----------------------------
-- Table structure for table kop_chat_memory_fact
-- ----------------------------
DROP TABLE IF EXISTS `kop_chat_memory_fact`;
CREATE TABLE `kop_chat_memory_fact` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT '主键',
  `user_id` bigint unsigned NOT NULL COMMENT '所属用户',
  `fact_type` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '事实类型：preference/project/environment/other',
  `fact_text` text COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '长期记忆内容',
  `confidence` decimal(4,3) DEFAULT NULL COMMENT '置信度，范围 0~1',
  `source_conversation_id` bigint unsigned DEFAULT NULL COMMENT '来源会话',
  `source_message_id` bigint unsigned DEFAULT NULL COMMENT '来源消息',
  `embedding_ref` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '后续向量引用标识',
  `status` tinyint NOT NULL DEFAULT '1' COMMENT '状态：1启用，0禁用',
  `created_at` datetime(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` datetime(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_kop_chat_memory_fact_user_status` (`user_id`,`status`,`created_at`),
  KEY `idx_kop_chat_memory_fact_user_type` (`user_id`,`fact_type`),
  KEY `idx_kop_chat_memory_fact_source` (`source_conversation_id`,`source_message_id`),
  KEY `fk_kop_chat_memory_fact_source_message` (`source_message_id`),
  CONSTRAINT `fk_kop_chat_memory_fact_source_conversation` FOREIGN KEY (`source_conversation_id`) REFERENCES `kop_chat_conversation` (`id`) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_kop_chat_memory_fact_source_message` FOREIGN KEY (`source_message_id`) REFERENCES `kop_chat_message` (`id`) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_kop_chat_memory_fact_user` FOREIGN KEY (`user_id`) REFERENCES `kop_user` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='KOP 长期记忆事实表';

-- ----------------------------
-- Table structure for table kop_chat_message
-- ----------------------------
DROP TABLE IF EXISTS `kop_chat_message`;
CREATE TABLE `kop_chat_message` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT '主键',
  `conversation_id` bigint unsigned NOT NULL COMMENT '所属会话',
  `role` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '消息角色：user/assistant/system/tool',
  `content` longtext COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '消息正文',
  `seq_no` int NOT NULL COMMENT '会话内顺序号，从 1 开始',
  `content_type` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'text' COMMENT '内容类型：text/json/markdown 等',
  `meta_json` json DEFAULT NULL COMMENT '扩展元数据',
  `citations_json` json DEFAULT NULL COMMENT '引用片段列表',
  `token_count` int DEFAULT NULL COMMENT '估算或实际 token 数',
  `model_name` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '生成该消息时使用的模型',
  `created_at` datetime(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` datetime(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_kop_chat_message_conversation_seq` (`conversation_id`,`seq_no`),
  KEY `idx_kop_chat_message_conversation_created` (`conversation_id`,`created_at`),
  KEY `idx_kop_chat_message_role` (`role`),
  CONSTRAINT `fk_kop_chat_message_conversation` FOREIGN KEY (`conversation_id`) REFERENCES `kop_chat_conversation` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=113 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='KOP 聊天消息表';

-- ----------------------------
-- Table structure for table kop_doc_file
-- ----------------------------
DROP TABLE IF EXISTS `kop_doc_file`;
CREATE TABLE `kop_doc_file` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT 'Primary key',
  `user_id` bigint unsigned NOT NULL COMMENT 'Owner user id',
  `folder_id` bigint unsigned DEFAULT NULL COMMENT 'Folder id, null means root',
  `display_name` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'Display file name',
  `original_name` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'Original uploaded file name',
  `stored_name` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'Actual stored file name',
  `storage_path` varchar(1024) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'Controlled relative storage path',
  `extension` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '' COMMENT 'File extension',
  `mime_type` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'MIME type',
  `size_bytes` bigint unsigned NOT NULL DEFAULT '0' COMMENT 'File size',
  `sha256` char(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'Content SHA-256',
  `index_status` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'pending' COMMENT 'pending/indexing/success/failed',
  `index_message` text COLLATE utf8mb4_unicode_ci COMMENT 'Index status message',
  `status` tinyint NOT NULL DEFAULT '1' COMMENT '1 active, 0 deleted',
  `created_at` datetime(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT 'Created time',
  `updated_at` datetime(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT 'Updated time',
  PRIMARY KEY (`id`),
  KEY `idx_kop_doc_file_user_folder` (`user_id`,`folder_id`,`status`,`updated_at`),
  KEY `idx_kop_doc_file_user_name` (`user_id`,`display_name`),
  KEY `idx_kop_doc_file_index_status` (`index_status`),
  KEY `fk_kop_doc_file_folder` (`folder_id`),
  CONSTRAINT `fk_kop_doc_file_folder` FOREIGN KEY (`folder_id`) REFERENCES `kop_doc_folder` (`id`) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_kop_doc_file_user` FOREIGN KEY (`user_id`) REFERENCES `kop_user` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=5 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='KOP document file';

-- ----------------------------
-- Table structure for table kop_doc_folder
-- ----------------------------
DROP TABLE IF EXISTS `kop_doc_folder`;
CREATE TABLE `kop_doc_folder` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT 'Primary key',
  `user_id` bigint unsigned NOT NULL COMMENT 'Owner user id',
  `parent_id` bigint unsigned DEFAULT NULL COMMENT 'Parent folder id, null means root',
  `name` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'Folder name',
  `path_cache` varchar(1024) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '' COMMENT 'Display path cache, for example /project/contracts',
  `sort_order` int NOT NULL DEFAULT '0' COMMENT 'Sort order',
  `status` tinyint NOT NULL DEFAULT '1' COMMENT '1 active, 0 deleted',
  `created_at` datetime(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT 'Created time',
  `updated_at` datetime(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT 'Updated time',
  PRIMARY KEY (`id`),
  KEY `idx_kop_doc_folder_user_parent` (`user_id`,`parent_id`,`status`),
  KEY `idx_kop_doc_folder_parent` (`parent_id`),
  CONSTRAINT `fk_kop_doc_folder_parent` FOREIGN KEY (`parent_id`) REFERENCES `kop_doc_folder` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_kop_doc_folder_user` FOREIGN KEY (`user_id`) REFERENCES `kop_user` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=12 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='KOP document folder';

-- ----------------------------
-- Table structure for table kop_user
-- ----------------------------
DROP TABLE IF EXISTS `kop_user`;
CREATE TABLE `kop_user` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT '主键',
  `username` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '登录账号',
  `password_hash` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '密码哈希',
  `nickname` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '昵称',
  `avatar_url` varchar(512) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '头像地址',
  `status` tinyint NOT NULL DEFAULT '1' COMMENT '状态：1启用，0禁用',
  `last_login_at` datetime(3) DEFAULT NULL COMMENT '最近登录时间',
  `created_at` datetime(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` datetime(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_kop_user_username` (`username`),
  KEY `idx_kop_user_status_created` (`status`,`created_at`)
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='KOP 用户表';

SET FOREIGN_KEY_CHECKS=1;
