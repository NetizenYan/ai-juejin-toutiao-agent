-- Off-site news leads found by web search (2026-10-31). Kept apart from `news`: never shown in the
-- app feed, never cited as station evidence, only a summary + link per page (like a news aggregator).
SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS `external_news` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'external lead id (ext:<id>)',
  `url` VARCHAR(1024) NOT NULL COMMENT 'normalised source URL',
  `url_hash` CHAR(64) NOT NULL COMMENT 'sha256 of the normalised URL',
  `content_hash` CHAR(64) NOT NULL COMMENT 'sha256 of normalised title + summary (mirrors of one story)',
  `domain` VARCHAR(255) NOT NULL COMMENT 'host of the URL',
  `site` VARCHAR(128) NULL COMMENT 'site name reported by the search engine',
  `title` VARCHAR(255) NOT NULL,
  `summary` VARCHAR(1000) NOT NULL COMMENT 'search snippet, capped, no full text is stored',
  `published_at` DATETIME NULL COMMENT 'publication date when the result or snippet gives one',
  `first_query` VARCHAR(255) NOT NULL DEFAULT '' COMMENT 'question that first found it',
  `backend` VARCHAR(32) NOT NULL DEFAULT '' COMMENT 'search backend that returned it',
  `status` VARCHAR(16) NOT NULL DEFAULT 'unverified' COMMENT 'unverified / verified / rejected',
  `hits` INT NOT NULL DEFAULT 1 COMMENT 'times returned by a search',
  `review_note` VARCHAR(255) NULL,
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `last_seen_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `reviewed_at` TIMESTAMP NULL DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_external_news_url` (`url_hash`),
  INDEX `idx_external_news_content` (`content_hash`),
  INDEX `idx_external_news_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='站外资讯线索（联网搜索结果的摘要与链接）';
