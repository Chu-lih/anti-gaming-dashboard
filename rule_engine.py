"""
rule_engine.py
================
動態合規規則引擎(Strategy Pattern 實作)

設計原則
--------
1.  **Strategy Pattern**:每條規則對應一個 `RuleChecker` 子類別,
    透過 `CHECKER_REGISTRY` 以 `rule_code` 為 key 分派;新增規則
    只需新增一個子類別並註冊,不動主迴圈(Open/Closed)。

2.  **零 Hardcode 閾值**:所有數值參數「只能」從 `ComplianceRules.parameter_json`
    讀取;若 JSON 缺 key 直接拋 `ValueError`,拒絕靜默預設。
    預設值僅存在於 DB(由 `seed_data.py` 的 `DEFAULT_RULES` 種入),
    主管在 UI 調整後「立即生效、無需重啟」。

3.  **Dry-run 模式**:`run_engine(dry_run=True)` 只回傳命中結果,不寫入
    `FlaggedSessions`。方便主管在變更規則參數前模擬。

4.  **冪等性**:DB 端已加 `UNIQUE(session_id, rule_violated_id)`,
    Python 端使用 `INSERT OR IGNORE`,確保重複掃描不會產生重複 flag。

執行方式
--------
    python3 rule_engine.py              # 正式掃描 + 寫入 FlaggedSessions
    python3 rule_engine.py --dry-run    # 只列出觸發結果,不寫入 DB
    python3 rule_engine.py --test       # 跑 demo 經典案例自動斷言
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Type

DB_PATH = Path(__file__).resolve().parent / "database.db"


# =============================================================
# 資料模型
# =============================================================
@dataclass(frozen=True)
class SessionRecord:
    """一筆學習 session 的精簡 view(供 checker 判斷用)"""
    session_id: str
    agent_id: str
    agent_name: str
    module_id: int | None
    module_name: str
    completion_seconds: int | None
    quiz_score: float | None
    quiz_seconds: int | None
    tab_switch_count: int
    telemetry_json: str | None
    module_avg_completion_seconds: int | None


@dataclass(frozen=True)
class RuleRecord:
    rule_id: int
    rule_code: str
    rule_name: str
    severity_level: str
    parameter_json: str

    @property
    def params(self) -> dict:
        return json.loads(self.parameter_json)


# =============================================================
# Strategy 基類
# =============================================================
class RuleChecker(ABC):
    """
    所有規則檢查器的抽象基類。

    *  子類別只要 override `rule_code`, `_validate_params`, `check`
    *  參數必須透過 `self.params` 存取,不允許 class-level 或 method-level
       的魔數(magic numbers)
    """
    rule_code: str = ""  # 子類必須 override

    def __init__(self, params: dict):
        self.params = params
        self._validate_params()

    @abstractmethod
    def _validate_params(self) -> None:
        """若 params 缺必要 key,拋 ValueError(不允許靜默預設)"""

    @abstractmethod
    def check(self, sess: SessionRecord) -> bool:
        """回傳 True 表示 session 違反此規則"""

    def _require(self, key: str) -> None:
        if key not in self.params:
            raise ValueError(
                f"[{self.rule_code}] parameter_json 缺少必要欄位 '{key}';"
                f"請到 ComplianceRules 表補齊設定"
            )


# =============================================================
# 具體 Checker:SPEEDING
# =============================================================
class SpeedingChecker(RuleChecker):
    """
    規則:完成時間 < 模組平均時間 × min_completion_ratio
    所需參數:
        min_completion_ratio (float)  — 由 DB 決定,例如 0.2 表示「秒過於 20%」
    """
    rule_code = "SPEEDING"

    def _validate_params(self) -> None:
        self._require("min_completion_ratio")

    def check(self, sess: SessionRecord) -> bool:
        if sess.module_avg_completion_seconds is None or sess.completion_seconds is None:
            return False
        ratio = sess.completion_seconds / sess.module_avg_completion_seconds
        return ratio < self.params["min_completion_ratio"]


# =============================================================
# 具體 Checker:BLIND_GUESSING
# =============================================================
class BlindGuessingChecker(RuleChecker):
    """
    規則:quiz 答題時間 < max_quiz_seconds 且 quiz_score <= max_score
    所需參數:
        max_quiz_seconds (int)
        max_score (float)  — 預設 0.0(DB 設定),表示 0 分才算「盲猜」
    """
    rule_code = "BLIND_GUESSING"

    def _validate_params(self) -> None:
        self._require("max_quiz_seconds")
        self._require("max_score")

    def check(self, sess: SessionRecord) -> bool:
        if sess.quiz_seconds is None or sess.quiz_score is None:
            return False
        return (
            sess.quiz_seconds < self.params["max_quiz_seconds"]
            and sess.quiz_score <= self.params["max_score"]
        )


# =============================================================
# 具體 Checker:DISTRACTION
# =============================================================
class DistractionChecker(RuleChecker):
    """
    規則:在 window_seconds 內,telemetry 中的 tab_switch 事件數 > max_tab_switches
    所需參數:
        max_tab_switches (int)
        window_seconds (int)  — 預設 420 秒,對應一個 7 分鐘 sprint
    """
    rule_code = "DISTRACTION"

    def _validate_params(self) -> None:
        self._require("max_tab_switches")
        self._require("window_seconds")

    def check(self, sess: SessionRecord) -> bool:
        if not sess.telemetry_json:
            return False
        try:
            events = json.loads(sess.telemetry_json)
        except json.JSONDecodeError:
            return False
        window = self.params["window_seconds"]
        switches_in_window = sum(
            1 for e in events
            if e.get("event") == "tab_switch" and e.get("time", 0) <= window
        )
        return switches_in_window > self.params["max_tab_switches"]


# =============================================================
# Registry:新增規則就在這裡註冊,其他程式碼不動
# =============================================================
CHECKER_REGISTRY: dict[str, Type[RuleChecker]] = {
    SpeedingChecker.rule_code: SpeedingChecker,
    BlindGuessingChecker.rule_code: BlindGuessingChecker,
    DistractionChecker.rule_code: DistractionChecker,
}


def build_checker(rule: RuleRecord) -> RuleChecker | None:
    cls = CHECKER_REGISTRY.get(rule.rule_code)
    if cls is None:
        print(f"[engine] 警告:未註冊的 rule_code '{rule.rule_code}',跳過")
        return None
    return cls(rule.params)


# =============================================================
# DB 讀取
# =============================================================
def load_active_rules(conn: sqlite3.Connection) -> list[RuleRecord]:
    rows = conn.execute(
        "SELECT rule_id, rule_code, rule_name, severity_level, parameter_json "
        "FROM ComplianceRules WHERE is_active = 1 ORDER BY rule_id"
    ).fetchall()
    return [RuleRecord(*r) for r in rows]


def load_sessions(conn: sqlite3.Connection) -> list[SessionRecord]:
    rows = conn.execute(
        """SELECT s.session_id, s.agent_id, s.agent_name, s.module_id, s.module_name,
                  s.completion_seconds, s.quiz_score, s.quiz_seconds, s.tab_switch_count,
                  s.telemetry_json, m.avg_completion_seconds
           FROM LearningSessions s
           LEFT JOIN Modules m ON s.module_id = m.module_id
           ORDER BY s.session_id"""
    ).fetchall()
    return [SessionRecord(*r) for r in rows]


# =============================================================
# 主引擎
# =============================================================
def run_engine(conn: sqlite3.Connection, *, dry_run: bool = False) -> list[dict]:
    """
    掃描所有 session × 所有 active 規則。
    dry_run=True 時僅回傳結果不寫入 DB。
    """
    rules = load_active_rules(conn)
    sessions = load_sessions(conn)

    # 為了效率:一次把 checker 建好,避免每個 session 重建
    checkers: list[tuple[RuleRecord, RuleChecker]] = []
    for rule in rules:
        checker = build_checker(rule)
        if checker is not None:
            checkers.append((rule, checker))

    hits: list[dict] = []
    for sess in sessions:
        for rule, checker in checkers:
            if checker.check(sess):
                hits.append({
                    "session_id": sess.session_id,
                    "agent_id": sess.agent_id,
                    "agent_name": sess.agent_name,
                    "module_name": sess.module_name,
                    "rule_violated_id": rule.rule_id,
                    "rule_code": rule.rule_code,
                    "severity": rule.severity_level,
                    "telemetry_json": sess.telemetry_json,
                })

    if dry_run:
        print(f"[engine] [DRY-RUN] 掃描完成:{len(hits)} 命中,未寫入 DB")
        return hits

    inserted = 0
    skipped = 0
    for h in hits:
        cur = conn.execute(
            """INSERT OR IGNORE INTO FlaggedSessions
               (session_id, agent_id, agent_name, module_name,
                rule_violated_id, session_telemetry_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (h["session_id"], h["agent_id"], h["agent_name"], h["module_name"],
             h["rule_violated_id"], h["telemetry_json"]),
        )
        if cur.rowcount > 0:
            inserted += 1
        else:
            skipped += 1
    conn.commit()
    print(
        f"[engine] 掃描完成:{len(hits)} 命中 → 新增 {inserted} 筆 Flagged,"
        f"略過 {skipped} 筆(已存在 / 冪等去重)"
    )
    return hits


