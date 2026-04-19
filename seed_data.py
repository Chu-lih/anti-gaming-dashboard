"""
seed_data.py
============
初始化 SQLite DB + 生成假資料。

資料量:
    - 15 業務員、3 主管
    - 10 個學習模組(涵蓋 AML、投資型保單、KYC、FSC 新規 等)
    - 80 筆 LearningSession:
          * ~60 筆正常
          * ~20 筆混合作弊模式(SPEEDING / BLIND_GUESSING / DISTRACTION)
          * 其中包含 3 組「demo 經典案例」,面試時可當故事主軸

執行:
    python3 seed_data.py
    → 產生 database.db,清空後重灌
"""

from __future__ import annotations

import json
import os
import random
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------
# 常數
# ---------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "database.db"
SCHEMA_PATH = BASE_DIR / "schema.sql"

random.seed(42)  # 結果可重現,demo 時每次跑都一樣

# ---------------------------------------------------------------
# 預設規則 (由規則引擎 dispatch)
# ---------------------------------------------------------------
DEFAULT_RULES = [
    {
        "rule_name": "Impossible Speed Verification",
        "rule_code": "SPEEDING",
        "description": "完成時間小於該模組平均時長之設定比例(疑似未閱讀)",
        "parameter_json": json.dumps({"min_completion_ratio": 0.2}),
        "severity_level": "High",
        "is_active": 1,
    },
    {
        "rule_name": "Blind Guessing Pattern",
        "rule_code": "BLIND_GUESSING",
        "description": "答題時間過短且得分為 0(疑似亂猜跳過)",
        "parameter_json": json.dumps({"max_quiz_seconds": 5, "max_score": 0.0}),
        "severity_level": "High",
        "is_active": 1,
    },
    {
        "rule_name": "Distraction / Excessive Tab Switching",
        "rule_code": "DISTRACTION",
        "description": "7 分鐘內切換分頁次數超標(疑似分心或外部協助)",
        "parameter_json": json.dumps({"max_tab_switches": 5, "window_seconds": 420}),
        "severity_level": "Medium",
        "is_active": 1,
    },
]

# ---------------------------------------------------------------
# 模組:模組名 + 公司平均完成秒數
# ---------------------------------------------------------------
MODULES = [
    ("AML 反洗錢基礎", 420),
    ("KYC 客戶身分審查", 360),
    ("FSC 金融消費者保護法新規", 480),
    ("投資型保單 DM 揭露要點", 300),
    ("利變型壽險商品結構", 540),
    ("個人資料保護與資料外洩應變", 420),
    ("信用卡交叉銷售合規", 360),
    ("反詐騙與社交工程辨識", 300),
    ("FATCA 與海外所得申報", 480),
    ("數位金融 KYC eID 流程", 360),
]

# ---------------------------------------------------------------
# 業務員 / 主管
# ---------------------------------------------------------------
AGENTS = [
    ("A001", "王大明"), ("A002", "陳美麗"), ("A003", "林志豪"),
    ("A004", "黃佳琪"), ("A005", "張建國"), ("A006", "李雅文"),
    ("A007", "吳柏翰"), ("A008", "蔡欣怡"), ("A009", "鄭宇廷"),
    ("A010", "謝宜芳"), ("A011", "周凱文"), ("A012", "許若涵"),
    ("A013", "葉宗翰"), ("A014", "潘美君"), ("A015", "曾彥勳"),
]

MANAGERS = [
    ("M001", "張經理"),
    ("M002", "林副理"),
    ("M003", "陳襄理"),
]

