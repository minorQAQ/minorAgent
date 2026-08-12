"""统一存储抽象层：会话与定时任务的 JSON / MySQL 双后端存储。

系统定位:
    会话历史（对话消息、工具调用记录、token/压缩元数据）与定时任务（任务配置、
    执行记录）共用的存储接口与后端实现。消费方（agent_utils / tool_call_recorder /
    ui_session / server / cron 等）只依赖本模块暴露的接口与便捷函数，
    **不感知后端选择**（不判断 STORAGE_BACKEND / is_mysql）。

接口隔离:
    - ``ConversationRecordRepository``：对话记录读写接口（16 方法）。
    - ``TaskConfigRepository``：cron 任务配置读写接口（6 方法）。
    - 新增存储后端 = 实现上述 Protocol + 在 ``get_record_repository`` /
      ``get_task_repository`` 工厂中注册一行。

作用域（scope）:
    - ``session``（默认）：主进程普通会话，JSON 落盘于 ``SESSIONS_ROOT``，
      MySQL 使用 ``sessions / session_messages / session_tool_calls`` 表。
    - ``cron``：定时任务，JSON 落盘于 ``CRON_ROOT``（history/cron），
      MySQL 使用 ``cron_messages / cron_tool_calls`` 表。
      主进程读 cron 记录用 ``get_record_repository(scope="cron")``；
      cron 子进程在 ``runner._redirect_storage_roots`` 中调用
      ``set_storage_scope("cron")``，使模块级便捷函数直接路由到 cron 作用域。

不双写:
    选哪种后端，读写就只走该后端。二进制产物文件（图片/附件等）始终落盘，
    与后端无关（由消费方负责，见 tool_call_recorder.save_turn）。

可扩展性:
    - 消费方新增字段/功能无需改动本模块：工具调用记录的 meta 全量透传，
      消息与记录原样 JSON 入库/落盘。
    - 新增存储方式（如 postgres）只需实现两个 Protocol 并注册工厂。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import threading
from typing import Any, Protocol

from agent.cron.models import CronTask, ExecutionLog
from agent.utils import agent_utils as _au
from agent.utils.agent_utils import HISTORY_ROOT, TURN_JSON_PREFIX
from agent.core.db import (
    mysql_conn,
    ensure_tables,
    get_storage_backend,
)

# 定时任务根目录：history/cron
CRON_ROOT = os.path.join(HISTORY_ROOT, "cron")
os.makedirs(CRON_ROOT, exist_ok=True)

# ---------- 作用域（cron 子进程切换为 "cron"） ----------
_STORAGE_SCOPE = "session"


def set_storage_scope(scope: str) -> None:
    """切换模块级便捷函数的存储作用域（"session" / "cron"）。

    供 cron 子进程（runner._redirect_storage_roots）调用，使后续所有
    记录读写路由到 cron 作用域（CRON_ROOT 文件 / cron_* 表）。
    """
    global _STORAGE_SCOPE
    _STORAGE_SCOPE = scope if scope == "cron" else "session"


def get_storage_scope() -> str:
    """返回当前存储作用域。"""
    return _STORAGE_SCOPE


# ---------- Protocol 定义 ----------
class ConversationRecordRepository(Protocol):
    """对话消息与工具调用记录的读写接口（session / cron 双作用域通用）。"""

    def save_turn(self, session_id: str, turn_id: str, messages: list[dict]) -> None: ...
    def load_messages(self, session_id: str) -> list[dict]: ...
    def load_turn_messages(self, session_id: str, turn_id: str) -> list[dict] | None: ...
    def list_turn_ids(self, session_id: str) -> list[str]: ...
    def save_tool_calls(
        self, session_id: str, turn_id: str, tool_calls: list[dict], meta: dict | None = None
    ) -> None: ...
    def get_turn_record(self, session_id: str, turn_id: str) -> dict[str, Any] | None: ...
    def get_latest_turn_record(self, session_id: str) -> dict[str, Any] | None: ...
    def list_turn_records(self, session_id: str, limit: int = 5) -> list[dict[str, Any]]: ...
    def persist_live_records(
        self, session_id: str, turn_id: str, records: list[dict], started_at: float | None = None
    ) -> None: ...
    def load_session_extra(self, session_id: str) -> dict[str, Any]: ...
    def save_session_extra(self, session_id: str, extra: dict[str, Any]) -> None: ...
    def list_session_ids(self) -> list[str]: ...
    def get_last_turn_id(self, session_id: str) -> str: ...
    def delete_turns_after(self, session_id: str, keep_until_turn_id: str) -> int: ...
    def delete_tool_records(self, session_id: str, keep_turn_ids: set[str] | None = None) -> None: ...
    def delete_session(self, session_id: str) -> None: ...


class TaskConfigRepository(Protocol):
    """定时任务配置与状态的读写接口。"""

    def list_tasks(self) -> list[CronTask]: ...
    def get_task(self, task_id: str) -> CronTask | None: ...
    def save_task(self, task: CronTask) -> None: ...
    def delete_task(self, task_id: str) -> None: ...
    def update_status(
        self,
        task_id: str,
        status: str,
        *,
        error: str = "",
        last_run_at: str = "",
        next_run_at: str = "",
    ) -> None: ...
    def append_execution(self, task_id: str, exec_log: dict[str, Any]) -> None: ...


# ---------- MySQL 表 DDL（幂等建表，session / cron 互不影响） ----------
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

_CRON_TABLE_DDLS = [
    """
    CREATE TABLE IF NOT EXISTS cron_tasks (
        task_id          VARCHAR(64) PRIMARY KEY,
        name             VARCHAR(255) NOT NULL,
        prompt           TEXT NOT NULL,
        trigger_type     ENUM('cron','interval','once') NOT NULL,
        cron_expr        VARCHAR(128) DEFAULT '',
        interval_seconds INT DEFAULT 0,
        run_at           VARCHAR(32) DEFAULT '',
        enabled          TINYINT(1) DEFAULT 1,
        timeout_seconds  INT DEFAULT 300,
        created_at       VARCHAR(32) NOT NULL,
        next_run_at      VARCHAR(32) DEFAULT '',
        last_run_at      VARCHAR(32) DEFAULT '',
        last_status      VARCHAR(16) DEFAULT 'pending',
        last_error       TEXT,
        executions       JSON DEFAULT NULL
    ) CHARACTER SET utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS cron_messages (
        id      BIGINT AUTO_INCREMENT PRIMARY KEY,
        task_id VARCHAR(64) NOT NULL,
        turn_id VARCHAR(64) NOT NULL,
        role    VARCHAR(16) NOT NULL,
        content JSON NOT NULL,
        meta    JSON DEFAULT NULL,
        INDEX idx_task_turn (task_id, turn_id)
    ) CHARACTER SET utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS cron_tool_calls (
        id         BIGINT AUTO_INCREMENT PRIMARY KEY,
        task_id    VARCHAR(64) NOT NULL,
        turn_id    VARCHAR(64) NOT NULL,
        tool_calls JSON NOT NULL,
        INDEX idx_task_turn (task_id, turn_id)
    ) CHARACTER SET utf8mb4
    """,
]


def _ensure_session_tables() -> None:
    """幂等建 session 三表（委托共享 ensure_tables）。"""
    ensure_tables(_SESSION_TABLE_DDLS)


def _ensure_cron_tables() -> None:
    """幂等建 cron 三表（委托共享 ensure_tables）。"""
    ensure_tables(_CRON_TABLE_DDLS)


# ---------- 附件路径解析（cron 作用域共用：JSON / MySQL） ----------
def _resolve_msg_paths(msg: dict, task_id: str) -> dict:
    """将消息 content 中的相对附件路径解析为绝对地址（相对 CRON_ROOT）。

    cron 子进程写入 / 数据库存储的附件路径均为相对 CRON_ROOT 的 relpath，
    主进程序列化前还原为绝对路径，供文件读取。
    """
    content = msg.get("content")
    if not isinstance(content, list):
        return msg
    for piece in content:
        if not isinstance(piece, dict):
            continue
        for key in ("path", "audio_path"):
            p = piece.get(key)
            if isinstance(p, str) and p and not os.path.isabs(p):
                piece[key] = os.path.normpath(os.path.join(CRON_ROOT, p))
        iu = piece.get("image_url")
        if isinstance(iu, dict):
            u = iu.get("url")
            if isinstance(u, str) and u and not u.startswith("data:") and not os.path.isabs(u):
                iu["url"] = os.path.normpath(os.path.join(CRON_ROOT, u))
    return msg


def _to_rel_paths(msg: dict, task_id: str) -> dict:
    """_resolve_msg_paths 的逆操作：绝对路径 → 相对 CRON_ROOT 的 relpath（入库前调用）。"""
    import copy
    msg = copy.deepcopy(msg)
    content = msg.get("content")
    if not isinstance(content, list):
        return msg
    cron_root_abs = os.path.abspath(CRON_ROOT)
    for piece in content:
        if not isinstance(piece, dict):
            continue
        for key in ("path", "audio_path"):
            p = piece.get(key)
            if isinstance(p, str) and p and os.path.isabs(p):
                try:
                    rel = os.path.relpath(p, cron_root_abs)
                    piece[key] = rel.replace("\\", "/")
                except ValueError:
                    pass
        iu = piece.get("image_url")
        if isinstance(iu, dict):
            u = iu.get("url")
            if isinstance(u, str) and u and not u.startswith("data:") and os.path.isabs(u):
                try:
                    rel = os.path.relpath(u, cron_root_abs)
                    iu["url"] = rel.replace("\\", "/")
                except ValueError:
                    pass
    return msg


# ---------- JSON 实现 ----------
class JsonRecordRepository:
    """基于 JSON 文件（人类可读、可直观查看）的记录仓库。

    session 作用域根目录为 SESSIONS_ROOT（动态引用 agent_utils.SESSIONS_ROOT，
    兼容 cron 子进程的重定向）；cron 作用域根目录为 CRON_ROOT。
    文件格式保持不变：turn_{tid}.json / tool_{tid}.json / session_meta.json /
    _session_tokens.json。
    """

    def __init__(self, scope: str = "session") -> None:
        self.scope = scope if scope == "cron" else "session"

    def _root(self) -> str:
        if self.scope == "cron":
            return CRON_ROOT
        return _au.SESSIONS_ROOT

    def _session_dir(self, session_id: str) -> str:
        return os.path.join(self._root(), session_id)

    def _turn_path(self, session_id: str, turn_id: str) -> str:
        return os.path.join(self._session_dir(session_id), f"{TURN_JSON_PREFIX}{turn_id}.json")

    def _tool_path(self, session_id: str, turn_id: str) -> str:
        return os.path.join(self._session_dir(session_id), f"tool_{turn_id}.json")

    def _meta_path(self, session_id: str) -> str:
        return os.path.join(self._session_dir(session_id), "session_meta.json")

    def _token_path(self, session_id: str) -> str:
        return os.path.join(self._session_dir(session_id), "_session_tokens.json")

    # ---- 消息 ----
    def save_turn(self, session_id: str, turn_id: str, messages: list[dict]) -> None:
        if not session_id or not turn_id:
            return
        sess_dir = self._session_dir(session_id)
        os.makedirs(sess_dir, exist_ok=True)
        with open(self._turn_path(session_id, turn_id), "w", encoding="utf-8") as f:
            json.dump({"turn_id": turn_id, "messages": messages}, f, ensure_ascii=False, indent=2)

    def load_messages(self, session_id: str) -> list[dict]:
        sess_dir = self._session_dir(session_id)
        if not os.path.isdir(sess_dir):
            return []
        all_msgs: list[dict] = []
        for tf in sorted(
            f for f in os.listdir(sess_dir)
            if f.startswith(TURN_JSON_PREFIX) and f.endswith(".json")
        ):
            tp = os.path.join(sess_dir, tf)
            if not os.path.isfile(tp):
                continue
            try:
                with open(tp, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for msg in data.get("messages", []):
                    if self.scope == "cron":
                        msg = _resolve_msg_paths(msg, session_id)
                    all_msgs.append(msg)
            except (json.JSONDecodeError, OSError):
                pass
        return all_msgs

    def load_turn_messages(self, session_id: str, turn_id: str) -> list[dict] | None:
        tp = self._turn_path(session_id, turn_id)
        if not os.path.isfile(tp):
            return None
        try:
            with open(tp, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("messages", []) or []
        except (json.JSONDecodeError, OSError):
            return None

    def list_turn_ids(self, session_id: str) -> list[str]:
        sess_dir = self._session_dir(session_id)
        if not os.path.isdir(sess_dir):
            return []
        return sorted(
            f[len(TURN_JSON_PREFIX):-len(".json")]
            for f in os.listdir(sess_dir)
            if f.startswith(TURN_JSON_PREFIX) and f.endswith(".json")
        )

    # ---- 工具调用记录 ----
    def save_tool_calls(
        self, session_id: str, turn_id: str, tool_calls: list[dict], meta: dict | None = None
    ) -> None:
        if not session_id or not turn_id:
            return
        sess_dir = self._session_dir(session_id)
        os.makedirs(sess_dir, exist_ok=True)
        record: dict[str, Any] = {
            "session_id": session_id,
            "turn_id": turn_id,
            "tool_calls": tool_calls,
            "timestamp": turn_id,
        }
        if meta:
            record.update(meta)  # meta 全量透传，消费方新增字段无需改动存储层
        with open(self._tool_path(session_id, turn_id), "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)

    def get_turn_record(self, session_id: str, turn_id: str) -> dict[str, Any] | None:
        tp = self._tool_path(session_id, turn_id)
        if not os.path.isfile(tp):
            return None
        try:
            with open(tp, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

    def get_latest_turn_record(self, session_id: str) -> dict[str, Any] | None:
        records = self.list_turn_records(session_id, limit=1)
        return records[0] if records else None

    def list_turn_records(self, session_id: str, limit: int = 5) -> list[dict[str, Any]]:
        sess_dir = self._session_dir(session_id)
        if not os.path.isdir(sess_dir):
            return []
        files = sorted(
            f for f in os.listdir(sess_dir)
            if f.startswith("tool_") and f.endswith(".json")
        )
        records: list[dict[str, Any]] = []
        for fname in reversed(files):
            tp = os.path.join(sess_dir, fname)
            try:
                with open(tp, "r", encoding="utf-8") as f:
                    records.append(json.load(f))
            except (json.JSONDecodeError, OSError):
                continue
            if limit and len(records) >= limit:
                break
        return records

    def persist_live_records(
        self, session_id: str, turn_id: str, records: list[dict], started_at: float | None = None
    ) -> None:
        """实时工具记录增量写盘（可选行为；mysql 后端不实现）。"""
        if not session_id or not turn_id:
            return
        sess_dir = self._session_dir(session_id)
        os.makedirs(sess_dir, exist_ok=True)
        record: dict[str, Any] = {
            "session_id": session_id,
            "turn_id": turn_id,
            "tool_calls": records,
            "timestamp": turn_id,
        }
        if started_at:
            record["started_at"] = started_at
        with open(self._tool_path(session_id, turn_id), "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)

    # ---- 会话元数据（extra = {tokens, token_breakdown, agent_meta}） ----
    def load_session_extra(self, session_id: str) -> dict[str, Any]:
        extra: dict[str, Any] = {}
        # agent_meta ↔ session_meta.json
        mp = self._meta_path(session_id)
        if os.path.isfile(mp):
            try:
                with open(mp, "r", encoding="utf-8") as f:
                    extra["agent_meta"] = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        # tokens / token_breakdown ↔ _session_tokens.json
        tf = self._token_path(session_id)
        if os.path.isfile(tf):
            try:
                with open(tf, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if "tokens" in data:
                    extra["tokens"] = data.get("tokens", 0)
                if "breakdown" in data and isinstance(data.get("breakdown"), dict):
                    extra["token_breakdown"] = data["breakdown"]
            except (json.JSONDecodeError, OSError):
                pass
        return extra

    def save_session_extra(self, session_id: str, extra: dict[str, Any]) -> None:
        if not session_id:
            return
        sess_dir = self._session_dir(session_id)
        os.makedirs(sess_dir, exist_ok=True)
        if "agent_meta" in extra:
            with open(self._meta_path(session_id), "w", encoding="utf-8") as f:
                json.dump(extra.get("agent_meta") or {}, f, ensure_ascii=False, indent=2)
        if "tokens" in extra or "token_breakdown" in extra:
            payload: dict[str, Any] = {
                "session_id": session_id,
                "tokens": extra.get("tokens", 0),
            }
            if "token_breakdown" in extra and isinstance(extra.get("token_breakdown"), dict):
                payload["breakdown"] = extra["token_breakdown"]
            with open(self._token_path(session_id), "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)

    # ---- 会话生命周期 ----
    def list_session_ids(self) -> list[str]:
        root = self._root()
        if not os.path.isdir(root):
            return []
        entries: list[tuple[float, str]] = []
        for name in os.listdir(root):
            dir_path = os.path.join(root, name)
            if not os.path.isdir(dir_path):
                continue
            try:
                has_turns = any(
                    f.startswith(TURN_JSON_PREFIX) and f.endswith(".json")
                    for f in os.listdir(dir_path)
                )
            except OSError:
                has_turns = False
            if has_turns:
                entries.append((os.path.getmtime(dir_path), name))
        entries.sort(key=lambda x: x[0], reverse=True)
        return [name for _, name in entries]

    def get_last_turn_id(self, session_id: str) -> str:
        sess_dir = self._session_dir(session_id)
        if not os.path.isdir(sess_dir):
            return ""
        turn_files = sorted(
            f for f in os.listdir(sess_dir)
            if f.startswith(TURN_JSON_PREFIX) and f.endswith(".json")
        )
        if not turn_files:
            return ""
        return turn_files[-1][len(TURN_JSON_PREFIX):-len(".json")]

    def delete_turns_after(self, session_id: str, keep_until_turn_id: str) -> int:
        """删除 keep 之后的 turn 消息与工具调用记录（turn_*.json / tool_*.json）。"""
        sess_dir = self._session_dir(session_id)
        if not os.path.isdir(sess_dir):
            return 0
        keep_turn_full = f"{TURN_JSON_PREFIX}{keep_until_turn_id}.json"
        keep_tool_full = f"tool_{keep_until_turn_id}.json"
        deleted = 0
        for fname in sorted(os.listdir(sess_dir)):
            if fname.startswith(TURN_JSON_PREFIX) and fname.endswith(".json"):
                if fname > keep_turn_full:
                    try:
                        os.remove(os.path.join(sess_dir, fname))
                        deleted += 1
                    except OSError:
                        pass
            elif fname.startswith("tool_") and fname.endswith(".json"):
                if fname > keep_tool_full:
                    try:
                        os.remove(os.path.join(sess_dir, fname))
                    except OSError:
                        pass
        return deleted

    def delete_tool_records(self, session_id: str, keep_turn_ids: set[str] | None = None) -> None:
        sess_dir = self._session_dir(session_id)
        if not os.path.isdir(sess_dir):
            return
        for fname in os.listdir(sess_dir):
            if not (fname.startswith("tool_") and fname.endswith(".json")):
                continue
            if keep_turn_ids:
                turn_id = fname[len("tool_"):-len(".json")]
                if turn_id in keep_turn_ids:
                    continue
            try:
                os.remove(os.path.join(sess_dir, fname))
            except OSError:
                pass

    def delete_session(self, session_id: str) -> None:
        sess_dir = self._session_dir(session_id)
        if os.path.isdir(sess_dir):
            shutil.rmtree(sess_dir, ignore_errors=True)


# ---------- MySQL 实现 ----------
class MysqlRecordRepository:
    """基于 MySQL（pymysql）的记录仓库。

    session 作用域表: sessions / session_messages / session_tool_calls；
    cron 作用域表: cron_messages / cron_tool_calls。
    消息与工具调用记录原样 JSON 入库；工具记录 meta 全量透传（不白名单）。
    """

    def __init__(self, scope: str = "session") -> None:
        self.scope = scope if scope == "cron" else "session"
        if self.scope == "cron":
            _ensure_cron_tables()
        else:
            _ensure_session_tables()
            self._ensure_extra_column()

    # ---- 表名 / 连接 ----
    def _messages_table(self) -> str:
        return "cron_messages" if self.scope == "cron" else "session_messages"

    def _tool_table(self) -> str:
        return "cron_tool_calls" if self.scope == "cron" else "session_tool_calls"

    def _sessions_table(self) -> str | None:
        return None if self.scope == "cron" else "sessions"

    def _sid_col(self) -> str:
        return "task_id" if self.scope == "cron" else "session_id"

    @staticmethod
    def _now_iso() -> str:
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    def _ensure_extra_column(self) -> None:
        """幂等添加 sessions.extra JSON 列（存储 tokens + agent_meta）。"""
        conn = mysql_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("ALTER TABLE sessions ADD COLUMN extra JSON DEFAULT NULL")
            conn.commit()
        except Exception:
            pass  # 列已存在 → 忽略
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
        if isinstance(raw, (bytes, bytearray)):
            try:
                return json.loads(raw.decode("utf-8"))
            except Exception:
                return {}
        return raw

    # ---- 消息 ----
    def save_turn(self, session_id: str, turn_id: str, messages: list[dict]) -> None:
        if not session_id or not turn_id:
            return
        sid_col = self._sid_col()
        conn = mysql_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"DELETE FROM {self._messages_table()} WHERE {sid_col}=%s AND turn_id=%s",
                    (session_id, turn_id),
                )
                if self.scope == "cron":
                    # cron 表按 role/content/meta 分列存储，附件路径转相对 CRON_ROOT
                    messages = [_to_rel_paths(m, session_id) for m in messages or []]
                    for msg in messages:
                        content = msg.get("content")
                        meta = msg.get("meta")
                        cur.execute(
                            f"INSERT INTO {self._messages_table()} "
                            f"({sid_col}, turn_id, role, content, meta) VALUES (%s,%s,%s,%s,%s)",
                            (
                                session_id, turn_id, msg.get("role", "user"),
                                json.dumps(content, ensure_ascii=False),
                                json.dumps(meta, ensure_ascii=False) if meta is not None else None,
                            ),
                        )
                else:
                    for seq, msg in enumerate(messages or []):
                        cur.execute(
                            f"INSERT INTO {self._messages_table()} "
                            f"(session_id, turn_id, seq, message) VALUES (%s,%s,%s,%s)",
                            (session_id, turn_id, seq, json.dumps(msg, ensure_ascii=False)),
                        )
                    now = self._now_iso()
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

    def load_messages(self, session_id: str) -> list[dict]:
        sid_col = self._sid_col()
        conn = mysql_conn()
        try:
            with conn.cursor() as cur:
                if self.scope == "cron":
                    cur.execute(
                        f"SELECT turn_id, role, content, meta FROM {self._messages_table()} "
                        f"WHERE {sid_col}=%s ORDER BY id",
                        (session_id,),
                    )
                    rows = cur.fetchall() or []
                    msgs: list[dict] = []
                    for r in rows:
                        content = self._loads(r.get("content"))
                        meta = self._loads(r.get("meta"))
                        msg: dict[str, Any] = {"role": r.get("role", "user"), "content": content}
                        if isinstance(meta, dict) and meta:
                            msg["meta"] = meta
                        msgs.append(_resolve_msg_paths(msg, session_id))
                    return msgs
                cur.execute(
                    f"SELECT message FROM {self._messages_table()} "
                    f"WHERE session_id=%s ORDER BY turn_id ASC, seq ASC",
                    (session_id,),
                )
                rows = cur.fetchall() or []
                return [self._loads(r["message"]) for r in rows]
        finally:
            conn.close()

    def load_turn_messages(self, session_id: str, turn_id: str) -> list[dict] | None:
        sid_col = self._sid_col()
        conn = mysql_conn()
        try:
            with conn.cursor() as cur:
                if self.scope == "cron":
                    cur.execute(
                        f"SELECT turn_id, role, content, meta FROM {self._messages_table()} "
                        f"WHERE {sid_col}=%s AND turn_id=%s ORDER BY id",
                        (session_id, turn_id),
                    )
                    rows = cur.fetchall() or []
                    if not rows:
                        return None
                    msgs: list[dict] = []
                    for r in rows:
                        content = self._loads(r.get("content"))
                        meta = self._loads(r.get("meta"))
                        msg: dict[str, Any] = {"role": r.get("role", "user"), "content": content}
                        if isinstance(meta, dict) and meta:
                            msg["meta"] = meta
                        msgs.append(_resolve_msg_paths(msg, session_id))
                    return msgs
                cur.execute(
                    f"SELECT message FROM {self._messages_table()} "
                    f"WHERE session_id=%s AND turn_id=%s ORDER BY seq ASC",
                    (session_id, turn_id),
                )
                rows = cur.fetchall() or []
                if not rows:
                    return None
                return [self._loads(r["message"]) for r in rows]
        finally:
            conn.close()

    def list_turn_ids(self, session_id: str) -> list[str]:
        sid_col = self._sid_col()
        conn = mysql_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT DISTINCT turn_id FROM {self._messages_table()} "
                    f"WHERE {sid_col}=%s ORDER BY turn_id",
                    (session_id,),
                )
                rows = cur.fetchall() or []
            return [r["turn_id"] for r in rows]
        finally:
            conn.close()

    # ---- 工具调用记录 ----
    def save_tool_calls(
        self, session_id: str, turn_id: str, tool_calls: list[dict], meta: dict | None = None
    ) -> None:
        if not session_id or not turn_id:
            return
        sid_col = self._sid_col()
        conn = mysql_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"DELETE FROM {self._tool_table()} WHERE {sid_col}=%s AND turn_id=%s",
                    (session_id, turn_id),
                )
                if self.scope == "cron":
                    # cron_tool_calls 无 meta 列（与既有表结构一致）
                    cur.execute(
                        f"INSERT INTO {self._tool_table()} ({sid_col}, turn_id, tool_calls) "
                        "VALUES (%s,%s,%s)",
                        (session_id, turn_id, json.dumps(tool_calls or [], ensure_ascii=False)),
                    )
                else:
                    cur.execute(
                        f"INSERT INTO {self._tool_table()} "
                        "(session_id, turn_id, tool_calls, meta) VALUES (%s,%s,%s,%s)",
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

    @classmethod
    def _row_to_record(cls, row: dict[str, Any], session_id: str, turn_id: str,
                       meta_key: str | None = None) -> dict[str, Any]:
        """把工具调用表行还原为与 tool_*.json 同构的 record dict。

        meta 全量透传（不做字段白名单）：消费方新增 meta 字段无需改动存储层。
        """
        tool_calls = cls._loads(row.get("tool_calls")) or []
        record: dict[str, Any] = {
            "session_id": session_id,
            "turn_id": turn_id,
            "tool_calls": tool_calls,
            "timestamp": turn_id,
        }
        if meta_key and row.get(meta_key) is not None:
            meta = cls._loads(row.get(meta_key))
            if isinstance(meta, dict):
                record.update(meta)
        return record

    def get_turn_record(self, session_id: str, turn_id: str) -> dict[str, Any] | None:
        sid_col = self._sid_col()
        conn = mysql_conn()
        try:
            with conn.cursor() as cur:
                if self.scope == "cron":
                    cur.execute(
                        f"SELECT tool_calls FROM {self._tool_table()} "
                        f"WHERE {sid_col}=%s AND turn_id=%s ORDER BY id",
                        (session_id, turn_id),
                    )
                    rows = cur.fetchall() or []
                    out: list[dict] = []
                    for r in rows:
                        tc = self._loads(r.get("tool_calls"))
                        if isinstance(tc, list):
                            out.extend(tc)
                    if not out:
                        return None
                    return {"session_id": session_id, "turn_id": turn_id,
                            "tool_calls": out, "timestamp": turn_id}
                cur.execute(
                    f"SELECT tool_calls, meta FROM {self._tool_table()} "
                    f"WHERE session_id=%s AND turn_id=%s",
                    (session_id, turn_id),
                )
                row = cur.fetchone()
            if not row:
                return None
            return self._row_to_record(row, session_id, turn_id, meta_key="meta")
        finally:
            conn.close()

    def get_latest_turn_record(self, session_id: str) -> dict[str, Any] | None:
        sid_col = self._sid_col()
        conn = mysql_conn()
        try:
            with conn.cursor() as cur:
                if self.scope == "cron":
                    cur.execute(
                        f"SELECT turn_id, tool_calls FROM {self._tool_table()} "
                        f"WHERE {sid_col}=%s ORDER BY turn_id DESC LIMIT 1",
                        (session_id,),
                    )
                    row = cur.fetchone()
                    if not row:
                        return None
                    tc = self._loads(row.get("tool_calls"))
                    return {"session_id": session_id, "turn_id": row.get("turn_id", ""),
                            "tool_calls": tc if isinstance(tc, list) else [],
                            "timestamp": row.get("turn_id", "")}
                cur.execute(
                    f"SELECT turn_id, tool_calls, meta FROM {self._tool_table()} "
                    f"WHERE session_id=%s ORDER BY turn_id DESC LIMIT 1",
                    (session_id,),
                )
                row = cur.fetchone()
            if not row:
                return None
            return self._row_to_record(row, session_id, row["turn_id"], meta_key="meta")
        finally:
            conn.close()

    def list_turn_records(self, session_id: str, limit: int = 5) -> list[dict[str, Any]]:
        """按 turn_id 倒序返回最近 limit 条 turn 记录（与 tool_*.json 同构）。"""
        sid_col = self._sid_col()
        conn = mysql_conn()
        try:
            with conn.cursor() as cur:
                if self.scope == "cron":
                    cur.execute(
                        f"SELECT turn_id, tool_calls FROM {self._tool_table()} "
                        f"WHERE {sid_col}=%s ORDER BY turn_id DESC LIMIT %s",
                        (session_id, limit),
                    )
                    rows = cur.fetchall() or []
                    out: list[dict] = []
                    for r in rows:
                        tc = self._loads(r.get("tool_calls"))
                        out.append({"session_id": session_id, "turn_id": r.get("turn_id", ""),
                                    "tool_calls": tc if isinstance(tc, list) else [],
                                    "timestamp": r.get("turn_id", "")})
                    return out
                cur.execute(
                    f"SELECT turn_id, tool_calls, meta FROM {self._tool_table()} "
                    f"WHERE session_id=%s ORDER BY turn_id DESC LIMIT %s",
                    (session_id, limit),
                )
                rows = cur.fetchall() or []
            return [self._row_to_record(r, session_id, r["turn_id"], meta_key="meta") for r in rows]
        finally:
            conn.close()

    def persist_live_records(
        self, session_id: str, turn_id: str, records: list[dict], started_at: float | None = None
    ) -> None:
        """实时工具记录不增量入库（由 save_tool_calls 在 turn 结束时统一落库）。"""

    # ---- 会话元数据（extra） ----
    def load_session_extra(self, session_id: str) -> dict[str, Any]:
        """读取 sessions.extra JSON 列（含 tokens + agent_meta）；cron 作用域无此表 → {}。"""
        table = self._sessions_table()
        if table is None:
            return {}
        conn = mysql_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT extra FROM sessions WHERE session_id=%s", (session_id,))
                row = cur.fetchone()
            raw = (row or {}).get("extra")
            return self._loads(raw) if raw is not None else {}
        finally:
            conn.close()

    def save_session_extra(self, session_id: str, extra: dict[str, Any]) -> None:
        """写入 sessions.extra JSON 列（与既有 extra 增量合并，不覆盖未涉及的键）。

        与 json 实现按 key 拆分的语义一致：消费方既可 load-modify-save 全量写入，
        也可只传增量键。cron 作用域无此表 → no-op。
        """
        table = self._sessions_table()
        if table is None or not session_id:
            return
        conn = mysql_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT extra FROM sessions WHERE session_id=%s", (session_id,))
                row = cur.fetchone()
                existing = self._loads((row or {}).get("extra")) if row else {}
                if not isinstance(existing, dict):
                    existing = {}
                existing.update(extra or {})
                now = self._now_iso()
                cur.execute(
                    """
                    INSERT INTO sessions (session_id, created_at, updated_at, extra)
                    VALUES (%s,%s,%s,%s)
                    ON DUPLICATE KEY UPDATE updated_at=%s, extra=VALUES(extra)
                    """,
                    (session_id, now, now, json.dumps(existing, ensure_ascii=False), now),
                )
            conn.commit()
        finally:
            conn.close()

    # ---- 会话生命周期 ----
    def list_session_ids(self) -> list[str]:
        conn = mysql_conn()
        try:
            with conn.cursor() as cur:
                if self.scope == "cron":
                    cur.execute(
                        "SELECT session_id FROM cron_messages "
                        "GROUP BY session_id ORDER BY MAX(id) DESC"
                    )
                else:
                    cur.execute("SELECT session_id FROM sessions ORDER BY updated_at DESC")
                rows = cur.fetchall() or []
            return [r["session_id"] for r in rows]
        finally:
            conn.close()

    def get_last_turn_id(self, session_id: str) -> str:
        sid_col = self._sid_col()
        conn = mysql_conn()
        try:
            with conn.cursor() as cur:
                if self.scope == "cron":
                    cur.execute(
                        f"SELECT MAX(turn_id) AS m FROM {self._messages_table()} "
                        f"WHERE {sid_col}=%s",
                        (session_id,),
                    )
                    r = cur.fetchone()
                    return (r or {}).get("m") or ""
                cur.execute(
                    "SELECT last_turn_id FROM sessions WHERE session_id=%s",
                    (session_id,),
                )
                row = cur.fetchone()
                if row and row.get("last_turn_id"):
                    return row["last_turn_id"]
                cur.execute(
                    "SELECT MAX(turn_id) AS m FROM session_messages WHERE session_id=%s",
                    (session_id,),
                )
                r2 = cur.fetchone()
                return (r2 or {}).get("m") or ""
        finally:
            conn.close()

    def delete_turns_after(self, session_id: str, keep_until_turn_id: str) -> int:
        if not session_id:
            return 0
        sid_col = self._sid_col()
        conn = mysql_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"DELETE FROM {self._messages_table()} "
                    f"WHERE {sid_col}=%s AND turn_id > %s",
                    (session_id, keep_until_turn_id),
                )
                cur.execute(
                    f"DELETE FROM {self._tool_table()} "
                    f"WHERE {sid_col}=%s AND turn_id > %s",
                    (session_id, keep_until_turn_id),
                )
                if self.scope == "session":
                    cur.execute(
                        "SELECT MAX(turn_id) AS m FROM session_messages WHERE session_id=%s",
                        (session_id,),
                    )
                    r = cur.fetchone()
                    last = (r or {}).get("m") or ""
                    cur.execute(
                        "UPDATE sessions SET last_turn_id=%s, updated_at=%s WHERE session_id=%s",
                        (last, self._now_iso(), session_id),
                    )
            conn.commit()
        finally:
            conn.close()
        return 0

    def delete_tool_records(self, session_id: str, keep_turn_ids: set[str] | None = None) -> None:
        if not session_id:
            return
        sid_col = self._sid_col()
        conn = mysql_conn()
        try:
            with conn.cursor() as cur:
                if keep_turn_ids:
                    if not keep_turn_ids:
                        return
                    placeholders = ",".join(["%s"] * len(keep_turn_ids))
                    cur.execute(
                        f"DELETE FROM {self._tool_table()} "
                        f"WHERE {sid_col}=%s AND turn_id NOT IN ({placeholders})",
                        (session_id, *sorted(keep_turn_ids)),
                    )
                else:
                    cur.execute(
                        f"DELETE FROM {self._tool_table()} WHERE {sid_col}=%s",
                        (session_id,),
                    )
            conn.commit()
        finally:
            conn.close()

    def delete_session(self, session_id: str) -> None:
        if not session_id:
            return
        sid_col = self._sid_col()
        conn = mysql_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"DELETE FROM {self._messages_table()} WHERE {sid_col}=%s", (session_id,)
                )
                cur.execute(
                    f"DELETE FROM {self._tool_table()} WHERE {sid_col}=%s", (session_id,)
                )
                if self.scope == "session":
                    cur.execute("DELETE FROM sessions WHERE session_id=%s", (session_id,))
            conn.commit()
        finally:
            conn.close()


# ---------- JSON 任务仓库 ----------
class JsonTaskConfigRepository:
    """基于 JSON 文件的任务仓库。

    存储路径: CRON_ROOT/{task_id}/cron_task.json
    """

    def _task_dir(self, task_id: str) -> str:
        return os.path.join(CRON_ROOT, task_id)

    def _task_file(self, task_id: str) -> str:
        return os.path.join(self._task_dir(task_id), "cron_task.json")

    def list_tasks(self) -> list[CronTask]:
        if not os.path.isdir(CRON_ROOT):
            return []
        tasks: list[CronTask] = []
        for name in os.listdir(CRON_ROOT):
            tf = self._task_file(name)
            if not os.path.isfile(tf):
                continue
            task = self._load(tf)
            if task:
                tasks.append(task)
        tasks.sort(key=lambda t: t.created_at, reverse=True)
        return tasks

    def get_task(self, task_id: str) -> CronTask | None:
        return self._load(self._task_file(task_id))

    def save_task(self, task: CronTask) -> None:
        if not task.task_id:
            return
        d = self._task_dir(task.task_id)
        os.makedirs(d, exist_ok=True)
        with open(self._task_file(task.task_id), "w", encoding="utf-8") as f:
            json.dump(task.to_dict(), f, ensure_ascii=False, indent=2)

    def delete_task(self, task_id: str) -> None:
        if not task_id:
            return
        d = self._task_dir(task_id)
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)

    def update_status(
        self,
        task_id: str,
        status: str,
        *,
        error: str = "",
        last_run_at: str = "",
        next_run_at: str = "",
    ) -> None:
        task = self.get_task(task_id)
        if not task:
            return
        task.last_status = status  # type: ignore[assignment]
        if error:
            task.last_error = error
        elif status != "failed":
            task.last_error = ""
        if last_run_at:
            task.last_run_at = last_run_at
        if next_run_at is not None:
            task.next_run_at = next_run_at
        self.save_task(task)

    def append_execution(self, task_id: str, exec_log: dict[str, Any]) -> None:
        task = self.get_task(task_id)
        if not task:
            return
        task.executions.append(ExecutionLog.from_dict(exec_log))
        self.save_task(task)

    @staticmethod
    def _load(path: str) -> CronTask | None:
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return CronTask.from_dict(json.load(f))
        except (json.JSONDecodeError, OSError):
            return None


# ---------- MySQL 任务仓库 ----------
def _row_to_task(row: dict[str, Any]) -> CronTask:
    """MySQL 行 → CronTask（构造与 to_dict 同构的 dict 再 from_dict）。"""
    executions = row.get("executions")
    if isinstance(executions, str):
        try:
            executions = json.loads(executions)
        except (json.JSONDecodeError, TypeError):
            executions = []
    elif isinstance(executions, (bytes, bytearray)):
        try:
            executions = json.loads(executions.decode("utf-8"))
        except Exception:
            executions = []
    elif not isinstance(executions, list):
        executions = []
    d = {
        "task_id": row.get("task_id", ""),
        "name": row.get("name", ""),
        "prompt": row.get("prompt", ""),
        "trigger": {
            "type": row.get("trigger_type", "cron"),
            "cron": row.get("cron_expr", "") or "",
            "interval_seconds": int(row.get("interval_seconds", 0) or 0),
            "run_at": row.get("run_at", "") or "",
        },
        "enabled": bool(row.get("enabled", 1)),
        "timeout_seconds": int(row.get("timeout_seconds", 300) or 300),
        "created_at": row.get("created_at", "") or "",
        "next_run_at": row.get("next_run_at", "") or "",
        "last_run_at": row.get("last_run_at", "") or "",
        "last_status": row.get("last_status", "pending") or "pending",
        "last_error": row.get("last_error", "") or "",
        "executions": executions,
    }
    return CronTask.from_dict(d)


class MysqlTaskConfigRepository:
    """基于 MySQL（pymysql）的任务仓库。

    表: cron_tasks。trigger 拆为 trigger_type/cron_expr/interval_seconds/run_at 列，
    executions 存为 JSON 列。
    """

    def __init__(self) -> None:
        _ensure_cron_tables()

    def list_tasks(self) -> list[CronTask]:
        conn = mysql_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM cron_tasks ORDER BY created_at DESC")
                rows = cur.fetchall() or []
            return [_row_to_task(r) for r in rows]
        finally:
            conn.close()

    def get_task(self, task_id: str) -> CronTask | None:
        conn = mysql_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM cron_tasks WHERE task_id=%s", (task_id,))
                row = cur.fetchone()
            return _row_to_task(row) if row else None
        finally:
            conn.close()

    def save_task(self, task: CronTask) -> None:
        if not task.task_id:
            return
        trig = task.trigger
        execs_json = json.dumps([e.to_dict() for e in task.executions], ensure_ascii=False)
        conn = mysql_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO cron_tasks
                      (task_id, name, prompt, trigger_type, cron_expr, interval_seconds, run_at,
                       enabled, timeout_seconds, created_at, next_run_at, last_run_at,
                       last_status, last_error, executions)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON DUPLICATE KEY UPDATE
                      name=VALUES(name), prompt=VALUES(prompt), trigger_type=VALUES(trigger_type),
                      cron_expr=VALUES(cron_expr), interval_seconds=VALUES(interval_seconds),
                      run_at=VALUES(run_at), enabled=VALUES(enabled),
                      timeout_seconds=VALUES(timeout_seconds), next_run_at=VALUES(next_run_at),
                      last_run_at=VALUES(last_run_at), last_status=VALUES(last_status),
                      last_error=VALUES(last_error), executions=VALUES(executions)
                    """,
                    (
                        task.task_id, task.name, task.prompt, trig.type, trig.cron,
                        trig.interval_seconds, trig.run_at, int(task.enabled),
                        task.timeout_seconds, task.created_at, task.next_run_at,
                        task.last_run_at, task.last_status, task.last_error, execs_json,
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def delete_task(self, task_id: str) -> None:
        if not task_id:
            return
        conn = mysql_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM cron_tasks WHERE task_id=%s", (task_id,))
                cur.execute("DELETE FROM cron_messages WHERE task_id=%s", (task_id,))
                cur.execute("DELETE FROM cron_tool_calls WHERE task_id=%s", (task_id,))
            conn.commit()
        finally:
            conn.close()

    def update_status(
        self,
        task_id: str,
        status: str,
        *,
        error: str = "",
        last_run_at: str = "",
        next_run_at: str = "",
    ) -> None:
        sets: list[str] = ["last_status=%s"]
        vals: list[Any] = [status]
        if error:
            sets.append("last_error=%s")
            vals.append(error)
        elif status != "failed":
            sets.append("last_error=%s")
            vals.append("")
        if last_run_at:
            sets.append("last_run_at=%s")
            vals.append(last_run_at)
        sets.append("next_run_at=%s")
        vals.append(next_run_at)
        vals.append(task_id)
        conn = mysql_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE cron_tasks SET {', '.join(sets)} WHERE task_id=%s",
                    vals,
                )
            conn.commit()
        finally:
            conn.close()

    def append_execution(self, task_id: str, exec_log: dict[str, Any]) -> None:
        conn = mysql_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT executions FROM cron_tasks WHERE task_id=%s", (task_id,))
                row = cur.fetchone()
                execs: list = []
                if row and row.get("executions"):
                    raw = row["executions"]
                    if isinstance(raw, str):
                        try:
                            execs = json.loads(raw)
                        except (json.JSONDecodeError, TypeError):
                            execs = []
                    elif isinstance(raw, list):
                        execs = raw
                execs.append(exec_log)
                cur.execute(
                    "UPDATE cron_tasks SET executions=%s WHERE task_id=%s",
                    (json.dumps(execs, ensure_ascii=False), task_id),
                )
            conn.commit()
        finally:
            conn.close()


