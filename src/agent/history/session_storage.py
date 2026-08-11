"""普通会话历史的存储后端抽象（MySQL）。

系统定位:
    为 web/ui_session、agent_utils、tool_call_recorder 提供会话消息与工具调用记录的
    数据库读写入口。与 cron 共用 STORAGE_BACKEND 开关与 MYSQL_* 连接配置
    （见 agent.core.db）。

设计要点（不双写：sql 就是 sql，json 就是 json）:
    - 选 mysql 时：对话消息与工具调用记录**只入库**（不写 turn_*.json / tool_*.json），
      读取只走数据库；二进制产物文件（图片/附件等）仍按 json 方式落盘到 session 文件夹。
    - 选 json 时：本模块所有操作退化为 no-op，读写仍走文件（现状不变）。
    - 消息与工具调用记录**原样**入库（不做路径转换）：DB 行为与文件读取完全一致，
      下游 _serialize_content / _tool_calls_from_turn_record 无需感知数据来源。
    - 写入幂等：save_turn / save_tool_calls 对同一 (session_id, turn_id) 先 DELETE 再 INSERT。
    - sessions 表记录会话的 created_at/updated_at/last_turn_id，供列表排序与 get_last_turn_id。
    - DB 失败仅打印日志，不阻断主流程（与 cron persist_turn_records 一致）。

可扩展性:
    - 未来如需跨机迁移，可在此处增加 relpath 转换（参考 cron/storage._to_rel_paths）。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from typing import Any, Protocol

from agent.core.db import ensure_tables, get_storage_backend, mysql_conn


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


# ---------- 会话三表 DDL（由 ensure_tables 幂等建表） ----------
_SESSION_TABLE_DDLS = [
    """
    CREATE TABLE IF NOT EXISTS sessions (
        session_id   VARCHAR(64) PRIMARY KEY,
        created_at   VARCHAR(32) NOT NULL,
        updated_at   VARCHAR(32) NOT NULL,
        last_turn_id VARCHAR(64) DEFAULT ''
    ) CHARACTER SET utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS session_messages (
        id         BIGINT AUTO_INCREMENT PRIMARY KEY,
        session_id VARCHAR(64) NOT NULL,
        turn_id    VARCHAR(64) NOT NULL,
        seq        INT NOT NULL DEFAULT 0,
        message    JSON NOT NULL,
        INDEX idx_sess_turn (session_id, turn_id)
    ) CHARACTER SET utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS session_tool_calls (
        id         BIGINT AUTO_INCREMENT PRIMARY KEY,
        session_id VARCHAR(64) NOT NULL,
        turn_id    VARCHAR(64) NOT NULL,
        tool_calls JSON NOT NULL,
        meta       JSON DEFAULT NULL,
        INDEX idx_sess_turn (session_id, turn_id)
    ) CHARACTER SET utf8mb4
    """,
]


def is_mysql() -> bool:
    """当前会话存储后端是否为 mysql。"""
    return get_storage_backend() == "mysql"


# ---------- Protocol ----------
class SessionRecordRepository(Protocol):
    """会话消息与工具调用记录的读写接口（mysql 后端实现）。"""

    def save_turn(self, session_id: str, turn_id: str, messages: list[dict]) -> None: ...
    def save_tool_calls(
        self, session_id: str, turn_id: str, tool_calls: list[dict], meta: dict | None = None
    ) -> None: ...
    def load_messages(self, session_id: str) -> list[dict]: ...
    def list_session_ids(self) -> list[str]: ...
    def get_turn_record(self, session_id: str, turn_id: str) -> dict[str, Any] | None: ...
    def get_latest_turn_record(self, session_id: str) -> dict[str, Any] | None: ...
    def list_turn_records(self, session_id: str, limit: int) -> list[dict[str, Any]]: ...
    def get_session_extra(self, session_id: str) -> dict[str, Any]: ...
    def save_session_extra(self, session_id: str, extra: dict[str, Any]) -> None: ...
    def get_last_turn_id(self, session_id: str) -> str: ...
    def delete_turns_after(self, session_id: str, keep_until_turn_id: str) -> None: ...
    def delete_session(self, session_id: str) -> None: ...


# ---------- MySQL 实现 ----------
class MysqlSessionRecordRepository:
    """基于 MySQL（pymysql）的会话记录仓库。

    表: sessions / session_messages / session_tool_calls。
    消息与工具调用记录原样以 JSON 列存储；meta 列存 started_at/ended_at/duration 等。
    """

    def __init__(self) -> None:
        ensure_tables(_SESSION_TABLE_DDLS)
        # 向后兼容：为已有 sessions 表补充 extra 列
        self._ensure_extra_column()

    def _ensure_extra_column(self) -> None:
        """幂等添加 sessions.extra JSON 列（存储 tokens + agent_meta）。"""
        conn = mysql_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "ALTER TABLE sessions ADD COLUMN extra JSON DEFAULT NULL"
                )
            conn.commit()
        except Exception:
            # 列已存在 → 忽略
            pass
        finally:
            conn.close()

    def save_turn(self, session_id: str, turn_id: str, messages: list[dict]) -> None:
        if not session_id or not turn_id:
            return
        conn = mysql_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM session_messages WHERE session_id=%s AND turn_id=%s",
                    (session_id, turn_id),
                )
                for seq, msg in enumerate(messages or []):
                    cur.execute(
                        "INSERT INTO session_messages (session_id, turn_id, seq, message) "
                        "VALUES (%s,%s,%s,%s)",
                        (session_id, turn_id, seq, json.dumps(msg, ensure_ascii=False)),
                    )
                now = _now_iso()
                cur.execute(
                    """
                    INSERT INTO sessions (session_id, created_at, updated_at, last_turn_id)
                    VALUES (%s,%s,%s,%s)
                    ON DUPLICATE KEY UPDATE updated_at=VALUES(updated_at), last_turn_id=VALUES(last_turn_id)
                    """,
                    (session_id, now, now, turn_id),
                )
            conn.commit()
        finally:
            conn.close()

    def save_tool_calls(
        self, session_id: str, turn_id: str, tool_calls: list[dict], meta: dict | None = None
    ) -> None:
        if not session_id or not turn_id:
            return
        meta = meta or {}
        conn = mysql_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM session_tool_calls WHERE session_id=%s AND turn_id=%s",
                    (session_id, turn_id),
                )
                cur.execute(
                    "INSERT INTO session_tool_calls (session_id, turn_id, tool_calls, meta) "
                    "VALUES (%s,%s,%s,%s)",
                    (
                        session_id,
                        turn_id,
                        json.dumps(tool_calls or [], ensure_ascii=False),
                        json.dumps(meta, ensure_ascii=False) if meta else None,
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def load_messages(self, session_id: str) -> list[dict]:
        conn = mysql_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT message FROM session_messages WHERE session_id=%s "
                    "ORDER BY turn_id ASC, seq ASC",
                    (session_id,),
                )
                rows = cur.fetchall() or []
            return [self._loads(r["message"]) for r in rows]
        finally:
            conn.close()

    def list_session_ids(self) -> list[str]:
        conn = mysql_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT session_id FROM sessions ORDER BY updated_at DESC")
                rows = cur.fetchall() or []
            return [r["session_id"] for r in rows]
        finally:
            conn.close()

    def get_turn_record(self, session_id: str, turn_id: str) -> dict[str, Any] | None:
        conn = mysql_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT tool_calls, meta FROM session_tool_calls "
                    "WHERE session_id=%s AND turn_id=%s",
                    (session_id, turn_id),
                )
                row = cur.fetchone()
            if not row:
                return None
            return self._row_to_record(row, session_id, turn_id)
        finally:
            conn.close()

    def get_latest_turn_record(self, session_id: str) -> dict[str, Any] | None:
        conn = mysql_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT turn_id, tool_calls, meta FROM session_tool_calls "
                    "WHERE session_id=%s ORDER BY turn_id DESC LIMIT 1",
                    (session_id,),
                )
                row = cur.fetchone()
            if not row:
                return None
            return self._row_to_record(row, session_id, row["turn_id"])
        finally:
            conn.close()

    def list_turn_records(self, session_id: str, limit: int) -> list[dict[str, Any]]:
        """按 turn_id 倒序返回最近 limit 条 turn 记录（与 tool_*.json 同构）。"""
        conn = mysql_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT turn_id, tool_calls, meta FROM session_tool_calls "
                    "WHERE session_id=%s ORDER BY turn_id DESC LIMIT %s",
                    (session_id, limit),
                )
                rows = cur.fetchall() or []
            return [self._row_to_record(r, session_id, r["turn_id"]) for r in rows]
        finally:
            conn.close()

    def get_session_extra(self, session_id: str) -> dict[str, Any]:
        """读取 sessions.extra JSON 列（含 tokens + agent_meta），不存在时返回 {}。"""
        conn = mysql_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT extra FROM sessions WHERE session_id=%s",
                    (session_id,),
                )
                row = cur.fetchone()
            raw = (row or {}).get("extra")
            return self._loads(raw) if raw is not None else {}
        finally:
            conn.close()

    def save_session_extra(self, session_id: str, extra: dict[str, Any]) -> None:
        """写入 sessions.extra JSON 列；session 行不存在时先创建占位行。"""
        conn = mysql_conn()
        try:
            with conn.cursor() as cur:
                now = _now_iso()
                cur.execute(
                    """
                    INSERT INTO sessions (session_id, created_at, updated_at, extra)
                    VALUES (%s,%s,%s,%s)
                    ON DUPLICATE KEY UPDATE updated_at=%s, extra=VALUES(extra)
                    """,
                    (session_id, now, now, json.dumps(extra, ensure_ascii=False), now),
                )
            conn.commit()
        finally:
            conn.close()

    def get_last_turn_id(self, session_id: str) -> str:
        conn = mysql_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT last_turn_id FROM sessions WHERE session_id=%s",
                    (session_id,),
                )
                row = cur.fetchone()
                if row and row.get("last_turn_id"):
                    return row["last_turn_id"]
                # 回退：从消息表取最大 turn_id
                cur.execute(
                    "SELECT MAX(turn_id) AS m FROM session_messages WHERE session_id=%s",
                    (session_id,),
                )
                r2 = cur.fetchone()
                return (r2 or {}).get("m") or ""
        finally:
            conn.close()

    def delete_turns_after(self, session_id: str, keep_until_turn_id: str) -> None:
        if not session_id:
            return
        conn = mysql_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM session_messages WHERE session_id=%s AND turn_id > %s",
                    (session_id, keep_until_turn_id),
                )
                cur.execute(
                    "DELETE FROM session_tool_calls WHERE session_id=%s AND turn_id > %s",
                    (session_id, keep_until_turn_id),
                )
                # 更新 last_turn_id 为剩余最大 turn_id
                cur.execute(
                    "SELECT MAX(turn_id) AS m FROM session_messages WHERE session_id=%s",
                    (session_id,),
                )
                r = cur.fetchone()
                last = (r or {}).get("m") or ""
                cur.execute(
                    "UPDATE sessions SET last_turn_id=%s, updated_at=%s WHERE session_id=%s",
                    (last, _now_iso(), session_id),
                )
            conn.commit()
        finally:
            conn.close()

    def delete_session(self, session_id: str) -> None:
        if not session_id:
            return
        conn = mysql_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM session_messages WHERE session_id=%s", (session_id,))
                cur.execute("DELETE FROM session_tool_calls WHERE session_id=%s", (session_id,))
                cur.execute("DELETE FROM sessions WHERE session_id=%s", (session_id,))
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _loads(raw: Any) -> Any:
        """pymysql 对 JSON 列可能返回 dict 或 str，统一反序列化。"""
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return {}
        return raw

    @classmethod
    def _row_to_record(cls, row: dict[str, Any], session_id: str, turn_id: str) -> dict[str, Any]:
        """把 session_tool_calls 行还原为与 tool_*.json 同构的 record dict。"""
        tool_calls = cls._loads(row.get("tool_calls")) or []
        meta = cls._loads(row.get("meta")) if row.get("meta") is not None else {}
        if not isinstance(meta, dict):
            meta = {}
        record: dict[str, Any] = {
            "session_id": session_id,
            "turn_id": turn_id,
            "tool_calls": tool_calls,
            "timestamp": turn_id,
        }
        # 合并 meta 中的 started_at/ended_at/duration/aborted 等
        for k in ("started_at", "ended_at", "duration", "aborted"):
            if k in meta:
                record[k] = meta[k]
        return record


# ---------- 工厂 ----------
_session_repo_cache: dict[str, Any] = {}


def get_session_record_repository() -> MysqlSessionRecordRepository:
    """获取会话记录仓库实例（仅在 mysql 后端调用，带缓存）。"""
    if "session_mysql" not in _session_repo_cache:
        _session_repo_cache["session_mysql"] = MysqlSessionRecordRepository()
    return _session_repo_cache["session_mysql"]  # type: ignore[return-value]


# ---------- 模块级便捷封装（内部自检 backend，json 后端 no-op / 返回 None） ----------
def persist_messages(session_id: str, turn_id: str, messages: list[dict]) -> None:
    """mysql 后端下把一轮消息写入 DB；json 后端 no-op。"""
    if not is_mysql() or not session_id or not turn_id:
        return
    try:
        get_session_record_repository().save_turn(session_id, turn_id, messages)
    except Exception as e:
        print(f"[session_storage] persist_messages 失败: {e}", file=sys.stderr)


def persist_tool_calls(
    session_id: str, turn_id: str, tool_calls: list[dict], meta: dict | None = None
) -> None:
    """mysql 后端下把一轮工具调用记录写入 DB；json 后端 no-op。"""
    if not is_mysql() or not session_id or not turn_id:
        return
    try:
        get_session_record_repository().save_tool_calls(session_id, turn_id, tool_calls, meta)
    except Exception as e:
        print(f"[session_storage] persist_tool_calls 失败: {e}", file=sys.stderr)


def load_messages(session_id: str) -> list[dict] | None:
    """mysql 后端返回消息列表；json 后端返回 None（调用方回退文件逻辑）。"""
    if not is_mysql():
        return None
    try:
        return get_session_record_repository().load_messages(session_id)
    except Exception as e:
        print(f"[session_storage] load_messages 失败: {e}", file=sys.stderr)
        return None


def list_session_ids() -> list[str] | None:
    """mysql 后端返回会话 ID 列表（updated_at 倒序）；json 后端返回 None。"""
    if not is_mysql():
        return None
    try:
        return get_session_record_repository().list_session_ids()
    except Exception as e:
        print(f"[session_storage] list_session_ids 失败: {e}", file=sys.stderr)
        return None


def get_turn_record(session_id: str, turn_id: str) -> dict[str, Any] | None:
    """mysql 后端返回 turn 记录（与 tool_*.json 同构）；json 后端返回 None。"""
    if not is_mysql():
        return None
    try:
        return get_session_record_repository().get_turn_record(session_id, turn_id)
    except Exception as e:
        print(f"[session_storage] get_turn_record 失败: {e}", file=sys.stderr)
        return None


def get_latest_turn_record(session_id: str) -> dict[str, Any] | None:
    """mysql 后端返回最近 turn 记录；json 后端返回 None。"""
    if not is_mysql():
        return None
    try:
        return get_session_record_repository().get_latest_turn_record(session_id)
    except Exception as e:
        print(f"[session_storage] get_latest_turn_record 失败: {e}", file=sys.stderr)
        return None


def list_turn_records(session_id: str, limit: int = 5) -> list[dict[str, Any]] | None:
    """mysql 后端返回最近 limit 条 turn 记录（turn_id 倒序）；json 后端返回 None。"""
    if not is_mysql():
        return None
    try:
        return get_session_record_repository().list_turn_records(session_id, limit)
    except Exception as e:
        print(f"[session_storage] list_turn_records 失败: {e}", file=sys.stderr)
        return None


def load_session_extra(session_id: str) -> dict[str, Any] | None:
    """mysql 后端返回 sessions.extra（tokens + agent_meta）；json 后端返回 None。"""
    if not is_mysql():
        return None
    try:
        return get_session_record_repository().get_session_extra(session_id)
    except Exception as e:
        print(f"[session_storage] load_session_extra 失败: {e}", file=sys.stderr)
        return None


def save_session_extra(session_id: str, extra: dict[str, Any]) -> None:
    """mysql 后端下写入 sessions.extra；json 后端 no-op。"""
    if not is_mysql():
        return
    try:
        get_session_record_repository().save_session_extra(session_id, extra)
    except Exception as e:
        print(f"[session_storage] save_session_extra 失败: {e}", file=sys.stderr)


def get_last_turn_id(session_id: str) -> str | None:
    """mysql 后端返回最后 turn_id；json 后端返回 None。"""
    if not is_mysql():
        return None
    try:
        return get_session_record_repository().get_last_turn_id(session_id)
    except Exception as e:
        print(f"[session_storage] get_last_turn_id 失败: {e}", file=sys.stderr)
        return None


def delete_turns_after(session_id: str, keep_until_turn_id: str) -> None:
    """mysql 后端下删除 keep_until_turn_id 之后的 turn 记录；json 后端 no-op。"""
    if not is_mysql():
        return
    try:
        get_session_record_repository().delete_turns_after(session_id, keep_until_turn_id)
    except Exception as e:
        print(f"[session_storage] delete_turns_after 失败: {e}", file=sys.stderr)


def delete_session(session_id: str) -> None:
    """mysql 后端下删除会话全部记录；json 后端 no-op。"""
    if not is_mysql():
        return
    try:
        get_session_record_repository().delete_session(session_id)
    except Exception as e:
        print(f"[session_storage] delete_session 失败: {e}", file=sys.stderr)
