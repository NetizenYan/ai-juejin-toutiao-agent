-- Without this, a client defaulting to latin1 double-encodes every Chinese string in this file
-- (comments, seed rows): news_category names came out as "å¤´æ¡" instead of "头条".
SET NAMES utf8mb4;
USE news_app;

CREATE TABLE IF NOT EXISTS `ai_session` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'session id',
  `user_id` INT UNSIGNED NOT NULL COMMENT 'user id',
  `title` VARCHAR(255) NULL DEFAULT NULL COMMENT 'session title',
  `intent` VARCHAR(32) NULL DEFAULT NULL COMMENT 'news_qa/recommendation/general_chat',
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  INDEX `idx_ai_session_user` (`user_id` ASC),
  CONSTRAINT `fk_ai_session_user` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI 会话表';

CREATE TABLE IF NOT EXISTS `ai_message` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'message id',
  `session_id` INT UNSIGNED NOT NULL COMMENT 'session id',
  `role` VARCHAR(16) NOT NULL COMMENT 'system/user/assistant/tool',
  `content` TEXT NULL COMMENT 'message content',
  `evidence` JSON NULL COMMENT 'evidence pack',
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  INDEX `idx_ai_message_session` (`session_id` ASC),
  CONSTRAINT `fk_ai_message_session` FOREIGN KEY (`session_id`) REFERENCES `ai_session` (`id`)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI 消息表';

CREATE TABLE IF NOT EXISTS `ai_tool_call` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'tool call id',
  `message_id` INT UNSIGNED NOT NULL COMMENT 'message id',
  `tool_name` VARCHAR(64) NOT NULL COMMENT 'tool name',
  `arguments` JSON NULL COMMENT 'call arguments',
  `result` JSON NULL COMMENT 'call result',
  `latency_ms` INT NULL COMMENT 'latency ms',
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  INDEX `idx_ai_tool_call_message` (`message_id` ASC),
  CONSTRAINT `fk_ai_tool_call_message` FOREIGN KEY (`message_id`) REFERENCES `ai_message` (`id`)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI 工具调用轨迹表';

-- Long-term memory: per-user durable preferences and interests, each with the user's own words as
-- evidence. News facts, remembered figures, holdings and personal data are never stored (write gate in
-- harness/long_term_memory.py). Users can list and delete entries (/api/ai/memory).
CREATE TABLE IF NOT EXISTS `ai_user_memory` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'memory id',
  `user_id` INT UNSIGNED NOT NULL COMMENT 'user id',
  `kind` VARCHAR(16) NOT NULL COMMENT 'preference/interest',
  `mem_key` VARCHAR(64) NOT NULL COMMENT 'preference scope (max_chars...) or interest topic',
  `value` JSON NULL COMMENT 'preference value',
  `cue` VARCHAR(64) NOT NULL DEFAULT '' COMMENT 'situation the memory applies to',
  `evidence` JSON NULL COMMENT 'source session/turn and the user quote',
  `hits` INT NOT NULL DEFAULT 0 COMMENT 'times injected into a reply',
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `last_used_at` TIMESTAMP NULL DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE INDEX `uk_ai_user_memory` (`user_id`, `kind`, `mem_key`),
  CONSTRAINT `fk_ai_user_memory_user` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI 用户长期记忆表';