# ---------- 工厂 ----------
_repo_cache: dict[str, Any] = {}


def get_record_repository(scope: str | None = None) -> ConversationRecordRepository:
    """获取记录仓库实例（按 STORAGE_BACKEND + 作用域选择实现并缓存）。

    主进程读 cron 记录时显式传 scope="cron"；其余场合不传，使用模块级作用域。
    """
    scope = (scope or _STORAGE_SCOPE) if (scope or _STORAGE_SCOPE) in ("session", "cron") else "session"
    backend = get_storage_backend()
    key = f"{scope}:{backend}"
    if key not in _repo_cache:
        if backend == "mysql":
            _repo_cache[key] = MysqlRecordRepository(scope)
        else:
            _repo_cache[key] = JsonRecordRepository(scope)
    return _repo_cache[key]  # type: ignore[return-value]


def get_task_repository() -> TaskConfigRepository:
    """获取任务仓库实例（按配置选择 json / mysql）。"""
    backend = get_storage_backend()
    if backend == "mysql":
        if "task_mysql" not in _repo_cache:
            _repo_cache["task_mysql"] = MysqlTaskConfigRepository()
        return _repo_cache["task_mysql"]  # type: ignore[return-value]
    if "task_json" not in _repo_cache:
        _repo_cache["task_json"] = JsonTaskConfigRepository()
    return _repo_cache["task_json"]  # type: ignore[return-value]


