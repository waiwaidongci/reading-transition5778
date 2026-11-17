-- 章节归一词典切版（MySQL8）。
-- 全新部署由 SQLAlchemy metadata 自动建表；已在运行的库执行本脚本补齐结构。
-- 表名与 domain.json 中 *_table 保持一致。

CREATE TABLE IF NOT EXISTS chapter_dictionary_versions (
  id INT PRIMARY KEY AUTO_INCREMENT,
  source_id INT NOT NULL,
  version INT NOT NULL,
  state VARCHAR(20) NOT NULL DEFAULT 'building',
  aliases JSON NOT NULL,
  alias_chains JSON NOT NULL,
  signature VARCHAR(64) NOT NULL,
  created_by VARCHAR(120) NOT NULL,
  created_at VARCHAR(40) NOT NULL,
  published_at VARCHAR(40) DEFAULT '',
  error TEXT,
  UNIQUE KEY uq_dict_version (source_id, version),
  CONSTRAINT fk_dict_source FOREIGN KEY (source_id) REFERENCES reading_collections (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS dictionary_backfill_jobs (
  id INT PRIMARY KEY AUTO_INCREMENT,
  source_id INT NOT NULL,
  dict_version_id INT NOT NULL,
  state VARCHAR(20) NOT NULL DEFAULT 'queued',
  total_sessions INT NOT NULL DEFAULT 0,
  processed_sessions INT NOT NULL DEFAULT 0,
  last_record_id INT NOT NULL DEFAULT 0,
  attempts INT NOT NULL DEFAULT 0,
  error TEXT,
  created_at VARCHAR(40) NOT NULL,
  updated_at VARCHAR(40) NOT NULL,
  CONSTRAINT fk_backfill_source FOREIGN KEY (source_id) REFERENCES reading_collections (id),
  CONSTRAINT fk_backfill_dict FOREIGN KEY (dict_version_id) REFERENCES chapter_dictionary_versions (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS normalized_reading_sessions (
  id INT PRIMARY KEY AUTO_INCREMENT,
  dict_version_id INT NOT NULL,
  record_id INT NOT NULL,
  canonical_path VARCHAR(2000) NOT NULL,
  UNIQUE KEY uq_normalized_record (dict_version_id, record_id),
  CONSTRAINT fk_norm_dict FOREIGN KEY (dict_version_id) REFERENCES chapter_dictionary_versions (id),
  CONSTRAINT fk_norm_record FOREIGN KEY (record_id) REFERENCES reading_sessions (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 已存在的文集/任务补列（MySQL8.0.29 之前不支持 ADD COLUMN IF NOT EXISTS，按实际库情况执行）：
ALTER TABLE reading_collections
  ADD COLUMN active_version_id INT NULL,
  ADD CONSTRAINT fk_source_active_dict FOREIGN KEY (active_version_id) REFERENCES chapter_dictionary_versions (id);

ALTER TABLE transition_runs
  ADD COLUMN dict_version_id INT NULL;

-- 历史数据回填：为每个文集建立 v1 空词典基线并置为当前版本（空词典恒等映射，旧研究口径不变）。
INSERT INTO chapter_dictionary_versions
  (source_id, version, state, aliases, alias_chains, signature, created_by, created_at, published_at, error)
SELECT c.id, 1, 'published', JSON_ARRAY(), JSON_OBJECT(),
       SHA2('', 256), 'migration', UTC_TIMESTAMP(), UTC_TIMESTAMP(), ''
FROM reading_collections c;

UPDATE reading_collections c
JOIN chapter_dictionary_versions d ON d.source_id = c.id AND d.version = 1
SET c.active_version_id = d.id;

-- 历史任务关联 v1，保证旧研究保留原判定、可继续导出。
UPDATE transition_runs r
JOIN chapter_dictionary_versions d ON d.source_id = r.source_id AND d.version = 1
SET r.dict_version_id = d.id
WHERE r.dict_version_id IS NULL;

CREATE INDEX idx_backfill_state ON dictionary_backfill_jobs (source_id, state);
CREATE INDEX idx_norm_version ON normalized_reading_sessions (dict_version_id);
