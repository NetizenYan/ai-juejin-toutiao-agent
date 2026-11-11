-- News categories the frontend expects. id 10 is reserved: the frontend appends its own "更多" tab
-- with id=10 on the client, so the table must not use it. Re-running is safe (INSERT IGNORE).
--
--   mysql --default-character-set=utf8mb4 -u root -p < sql/seed_categories.sql
SET NAMES utf8mb4;
USE news_app;

INSERT IGNORE INTO `news_category` (`id`, `name`, `sort_order`) VALUES
  (1, '头条', 1),
  (2, '社会', 2),
  (3, '国内', 3),
  (4, '国际', 4),
  (5, '娱乐', 5),
  (6, '体育', 6),
  (7, '科技', 7),
  (8, '财经', 8),
  (9, '军事', 9);