def new_task_id() -> str:
    """生成基于时间戳的任务 ID（与 session_id 同构风格）。"""
    from datetime import datetime
    base = datetime.now().strftime("%Y%m%d_%H%M%S")
    existing = {t.task_id for t in get_task_repository().list_tasks()}
    if base not in existing:
        return base
    n = 1
    while True:
        cand = f"{base}_{n}"
        if cand not in existing:
            return cand
        n += 1


# ---------- 模块级便捷函数（消费方无感知后端选择；失败仅日志，不阻断主流程） ----------
def _repo() -> ConversationRecordRepository:
    return get_record_repository()


def save_turn(session_id: str, turn_id: str, messages: list[dict]) -> None:
    """持久化一轮对话消息（后端按配置选择，不双写）。"""
    try:
        _repo().save_turn(session_id, turn_id, messages)
    except Exception as e:
        print(f"[storage] save_turn 失败: {e}", file=sys.stderr)


def load_messages(session_id: str) -> list[dict]:
    """按时间顺序加载所有 turn 的消息，返回扁平列表。"""
    try:
        return _repo().load_messages(session_id)
    except Exception as e:
        print(f"[storage] load_messages 失败: {e}", file=sys.stderr)
        return []


def load_turn_messages(session_id: str, turn_id: str) -> list[dict] | None:
    """加载指定 turn 的消息；不存在返回 None。"""
    try:
        return _repo().load_turn_messages(session_id, turn_id)
    except Exception as e:
        print(f"[storage] load_turn_messages 失败: {e}", file=sys.stderr)
        return None