# =============================================================
# CLI 輔助:列出 Top N 最可疑
# =============================================================
def print_top_suspicious(hits: list[dict], top_n: int = 10) -> None:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for h in hits:
        grouped[h["session_id"]].append(h)
    ranked = sorted(
        grouped.items(),
        key=lambda kv: (-len(kv[1]), kv[0]),
    )
    print(f"\n--- Top {top_n} 可疑 Session(依觸發規則數) ---")
    print(f"  {'session_id':<12}  {'agent':<8}  {'module':<22}  rules")
    for sid, items in ranked[:top_n]:
        codes = ",".join(i["rule_code"] for i in items)
        agent = items[0]["agent_name"]
        mod = items[0]["module_name"]
        print(f"  {sid:<12}  {agent:<8}  {mod[:22]:<22}  [{codes}]")


# =============================================================
# 內建測試:demo 案例斷言
# =============================================================
def run_test(conn: sqlite3.Connection) -> int:
    print("=== Demo 案例自動驗證(dry-run)===")
    hits = run_engine(conn, dry_run=True)

    hits_by_sid: dict[str, set[str]] = defaultdict(set)
    for h in hits:
        hits_by_sid[h["session_id"]].add(h["rule_code"])

    cases = [
        ("S-DEMO-01", {"SPEEDING", "BLIND_GUESSING", "DISTRACTION"}, "王大明 AML 三規則齊發"),
        ("S-DEMO-02", {"SPEEDING"}, "陳美麗 投資型保單 純 SPEEDING"),
        ("S-DEMO-03", {"DISTRACTION"}, "林志豪 FSC 純 DISTRACTION"),
    ]

    failed = 0
    for sid, expected, desc in cases:
        got = hits_by_sid.get(sid, set())
        ok = got == expected
        mark = "✓" if ok else "✗"
        print(f"  {mark} {sid} ({desc})")
        print(f"      expected = {sorted(expected)}")
        print(f"      got      = {sorted(got)}")
        if not ok:
            failed += 1

    if failed:
        print(f"\n  ❌ {failed} 個斷言失敗")
        return 1
    print("\n  全數通過 ✓")
    return 0


# =============================================================
# Entry point
# =============================================================
def main() -> int:
    parser = argparse.ArgumentParser(description="Anti-Gaming 合規規則引擎")
    parser.add_argument("--dry-run", action="store_true",
                        help="只列出觸發結果,不寫入 FlaggedSessions")
    parser.add_argument("--test", action="store_true",
                        help="跑 demo 經典案例自動斷言")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"[engine] 找不到 {DB_PATH},請先執行 `python3 seed_data.py`")
        return 2

    conn = sqlite3.connect(DB_PATH)
    try:
        if args.test:
            return run_test(conn)
        hits = run_engine(conn, dry_run=args.dry_run)
        print_top_suspicious(hits)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