# ---------------------------------------------------------------
# Telemetry 生成器
# ---------------------------------------------------------------
def build_normal_telemetry(completion_sec: int, tab_switches: int = 0) -> list[dict]:
    """正常學習軌跡:按步驟完成,無異常"""
    events = [{"time": 0, "event": "session_start"}]
    # 內容瀏覽
    for i in range(1, 6):
        t = int(completion_sec * i / 6)
        events.append({"time": t, "event": "card_swiped", "detail": f"card {i}/5"})
    # 切 tab (若有)
    for _ in range(tab_switches):
        t = random.randint(30, max(31, completion_sec - 30))
        events.append({"time": t, "event": "tab_switch", "detail": "switched to external app"})
        events.append({"time": t + 3, "event": "tab_return"})
    events.append({"time": completion_sec - 20, "event": "quiz_started"})
    events.append({"time": completion_sec, "event": "quiz_submitted", "detail": "completed"})
    events.sort(key=lambda e: e["time"])
    return events


def build_speeding_telemetry(completion_sec: int) -> list[dict]:
    """秒過整個模組 (e.g., 420 秒模組 15 秒做完)"""
    return [
        {"time": 0, "event": "session_start"},
        {"time": 1, "event": "card_swiped", "detail": "card 1/5"},
        {"time": 2, "event": "card_swiped", "detail": "card 2/5"},
        {"time": 3, "event": "card_swiped", "detail": "card 3/5"},
        {"time": 4, "event": "card_swiped", "detail": "card 4/5"},
        {"time": 5, "event": "card_swiped", "detail": "card 5/5 (all cards in 5s)"},
        {"time": 6, "event": "quiz_started"},
        {"time": completion_sec, "event": "quiz_submitted", "detail": "speed-clicked through"},
    ]


def build_blind_guessing_telemetry(completion_sec: int, quiz_sec: int) -> list[dict]:
    """正常瀏覽,但 quiz 秒答 0 分"""
    events = [{"time": 0, "event": "session_start"}]
    for i in range(1, 6):
        t = int((completion_sec - quiz_sec) * i / 6)
        events.append({"time": t, "event": "card_swiped", "detail": f"card {i}/5"})
    events.append({"time": completion_sec - quiz_sec, "event": "quiz_started"})
    events.append({"time": completion_sec, "event": "quiz_submitted",
                   "detail": f"0/3 correct in {quiz_sec}s (blind guess)"})
    return events


def build_distraction_telemetry(completion_sec: int, switch_count: int) -> list[dict]:
    """頻繁切 tab (疑似外部協助 / 分心)"""
    events = [{"time": 0, "event": "session_start"}]
    switch_targets = ["LINE", "Chrome 新分頁", "Facebook", "Gmail", "YouTube", "ChatGPT"]
    # 切 tab 都塞進 420 秒 (7 分鐘) 內
    window = min(420, completion_sec - 10)
    switch_times = sorted(random.sample(range(10, window), min(switch_count, window - 10)))
    for t in switch_times:
        target = random.choice(switch_targets)
        events.append({"time": t, "event": "tab_switch", "detail": f"switched to {target}"})
        events.append({"time": t + random.randint(2, 15), "event": "tab_return"})
    for i in range(1, 6):
        t = int(completion_sec * i / 7)
        events.append({"time": t, "event": "card_swiped", "detail": f"card {i}/5"})
    events.append({"time": completion_sec - 15, "event": "quiz_started"})
    events.append({"time": completion_sec, "event": "quiz_submitted"})
    events.sort(key=lambda e: e["time"])
    return events


# ---------------------------------------------------------------
# Session 產生器
# ---------------------------------------------------------------
def gen_session_id(idx: int) -> str:
    return f"S{idx:05d}"