def list_turn_ids(session_id: str) -> list[str]:
    """列出会话全部 turn_id（升序）。"""
    try:
        return _repo().list_turn_ids(session_id)
    except Exception as e:
        print(f"[storage] list_turn_ids 失败: {e}", file=sys.stderr)
        return []


def save_tool_calls(
    session_id: str, turn_id: str, tool_calls: list[dict], meta: dict | None = None
) -> None:
    """持久化一轮工具调用记录（meta 全量透传）。"""
    try:
        _repo().save_tool_calls(session_id, turn_id, tool_calls, meta)
    except Exception as e:
        print(f"[storage] save_tool_calls 失败: {e}", file=sys.stderr)


def get_turn_record(session_id: str, turn_id: str) -> dict[str, Any] | None:
    """读取指定 turn 的工具调用记录（与 tool_*.json 同构）。"""
    try:
        return _repo().get_turn_record(session_id, turn_id)
    except Exception as e:
        print(f"[storage] get_turn_record 失败: {e}", file=sys.stderr)
        return None


def get_latest_turn_record(session_id: str) -> dict[str, Any] | None:
    """读取最近一个 turn 的工具调用记录。"""
    try:
        return _repo().get_latest_turn_record(session_id)
    except Exception as e:
        print(f"[storage] get_latest_turn_record 失败: {e}", file=sys.stderr)
        return None


