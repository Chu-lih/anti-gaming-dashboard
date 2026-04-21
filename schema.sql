-- Anti-Gaming Fraud Dashboard — Schema
-- 設計原則:
--   1. ComplianceRules 為「邏輯字典」,參數存 JSON,規則引擎動態讀取,不 hardcode
--   2. FlaggedSessions 是「待審佇列」,resolution_status 可變更,但違規事實不可改
--   3. ComplianceAuditLog 為「不可變稽核日誌」:DB 層 trigger + 應用層雙鎖,供 FSC 稽核
--   4. LearningSessions 記錄完整 telemetry,供規則引擎批次或即時掃描

PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS RuleChangeLog;
DROP TABLE IF EXISTS ComplianceAuditLog;
DROP TABLE IF EXISTS FlaggedSessions;
DROP TABLE IF EXISTS LearningSessions;
DROP TABLE IF EXISTS Modules;
DROP TABLE IF EXISTS ComplianceRules;

-- ============================================================
-- ComplianceRules:規則邏輯字典(可由主管動態調整)
-- ============================================================
CREATE TABLE ComplianceRules (
    rule_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_name      TEXT    NOT NULL,
    rule_code      TEXT    NOT NULL UNIQUE,           -- 程式分派依據 (SPEEDING / BLIND_GUESSING / DISTRACTION)
    description    TEXT,
    parameter_json TEXT    NOT NULL,                  -- 規則參數 (JSON 字串)
    severity_level TEXT    NOT NULL CHECK (severity_level IN ('Low', 'Medium', 'High')),
    is_active      INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- Modules:學習模組主檔 (SPEEDING 規則需要對照平均時長)
-- ============================================================
CREATE TABLE Modules (
    module_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    module_name            TEXT    NOT NULL UNIQUE,
    avg_completion_seconds INTEGER NOT NULL            -- 公司平均完成秒數
);

-- ============================================================
-- LearningSessions:原始學習 session + telemetry 事件軌跡
--   規則引擎會對 is_active=1 的規則掃描此表,產生 FlaggedSessions
-- ============================================================
CREATE TABLE LearningSessions (
    session_id         TEXT    PRIMARY KEY,
    agent_id           TEXT    NOT NULL,
    agent_name         TEXT    NOT NULL,
    module_id          INTEGER,
    module_name        TEXT    NOT NULL,
    completion_seconds INTEGER,                        -- 本次完成時間
    quiz_score         REAL,                           -- 0.0 ~ 1.0
    quiz_seconds       INTEGER,                        -- 作答秒數
    tab_switch_count   INTEGER DEFAULT 0,
    telemetry_json     TEXT,                           -- 完整事件軌跡 (JSON array)
    started_at         TIMESTAMP,
    FOREIGN KEY (module_id) REFERENCES Modules(module_id)
);

CREATE INDEX idx_sessions_agent  ON LearningSessions(agent_id);
CREATE INDEX idx_sessions_module ON LearningSessions(module_id);

-- ============================================================
-- FlaggedSessions:主管收件匣佇列
-- ============================================================
CREATE TABLE FlaggedSessions (
    flag_id                INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id             TEXT    NOT NULL,
    agent_id               TEXT    NOT NULL,
    agent_name             TEXT    NOT NULL,
    module_name            TEXT    NOT NULL,
    rule_violated_id       INTEGER NOT NULL,
    flag_timestamp         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolution_status      TEXT    NOT NULL DEFAULT 'pending'
                                    CHECK (resolution_status IN ('pending', 'approved', 'voided', 'escalated')),
    session_telemetry_json TEXT,
    FOREIGN KEY (rule_violated_id) REFERENCES ComplianceRules(rule_id),
    UNIQUE (session_id, rule_violated_id)             -- 同一 session 不重複 flag 同一規則
);

CREATE INDEX idx_flagged_status ON FlaggedSessions(resolution_status);
CREATE INDEX idx_flagged_rule   ON FlaggedSessions(rule_violated_id);

-- ============================================================
-- ComplianceAuditLog:不可變稽核紀錄 (供 FSC 稽核)
--   僅允許 INSERT,UPDATE / DELETE 皆被 trigger 阻擋
-- ============================================================
CREATE TABLE ComplianceAuditLog (
    audit_id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    flag_id                     INTEGER NOT NULL,
    manager_id                  TEXT    NOT NULL,
    manager_name                TEXT    NOT NULL,
    action_taken                TEXT    NOT NULL CHECK (action_taken IN ('approve', 'void', 'escalate')),
    manager_justification_notes TEXT    NOT NULL,
    timestamp                   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (flag_id) REFERENCES FlaggedSessions(flag_id)
);

CREATE INDEX idx_audit_flag    ON ComplianceAuditLog(flag_id);
CREATE INDEX idx_audit_manager ON ComplianceAuditLog(manager_id);

-- ============================================================
-- 不可變觸發器:DB 層強制 audit log 只能 INSERT
-- ============================================================
CREATE TRIGGER trg_audit_no_update
BEFORE UPDATE ON ComplianceAuditLog
BEGIN
    SELECT RAISE(ABORT, 'ComplianceAuditLog is immutable — UPDATE is forbidden for FSC compliance');
END;

CREATE TRIGGER trg_audit_no_delete
BEFORE DELETE ON ComplianceAuditLog
BEGIN
    SELECT RAISE(ABORT, 'ComplianceAuditLog is immutable — DELETE is forbidden for FSC compliance');
END;

-- ============================================================
-- RuleChangeLog:規則變更稽核記錄(與 ComplianceAuditLog 分責)
--   主管調整 parameter_json 或 toggle is_active 時永久留存,
--   監管稽核時可重建「當時規則閾值為何」的歷史快照。
-- ============================================================
CREATE TABLE RuleChangeLog (
    change_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id      INTEGER NOT NULL,
    rule_code    TEXT    NOT NULL,
    change_type  TEXT    NOT NULL CHECK (change_type IN ('parameter_update', 'toggle_active')),
    old_value    TEXT,
    new_value    TEXT    NOT NULL,
    manager_id   TEXT    NOT NULL,
    manager_name TEXT    NOT NULL,
    timestamp    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (rule_id) REFERENCES ComplianceRules(rule_id)
);

CREATE INDEX idx_rule_change_rule ON RuleChangeLog(rule_id);

CREATE TRIGGER trg_rule_change_no_update
BEFORE UPDATE ON RuleChangeLog
BEGIN
    SELECT RAISE(ABORT, 'RuleChangeLog is immutable — UPDATE is forbidden for FSC compliance');
END;

CREATE TRIGGER trg_rule_change_no_delete
BEFORE DELETE ON RuleChangeLog
BEGIN
    SELECT RAISE(ABORT, 'RuleChangeLog is immutable — DELETE is forbidden for FSC compliance');
END;
