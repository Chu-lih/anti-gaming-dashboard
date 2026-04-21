"""
app.py
======
Flask 主程式:路由骨架 + DB helper + 統一錯誤處理

路由總表
--------
頁面
    GET  /                     → redirect /inbox
    GET  /inbox                → Risk Inbox 主頁(支援 severity/rule/status 篩選)
    GET  /timeline/<flag_id>   → Forensic Timeline 詳細頁
    GET  /rules                → 規則管理頁

API(JSON)
    POST /api/resolve           → 主管送出 approve/void/escalate(寫 audit + 更新 status)
    POST /api/rules/update      → 修改規則 parameter_json / toggle is_active
    POST /api/rescan            → 重跑規則引擎(改規則後可立即見效)
    POST /api/switch-manager    → 切換 demo 主管身份

DB 存取原則
-----------
*  所有 SQL 皆使用 `?` 參數化查詢
*  `get_db()` 以 Flask `g` 管理連線,`teardown_appcontext` 自動關閉
*  外部工具(規則引擎)rescan 時另開連線,避免 row_factory 影響 engine 的 tuple unpack
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from flask import (
    Flask,
    abort,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from rule_engine import run_engine

# ============================================================
# 設定
# ============================================================
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "database.db"

# 主管名單:demo 為求簡單用硬編(實際應走 SSO / HR system)
DEMO_MANAGERS = [
    ("M001", "張經理"),
    ("M002", "林副理"),
    ("M003", "陳襄理"),
]

app = Flask(__name__)
app.config["SECRET_KEY"] = "demo-only-secret-key-change-in-prod"


# ============================================================
# DB Helpers
# ============================================================
def get_db() -> sqlite3.Connection:
    if "db" not in g:
        if not DB_PATH.exists():
            abort(500, description=f"資料庫不存在 ({DB_PATH.name}),請先執行 `python3 seed_data.py`")
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        g.db = conn
    return g.db


@app.teardown_appcontext
def close_db(err: BaseException | None = None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


# ============================================================
# Session / Context
# ============================================================
@app.before_request
def ensure_current_manager() -> None:
    if "manager_id" not in session:
        session["manager_id"] = DEMO_MANAGERS[0][0]
        session["manager_name"] = DEMO_MANAGERS[0][1]


@app.context_processor
def inject_globals() -> dict:
    return {
        "managers": DEMO_MANAGERS,
        "current_manager_id": session.get("manager_id"),
        "current_manager_name": session.get("manager_name"),
    }


# ============================================================
# 頁面路由
# ============================================================
@app.route("/")
def root():
    return redirect(url_for("inbox"))


def _build_flag_filters(args) -> tuple[list[str], list, dict]:
    """抽出 filter 建構邏輯供 /inbox 與 /api/inbox-data 共用。回傳 (where, params, echo)"""
    severity = args.get("severity", "").strip()
    rule = args.get("rule", "").strip()
    status = args.get("status", "pending").strip()
    agent = args.get("agent", "").strip()

    where: list[str] = []
    params: list = []
    if severity in ("Low", "Medium", "High"):
        where.append("r.severity_level = ?")
        params.append(severity)
    if rule:
        where.append("r.rule_code = ?")
        params.append(rule)
    if status and status != "all":
        where.append("f.resolution_status = ?")
        params.append(status)
    if agent:
        where.append("(f.agent_name LIKE ? OR f.agent_id LIKE ?)")
        pattern = f"%{agent}%"
        params.extend([pattern, pattern])

    return where, params, {
        "severity": severity, "rule": rule, "status": status, "agent": agent,
    }


@app.route("/inbox")
def inbox():
    db = get_db()
    where, params, echo = _build_flag_filters(request.args)
    severity_filter = echo["severity"]
    rule_filter = echo["rule"]
    status_filter = echo["status"]
    agent_filter = echo["agent"]

    sql = """
        SELECT f.flag_id, f.session_id, f.agent_id, f.agent_name, f.module_name,
               f.flag_timestamp, f.resolution_status,
               r.rule_code, r.rule_name, r.severity_level
        FROM FlaggedSessions f
        JOIN ComplianceRules r ON f.rule_violated_id = r.rule_id
    """
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += """
        ORDER BY
          CASE r.severity_level
              WHEN 'High' THEN 0
              WHEN 'Medium' THEN 1
              WHEN 'Low' THEN 2
          END,
          f.flag_timestamp DESC
    """
    flags = db.execute(sql, params).fetchall()

    stats = db.execute(
        """
        SELECT
          SUM(CASE WHEN r.severity_level='High'   AND f.resolution_status='pending' THEN 1 ELSE 0 END) AS high_pending,
          SUM(CASE WHEN r.severity_level='Medium' AND f.resolution_status='pending' THEN 1 ELSE 0 END) AS medium_pending,
          SUM(CASE WHEN r.severity_level='Low'    AND f.resolution_status='pending' THEN 1 ELSE 0 END) AS low_pending,
          SUM(CASE WHEN f.resolution_status='pending' THEN 1 ELSE 0 END) AS total_pending,
          COUNT(*) AS total_all
        FROM FlaggedSessions f
        JOIN ComplianceRules r ON f.rule_violated_id = r.rule_id
        """
    ).fetchone()

    # 帶上 severity_level 讓前端可做「依 severity 過濾 rule」的連動下拉
    rules = [
        dict(r) for r in db.execute(
            "SELECT rule_code, rule_name, severity_level FROM ComplianceRules ORDER BY rule_id"
        ).fetchall()
    ]

    return render_template(
        "inbox.html",
        flags=flags,
        stats=stats,
        rules=rules,
        severity_filter=severity_filter,
        rule_filter=rule_filter,
        status_filter=status_filter,
        agent_filter=agent_filter,
    )


@app.route("/timeline/<int:flag_id>")
def timeline(flag_id: int):
    db = get_db()
    row = db.execute(
        """
        SELECT
            f.flag_id, f.session_id, f.agent_id, f.agent_name, f.module_name,
            f.flag_timestamp, f.resolution_status, f.session_telemetry_json,
            r.rule_id, r.rule_code, r.rule_name, r.severity_level,
            r.description AS rule_desc, r.parameter_json,
            m.avg_completion_seconds,
            s.completion_seconds, s.quiz_score, s.quiz_seconds, s.tab_switch_count,
            s.started_at
        FROM FlaggedSessions f
        JOIN ComplianceRules r     ON f.rule_violated_id = r.rule_id
        LEFT JOIN LearningSessions s ON s.session_id = f.session_id
        LEFT JOIN Modules m          ON m.module_name = f.module_name
        WHERE f.flag_id = ?
        """,
        (flag_id,),
    ).fetchone()
    if row is None:
        abort(404, description=f"Flag #{flag_id} 不存在")

    try:
        telemetry = json.loads(row["session_telemetry_json"]) if row["session_telemetry_json"] else []
    except json.JSONDecodeError:
        telemetry = []

    sibling_flags = db.execute(
        """
        SELECT f.flag_id, r.rule_code, r.rule_name, r.severity_level, f.resolution_status
        FROM FlaggedSessions f
        JOIN ComplianceRules r ON f.rule_violated_id = r.rule_id
        WHERE f.session_id = ? AND f.flag_id != ?
        """,
        (row["session_id"], flag_id),
    ).fetchall()

    audits = db.execute(
        """
        SELECT audit_id, manager_id, manager_name, action_taken,
               manager_justification_notes, timestamp
        FROM ComplianceAuditLog
        WHERE flag_id = ?
        ORDER BY timestamp
        """,
        (flag_id,),
    ).fetchall()

    # 把「本 flag 的規則」與「同一 session 的其他 flag」合併成一份清單
    rules_violated = [
        {
            "rule_code": row["rule_code"],
            "rule_name": row["rule_name"],
            "severity_level": row["severity_level"],
            "flag_id": row["flag_id"],
            "resolution_status": row["resolution_status"],
            "is_current": True,
        }
    ]
    for s in sibling_flags:
        rules_violated.append({
            "rule_code": s["rule_code"],
            "rule_name": s["rule_name"],
            "severity_level": s["severity_level"],
            "flag_id": s["flag_id"],
            "resolution_status": s["resolution_status"],
            "is_current": False,
        })

    # SVG 渲染用的 JSON payload(前端 timeline.js 讀取)
    timeline_payload = {
        "flag_id": row["flag_id"],
        "session_id": row["session_id"],
        "module_name": row["module_name"],
        "module_avg_seconds": row["avg_completion_seconds"],
        "completion_seconds": row["completion_seconds"],
        "quiz_score": row["quiz_score"],
        "quiz_seconds": row["quiz_seconds"],
        "tab_switch_count": row["tab_switch_count"],
        "telemetry": telemetry,
    }

    return render_template(
        "timeline.html",
        flag=row,
        telemetry=telemetry,
        rules_violated=rules_violated,
        audits=audits,
        timeline_payload=timeline_payload,
    )


@app.route("/rules")
def rules_page():
    db = get_db()
    rule_rows = db.execute(
        """
        SELECT rule_id, rule_code, rule_name, description, parameter_json,
               severity_level, is_active, created_at
        FROM ComplianceRules
        ORDER BY rule_id
        """
    ).fetchall()

    # 轉成 dict 並 pretty-print parameter_json 供 textarea 使用
    rules = []
    for r in rule_rows:
        d = dict(r)
        try:
            d["parameter_json_pretty"] = json.dumps(
                json.loads(r["parameter_json"]), indent=2, ensure_ascii=False
            )
        except json.JSONDecodeError:
            d["parameter_json_pretty"] = r["parameter_json"]
        rules.append(d)

    # 最近 10 筆規則變更紀錄
    recent_changes = db.execute(
        """
        SELECT change_id, rule_code, change_type, old_value, new_value,
               manager_id, manager_name, timestamp
        FROM RuleChangeLog
        ORDER BY timestamp DESC, change_id DESC
        LIMIT 10
        """
    ).fetchall()

    return render_template("rules.html", rules=rules, recent_changes=recent_changes)


# ============================================================
# API
# ============================================================
@app.route("/api/resolve", methods=["POST"])
def api_resolve():
    data = request.get_json(silent=True) or {}
    flag_id = data.get("flag_id")
    action = data.get("action")
    notes = (data.get("notes") or "").strip()

    if not isinstance(flag_id, int) or action not in ("approve", "void", "escalate"):
        return jsonify({"error": "flag_id (int) 與 action (approve/void/escalate) 必填"}), 400
    if not notes:
        return jsonify({"error": "必須填寫主管決議備註 (manager_justification_notes)"}), 400

    db = get_db()
    row = db.execute(
        "SELECT flag_id, resolution_status FROM FlaggedSessions WHERE flag_id = ?",
        (flag_id,),
    ).fetchone()
    if row is None:
        return jsonify({"error": f"Flag #{flag_id} 不存在"}), 404
    if row["resolution_status"] != "pending":
        return jsonify(
            {"error": f"Flag #{flag_id} 已審結 (status={row['resolution_status']}),不可再變更"}
        ), 409

    status_map = {"approve": "approved", "void": "voided", "escalate": "escalated"}
    new_status = status_map[action]

    try:
        db.execute(
            """
            INSERT INTO ComplianceAuditLog
                (flag_id, manager_id, manager_name, action_taken, manager_justification_notes)
            VALUES (?, ?, ?, ?, ?)
            """,
            (flag_id, session["manager_id"], session["manager_name"], action, notes),
        )
        db.execute(
            "UPDATE FlaggedSessions SET resolution_status = ? WHERE flag_id = ?",
            (new_status, flag_id),
        )
        db.commit()
    except sqlite3.IntegrityError as exc:
        db.rollback()
        return jsonify({"error": f"DB 完整性錯誤: {exc}"}), 500

    return jsonify({"ok": True, "flag_id": flag_id, "new_status": new_status})


@app.route("/api/rules/update", methods=["POST"])
def api_rules_update():
    """只處理 parameter_json 變更(toggle 走另一 endpoint)"""
    data = request.get_json(silent=True) or {}
    rule_id = data.get("rule_id")
    parameter_json = data.get("parameter_json")

    if not isinstance(rule_id, int):
        return jsonify({"error": "rule_id (int) 必填"}), 400
    if parameter_json is None:
        return jsonify({"error": "parameter_json 必填"}), 400

    try:
        parsed = json.loads(parameter_json) if isinstance(parameter_json, str) else parameter_json
        if not isinstance(parsed, dict):
            raise ValueError("parameter_json 必須是 JSON 物件 (dict)")
    except (ValueError, json.JSONDecodeError) as exc:
        return jsonify({"error": f"parameter_json 格式錯誤: {exc}"}), 400

    db = get_db()
    row = db.execute(
        "SELECT rule_id, rule_code, parameter_json FROM ComplianceRules WHERE rule_id = ?",
        (rule_id,),
    ).fetchone()
    if row is None:
        return jsonify({"error": f"Rule #{rule_id} 不存在"}), 404

    new_json = json.dumps(parsed, ensure_ascii=False)
    if new_json == row["parameter_json"]:
        return jsonify({"ok": True, "rule_id": rule_id, "rule_code": row["rule_code"],
                        "unchanged": True})

    db.execute(
        "UPDATE ComplianceRules SET parameter_json = ? WHERE rule_id = ?",
        (new_json, rule_id),
    )
    db.execute(
        """INSERT INTO RuleChangeLog
           (rule_id, rule_code, change_type, old_value, new_value, manager_id, manager_name)
           VALUES (?, ?, 'parameter_update', ?, ?, ?, ?)""",
        (rule_id, row["rule_code"], row["parameter_json"], new_json,
         session["manager_id"], session["manager_name"]),
    )
    db.commit()
    return jsonify({"ok": True, "rule_id": rule_id, "rule_code": row["rule_code"]})


@app.route("/api/rules/toggle", methods=["POST"])
def api_rules_toggle():
    """切換規則 is_active 並寫入 RuleChangeLog"""
    data = request.get_json(silent=True) or {}
    rule_id = data.get("rule_id")
    if not isinstance(rule_id, int):
        return jsonify({"error": "rule_id (int) 必填"}), 400

    db = get_db()
    row = db.execute(
        "SELECT rule_id, rule_code, is_active FROM ComplianceRules WHERE rule_id = ?",
        (rule_id,),
    ).fetchone()
    if row is None:
        return jsonify({"error": f"Rule #{rule_id} 不存在"}), 404

    old_val = int(row["is_active"])
    new_val = 0 if old_val else 1
    db.execute("UPDATE ComplianceRules SET is_active = ? WHERE rule_id = ?", (new_val, rule_id))
    db.execute(
        """INSERT INTO RuleChangeLog
           (rule_id, rule_code, change_type, old_value, new_value, manager_id, manager_name)
           VALUES (?, ?, 'toggle_active', ?, ?, ?, ?)""",
        (rule_id, row["rule_code"], str(old_val), str(new_val),
         session["manager_id"], session["manager_name"]),
    )
    db.commit()
    return jsonify({"ok": True, "rule_id": rule_id, "rule_code": row["rule_code"],
                    "is_active": new_val})


@app.route("/api/inbox-data")
def api_inbox_data():
    """Inbox 頁的 AJAX 篩選資料來源(stats + flags),JSON 回傳"""
    db = get_db()
    where, params, _ = _build_flag_filters(request.args)

    sql = """
        SELECT f.flag_id, f.session_id, f.agent_id, f.agent_name, f.module_name,
               f.flag_timestamp, f.resolution_status,
               r.rule_code, r.rule_name, r.severity_level
        FROM FlaggedSessions f
        JOIN ComplianceRules r ON f.rule_violated_id = r.rule_id
    """
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += """
        ORDER BY
          CASE r.severity_level
              WHEN 'High' THEN 0
              WHEN 'Medium' THEN 1
              WHEN 'Low' THEN 2
          END,
          f.flag_timestamp DESC
    """
    flags = [dict(r) for r in db.execute(sql, params).fetchall()]

    stats_row = db.execute(
        """
        SELECT
          SUM(CASE WHEN r.severity_level='High'   AND f.resolution_status='pending' THEN 1 ELSE 0 END) AS high_pending,
          SUM(CASE WHEN r.severity_level='Medium' AND f.resolution_status='pending' THEN 1 ELSE 0 END) AS medium_pending,
          SUM(CASE WHEN r.severity_level='Low'    AND f.resolution_status='pending' THEN 1 ELSE 0 END) AS low_pending,
          SUM(CASE WHEN f.resolution_status='pending' THEN 1 ELSE 0 END) AS total_pending,
          COUNT(*) AS total_all
        FROM FlaggedSessions f
        JOIN ComplianceRules r ON f.rule_violated_id = r.rule_id
        """
    ).fetchone()

    return jsonify(
        {
            "stats": {k: (stats_row[k] or 0) for k in stats_row.keys()},
            "flags": flags,
        }
    )


@app.route("/api/rescan", methods=["POST"])
def api_rescan():
    # 另開獨立連線:rule_engine 的 RuleRecord/SessionRecord unpack 需 tuple,
    # 不依賴 Flask get_db() 所設的 row_factory
    conn = sqlite3.connect(DB_PATH)
    try:
        hits = run_engine(conn, dry_run=False)
        return jsonify({"ok": True, "hits_total": len(hits)})
    finally:
        conn.close()


@app.route("/api/switch-manager", methods=["POST"])
def api_switch_manager():
    data = request.get_json(silent=True) or {}
    mid = data.get("manager_id")
    match = [m for m in DEMO_MANAGERS if m[0] == mid]
    if not match:
        return jsonify({"error": "unknown manager_id"}), 400
    session["manager_id"] = match[0][0]
    session["manager_name"] = match[0][1]
    return jsonify(
        {"ok": True, "manager_id": match[0][0], "manager_name": match[0][1]}
    )


# ============================================================
# Error handlers(API 回 JSON,頁面回簡易訊息)
# ============================================================
def _wants_json() -> bool:
    return request.path.startswith("/api/") or "application/json" in (request.headers.get("Accept") or "")


@app.errorhandler(400)
def bad_request(err):
    if _wants_json():
        return jsonify({"error": "bad request", "detail": str(err.description)}), 400
    return f"<h1>400 Bad Request</h1><p>{err.description}</p>", 400


@app.errorhandler(404)
def not_found(err):
    if _wants_json():
        return jsonify({"error": "not found", "detail": str(err.description)}), 404
    return f"<h1>404 Not Found</h1><p>{err.description}</p>", 404


@app.errorhandler(500)
def server_error(err):
    if _wants_json():
        return jsonify({"error": "server error", "detail": str(err.description)}), 500
    return f"<h1>500 Server Error</h1><p>{err.description}</p>", 500


# ============================================================
# Entry point
# ============================================================
def _bootstrap_flags_if_empty() -> None:
    """首次啟動時若 FlaggedSessions 為空,自動掃一次(避免 demo 時打開畫面空空)"""
    if not DB_PATH.exists():
        return
    conn = sqlite3.connect(DB_PATH)
    try:
        n = conn.execute("SELECT COUNT(*) FROM FlaggedSessions").fetchone()[0]
        if n == 0:
            print("[app] 偵測到 FlaggedSessions 為空,啟動時自動執行規則引擎...")
            run_engine(conn, dry_run=False)
    finally:
        conn.close()


if __name__ == "__main__":
    _bootstrap_flags_if_empty()
    app.run(debug=True, port=5001)