def list_turn_records(session_id: str, limit: int = 5) -> list[dict[str, Any]]:
    """按 turn_id 倒序返回最近 limit 条 turn 记录。"""
    try:
        return _repo().list_turn_records(session_id, limit)
    except Exception as e:
        print(f"[storage] list_turn_records 失败: {e}", file=sys.stderr)
        return []


def persist_live_records(
    session_id: str, turn_id: str, records: list[dict], started_at: float | None = None
) -> None:
    """实时工具记录增量持久化（可选行为：json 写盘，mysql 不实现）。"""
    try:
        _repo().persist_live_records(session_id, turn_id, records, started_at)
    except Exception:
        pass  # 持久化失败不应影响主流程


def load_session_extra(session_id: str) -> dict[str, Any]:
    """读取会话扩展元数据（tokens / token_breakdown / agent_meta）。"""
    try:
        return _repo().load_session_extra(session_id) or {}
    except Exception as e:
        print(f"[storage] load_session_extra 失败: {e}", file=sys.stderr)
        return {}


def save_session_extra(session_id: str, extra: dict[str, Any]) -> None:
    """写入会话扩展元数据（后端无关）。"""
    try:
        _repo().save_session_extra(session_id, extra)
    except Exception as e:
        print(f"[storage] save_session_extra 失败: {e}", file=sys.stderr)