def build_sessions() -> list[dict]:
    """回傳 list of dict,每筆對應一筆 LearningSession"""
    sessions: list[dict] = []
    module_map = {name: (i + 1, avg) for i, (name, avg) in enumerate(MODULES)}
    now = datetime(2026, 4, 17, 9, 0, 0)
    sid = 1

    # --- 60 筆正常 session ---
    for _ in range(60):
        agent_id, agent_name = random.choice(AGENTS)
        module_name, (module_id, avg) = random.choice(list(module_map.items()))
        # 完成時間 0.6x ~ 1.3x 平均
        comp = int(avg * random.uniform(0.6, 1.3))
        tab = random.randint(0, 3)
        quiz_sec = random.randint(15, 60)
        score = round(random.uniform(0.67, 1.0), 2)
        sessions.append({
            "session_id": gen_session_id(sid),
            "agent_id": agent_id, "agent_name": agent_name,
            "module_id": module_id, "module_name": module_name,
            "completion_seconds": comp,
            "quiz_score": score, "quiz_seconds": quiz_sec,
            "tab_switch_count": tab,
            "telemetry_json": json.dumps(build_normal_telemetry(comp, tab), ensure_ascii=False),
            "started_at": (now - timedelta(hours=random.randint(1, 72))).isoformat(sep=" "),
        })
        sid += 1

    # --- demo 經典案例:王大明 AML 合規(高嚴重度三規則齊發) ---
    # 420 秒模組做 12 秒,quiz 4 秒 0 分,tab 切 LINE 6 次
    aml_id, aml_avg = module_map["AML 反洗錢基礎"]
    telemetry_wang = [
        {"time": 0, "event": "session_start"},
        {"time": 1, "event": "card_swiped", "detail": "card 1/5"},
        {"time": 2, "event": "tab_switch", "detail": "switched to LINE"},
        {"time": 3, "event": "tab_return"},
        {"time": 4, "event": "card_swiped", "detail": "card 2/5"},
        {"time": 5, "event": "tab_switch", "detail": "switched to LINE"},
        {"time": 6, "event": "tab_return"},
        {"time": 7, "event": "card_swiped", "detail": "card 3/5"},
        {"time": 8, "event": "card_swiped", "detail": "card 4/5 & 5/5"},
        {"time": 8, "event": "quiz_started"},
        {"time": 9, "event": "tab_switch", "detail": "switched to LINE"},
        {"time": 10, "event": "tab_return"},
        {"time": 10, "event": "tab_switch", "detail": "switched to Chrome 新分頁"},
        {"time": 11, "event": "tab_return"},
        {"time": 11, "event": "tab_switch", "detail": "switched to LINE"},
        {"time": 11, "event": "tab_return"},
        {"time": 11, "event": "tab_switch", "detail": "switched to LINE"},
        {"time": 12, "event": "tab_return"},
        {"time": 12, "event": "quiz_submitted", "detail": "0/3 correct in 4s"},
    ]
    sessions.append({
        "session_id": "S-DEMO-01",
        "agent_id": "A001", "agent_name": "王大明",
        "module_id": aml_id, "module_name": "AML 反洗錢基礎",
        "completion_seconds": 12, "quiz_score": 0.0, "quiz_seconds": 4,
        "tab_switch_count": 6,
        "telemetry_json": json.dumps(telemetry_wang, ensure_ascii=False),
        "started_at": (now - timedelta(hours=2)).isoformat(sep=" "),
    })

    # --- demo 經典案例:陳美麗 投資型保單 DM 揭露(純 SPEEDING) ---
    inv_id, inv_avg = module_map["投資型保單 DM 揭露要點"]
    sessions.append({
        "session_id": "S-DEMO-02",
        "agent_id": "A002", "agent_name": "陳美麗",
        "module_id": inv_id, "module_name": "投資型保單 DM 揭露要點",
        "completion_seconds": 48, "quiz_score": 1.0, "quiz_seconds": 25,
        "tab_switch_count": 1,
        "telemetry_json": json.dumps(build_speeding_telemetry(48), ensure_ascii=False),
        "started_at": (now - timedelta(hours=5)).isoformat(sep=" "),
    })

    # --- demo 經典案例:林志豪 FSC 新規(DISTRACTION 獨發) ---
    fsc_id, fsc_avg = module_map["FSC 金融消費者保護法新規"]
    sessions.append({
        "session_id": "S-DEMO-03",
        "agent_id": "A003", "agent_name": "林志豪",
        "module_id": fsc_id, "module_name": "FSC 金融消費者保護法新規",
        "completion_seconds": 460, "quiz_score": 0.67, "quiz_seconds": 38,
        "tab_switch_count": 9,
        "telemetry_json": json.dumps(build_distraction_telemetry(460, 9), ensure_ascii=False),
        "started_at": (now - timedelta(hours=8)).isoformat(sep=" "),
    })

    sid = 64  # 接續

    # --- 額外 17 筆可疑 session (隨機分佈三種作弊) ---
    cheat_types = ["SPEEDING"] * 6 + ["BLIND_GUESSING"] * 6 + ["DISTRACTION"] * 5
    random.shuffle(cheat_types)
    for ctype in cheat_types:
        agent_id, agent_name = random.choice(AGENTS)
        module_name, (module_id, avg) = random.choice(list(module_map.items()))
        if ctype == "SPEEDING":
            comp = int(avg * random.uniform(0.05, 0.18))  # 低於 20% 門檻
            score = round(random.uniform(0.33, 1.0), 2)
            quiz_sec = random.randint(5, 20)
            tab = random.randint(0, 2)
            telemetry = build_speeding_telemetry(comp)
        elif ctype == "BLIND_GUESSING":
            comp = int(avg * random.uniform(0.4, 1.0))
            quiz_sec = random.randint(2, 4)
            score = 0.0
            tab = random.randint(0, 2)
            telemetry = build_blind_guessing_telemetry(comp, quiz_sec)
        else:  # DISTRACTION
            comp = int(avg * random.uniform(0.9, 1.2))
            quiz_sec = random.randint(20, 45)
            score = round(random.uniform(0.5, 1.0), 2)
            tab = random.randint(6, 10)
            telemetry = build_distraction_telemetry(comp, tab)
        sessions.append({
            "session_id": gen_session_id(sid),
            "agent_id": agent_id, "agent_name": agent_name,
            "module_id": module_id, "module_name": module_name,
            "completion_seconds": comp,
            "quiz_score": score, "quiz_seconds": quiz_sec,
            "tab_switch_count": tab,
            "telemetry_json": json.dumps(telemetry, ensure_ascii=False),
            "started_at": (now - timedelta(hours=random.randint(1, 72))).isoformat(sep=" "),
        })
        sid += 1

    return sessions