def list_session_ids() -> list[str]:
    """按最近活动倒序列出所有会话 ID。"""
    try:
        return _repo().list_session_ids()
    except Exception as e:
        print(f"[storage] list_session_ids 失败: {e}", file=sys.stderr)
        return []


def get_last_turn_id(session_id: str) -> str:
    """获取最后一条 turn_id；无记录返回空串。"""
    try:
        return _repo().get_last_turn_id(session_id) or ""
    except Exception as e:
        print(f"[storage] get_last_turn_id 失败: {e}", file=sys.stderr)
        return ""


def delete_turns_after(session_id: str, keep_until_turn_id: str) -> int:
    """删除 keep_until_turn_id 之后的 turn 消息与工具调用记录；返回删除的 turn 数。"""
    try:
        return _repo().delete_turns_after(session_id, keep_until_turn_id)
    except Exception as e:
        print(f"[storage] delete_turns_after 失败: {e}", file=sys.stderr)
        return 0


def delete_tool_records(session_id: str, keep_turn_ids: set[str] | None = None) -> None:
    """删除工具调用记录（keep_turn_ids 为 None 时全部删除）。"""
    try:
        _repo().delete_tool_records(session_id, keep_turn_ids)
    except Exception as e:
        print(f"[storage] delete_tool_records 失败: {e}", file=sys.stderr)


def delete_session(session_id: str) -> None:
    """删除会话全部记录（json 后端同时删除会话目录）。"""
    try:
        _repo().delete_session(session_id)
    except Exception as e:
        print(f"[storage] delete_session 失败: {e}", file=sys.stderr)