# ---------------------------------------------------------------
# 主程序
# ---------------------------------------------------------------
def main() -> None:
    if DB_PATH.exists():
        os.remove(DB_PATH)
        print(f"[seed] 已刪除舊 DB: {DB_PATH.name}")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")

    # 1. 執行 schema
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(schema_sql)
    print(f"[seed] schema.sql 執行完成")

    # 2. 插入規則
    for r in DEFAULT_RULES:
        conn.execute(
            """INSERT INTO ComplianceRules
               (rule_name, rule_code, description, parameter_json, severity_level, is_active)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (r["rule_name"], r["rule_code"], r["description"],
             r["parameter_json"], r["severity_level"], r["is_active"]),
        )
    print(f"[seed] 插入 {len(DEFAULT_RULES)} 條合規規則")

    # 3. 插入模組
    for name, avg in MODULES:
        conn.execute(
            "INSERT INTO Modules (module_name, avg_completion_seconds) VALUES (?, ?)",
            (name, avg),
        )
    print(f"[seed] 插入 {len(MODULES)} 個學習模組")

    # 4. 插入 sessions
    sessions = build_sessions()
    for s in sessions:
        conn.execute(
            """INSERT INTO LearningSessions
               (session_id, agent_id, agent_name, module_id, module_name,
                completion_seconds, quiz_score, quiz_seconds, tab_switch_count,
                telemetry_json, started_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (s["session_id"], s["agent_id"], s["agent_name"], s["module_id"],
             s["module_name"], s["completion_seconds"], s["quiz_score"],
             s["quiz_seconds"], s["tab_switch_count"], s["telemetry_json"],
             s["started_at"]),
        )
    print(f"[seed] 插入 {len(sessions)} 筆學習 session(含 3 筆 demo 經典案例)")

    conn.commit()
    conn.close()
    print(f"[seed] 完成 → {DB_PATH}")


if __name__ == "__main__":
    main()
