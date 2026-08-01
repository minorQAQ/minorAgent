"""定时任务存储抽象层。

系统定位:
    为 scheduler / API / cron_manager 工具提供统一的任务与记录读写接口。
    支持两种后端：JSON 文件（history/cron/{task_id}/cron_task.json）与
    MySQL（pymysql，表 cron_tasks / cron_messages / cron_tool_calls）。

可扩展性:
    - get_task_repository() / get_record_repository() 依据 env_config.json 的
      STORAGE_BACKEND（默认 "json"）选择实现，两种后端均完整支持增删改查。
    - 多模态附件地址在读取时解析为绝对地址（相对 CRON_ROOT），
      保证数据库迁移到不同机器后仍可定位文件。
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Protocol

from agent.cron.models import CronTask, ExecutionLog, now_iso
from agent.utils.agent_utils import HISTORY_ROOT
from agent.core.db import (
    mysql_conn,
    ensure_tables,
    get_storage_backend,
)

# 定时任务根目录：history/cron
CRON_ROOT = os.path.join(HISTORY_ROOT, "cron")
os.makedirs(CRON_ROOT, exist_ok=True)


# ---------- Protocol 定义 ----------
class CronTaskRepository(Protocol):
    """任务配置与状态的读写接口。"""

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


class CronRecordRepository(Protocol):
    """任务执行记录（消息与工具调用）的读取接口。"""

    def load_messages(self, task_id: str) -> list[dict]: ...
    def list_turns(self, task_id: str) -> list[dict]: ...
    def get_tool_calls(self, task_id: str, turn_id: str) -> list[dict]: ...


# ---------- JSON 实现 ----------
class JsonCronTaskRepository:
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
            # 成功类状态清空错误描述
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


class JsonCronRecordRepository:
    """基于 JSON 文件的执行记录仓库。

    复用 session 同构的 turn_*.json / tool_*.json（由 runner 写入）。
    读取时将附件 relpath 解析为绝对地址（相对 CRON_ROOT），保证可移植性。
    """

    def _task_dir(self, task_id: str) -> str:
        return os.path.join(CRON_ROOT, task_id)

    def load_messages(self, task_id: str) -> list[dict]:
        """加载该任务所有 turn 的扁平消息列表，附件路径解析为绝对地址。"""
        from agent.utils.agent_utils import TURN_JSON_PREFIX

        sess_dir = self._task_dir(task_id)
        if not os.path.isdir(sess_dir):
            return []
        all_msgs: list[dict] = []
        turn_files = sorted(
            f for f in os.listdir(sess_dir)
            if f.startswith(TURN_JSON_PREFIX) and f.endswith(".json")
        )
        for tf in turn_files:
            tp = os.path.join(sess_dir, tf)
            if not os.path.isfile(tp):
                continue
            try:
                with open(tp, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for msg in data.get("messages", []):
                    all_msgs.append(self._resolve_abs_paths(msg, task_id))
            except (json.JSONDecodeError, OSError):
                pass
        return all_msgs

    def list_turns(self, task_id: str) -> list[dict]:
        """列出该任务所有 turn 的元信息（turn_id + messages 概要）。"""
        from agent.utils.agent_utils import TURN_JSON_PREFIX

        sess_dir = self._task_dir(task_id)
        if not os.path.isdir(sess_dir):
            return []
        turns: list[dict] = []
        turn_files = sorted(
            f for f in os.listdir(sess_dir)
            if f.startswith(TURN_JSON_PREFIX) and f.endswith(".json")
        )
        for tf in turn_files:
            tp = os.path.join(sess_dir, tf)
            if not os.path.isfile(tp):
                continue
            try:
                with open(tp, "r", encoding="utf-8") as f:
                    data = json.load(f)
                turns.append({
                    "turn_id": data.get("turn_id", ""),
                    "messages_count": len(data.get("messages", [])),
                })
            except (json.JSONDecodeError, OSError):
                pass
        return turns

    def get_tool_calls(self, task_id: str, turn_id: str) -> list[dict]:
        """读取指定 turn 的工具调用记录。"""
        tool_path = os.path.join(self._task_dir(task_id), f"tool_{turn_id}.json")
        if not os.path.isfile(tool_path):
            return []
        try:
            with open(tool_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("tool_calls", []) or []
        except (json.JSONDecodeError, OSError):
            return []

    def _resolve_abs_paths(self, msg: dict, task_id: str) -> dict:
        """附件路径解析委托给模块级 _resolve_msg_paths（JSON/MySQL 共用）。"""
        return _resolve_msg_paths(msg, task_id)


# ---------- MySQL 实现（pymysql） ----------
# 连接 / 配置 / 后端选择已抽取至 agent.core.db，此处保留别名供模块内部调用
_mysql_conn = mysql_conn
_get_backend = get_storage_backend

# cron 三表 DDL（由 ensure_tables 幂等建表）
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


def _ensure_mysql_tables() -> None:
    """幂等建 cron 三表（委托共享 ensure_tables）。"""
    ensure_tables(_CRON_TABLE_DDLS)


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


class MysqlCronTaskRepository:
    """基于 MySQL（pymysql）的任务仓库。

    表: cron_tasks。trigger 拆为 trigger_type/cron_expr/interval_seconds/run_at 列，
    executions 存为 JSON 列。
    """

    def __init__(self) -> None:
        _ensure_mysql_tables()

    def list_tasks(self) -> list[CronTask]:
        conn = _mysql_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM cron_tasks ORDER BY created_at DESC")
                rows = cur.fetchall() or []
            return [_row_to_task(r) for r in rows]
        finally:
            conn.close()

    def get_task(self, task_id: str) -> CronTask | None:
        conn = _mysql_conn()
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
        conn = _mysql_conn()
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
        conn = _mysql_conn()
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
        # next_run_at 显式更新（空串也写，表示不再运行）
        sets.append("next_run_at=%s")
        vals.append(next_run_at)
        vals.append(task_id)
        conn = _mysql_conn()
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
        conn = _mysql_conn()
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


class MysqlCronRecordRepository:
    """基于 MySQL（pymysql）的执行记录仓库。

    表: cron_messages / cron_tool_calls。
    附件路径统一存相对 CRON_ROOT 的 relpath，读取时按本机 CRON_ROOT 解析为绝对地址。
    写入由 runner 执行后调用 persist_turn_records 触发（见模块底部）。
    """

    def __init__(self) -> None:
        _ensure_mysql_tables()

    @staticmethod
    def _parse_json_col(val: Any) -> Any:
        if isinstance(val, str):
            try:
                return json.loads(val)
            except (json.JSONDecodeError, TypeError):
                return None
        if isinstance(val, (bytes, bytearray)):
            try:
                return json.loads(val.decode("utf-8"))
            except Exception:
                return None
        return val

    def load_messages(self, task_id: str) -> list[dict]:
        conn = _mysql_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT turn_id, role, content, meta FROM cron_messages "
                    "WHERE task_id=%s ORDER BY id",
                    (task_id,),
                )
                rows = cur.fetchall() or []
            msgs: list[dict] = []
            for r in rows:
                content = self._parse_json_col(r.get("content")) or ""
                meta = self._parse_json_col(r.get("meta"))
                msg: dict[str, Any] = {"role": r.get("role", "user"), "content": content}
                if meta:
                    msg["meta"] = meta
                msgs.append(_resolve_msg_paths(msg, task_id))
            return msgs
        finally:
            conn.close()

    def list_turns(self, task_id: str) -> list[dict]:
        conn = _mysql_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT turn_id, COUNT(*) AS cnt FROM cron_messages "
                    "WHERE task_id=%s GROUP BY turn_id ORDER BY MIN(id)",
                    (task_id,),
                )
                rows = cur.fetchall() or []
            return [{"turn_id": r.get("turn_id", ""), "messages_count": int(r.get("cnt", 0))} for r in rows]
        finally:
            conn.close()

    def get_tool_calls(self, task_id: str, turn_id: str) -> list[dict]:
        conn = _mysql_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT tool_calls FROM cron_tool_calls "
                    "WHERE task_id=%s AND turn_id=%s ORDER BY id",
                    (task_id, turn_id),
                )
                rows = cur.fetchall() or []
            out: list[dict] = []
            for r in rows:
                tc = self._parse_json_col(r.get("tool_calls"))
                if isinstance(tc, list):
                    out.extend(tc)
            return out
        finally:
            conn.close()

    def save_turn(self, task_id: str, turn_id: str, messages: list[dict]) -> None:
        """写入一个 turn 的消息（幂等：先删同 turn 旧记录）。"""
        conn = _mysql_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM cron_messages WHERE task_id=%s AND turn_id=%s",
                    (task_id, turn_id),
                )
                for msg in messages:
                    content = msg.get("content")
                    meta = msg.get("meta")
                    cur.execute(
                        "INSERT INTO cron_messages (task_id, turn_id, role, content, meta) "
                        "VALUES (%s,%s,%s,%s,%s)",
                        (
                            task_id, turn_id, msg.get("role", "user"),
                            json.dumps(content, ensure_ascii=False),
                            json.dumps(meta, ensure_ascii=False) if meta is not None else None,
                        ),
                    )
            conn.commit()
        finally:
            conn.close()

    def save_tool_calls(self, task_id: str, turn_id: str, tool_calls: list[dict]) -> None:
        """写入一个 turn 的工具调用记录（幂等）。"""
        conn = _mysql_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM cron_tool_calls WHERE task_id=%s AND turn_id=%s",
                    (task_id, turn_id),
                )
                cur.execute(
                    "INSERT INTO cron_tool_calls (task_id, turn_id, tool_calls) VALUES (%s,%s,%s)",
                    (task_id, turn_id, json.dumps(tool_calls, ensure_ascii=False)),
                )
            conn.commit()
        finally:
            conn.close()


# ---------- 附件路径解析（JSON / MySQL 共用） ----------
def _resolve_msg_paths(msg: dict, task_id: str) -> dict:
    """将消息 content 中的相对附件路径解析为绝对地址（相对 CRON_ROOT）。

    runner 写入 / 数据库存储的附件路径均为相对 CRON_ROOT 的 relpath，
    此处返回前端/序列化前还原为绝对路径，供文件读取。
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


# ---------- 工厂 ----------
_backend_cache: dict[str, Any] = {}


def get_task_repository() -> CronTaskRepository:
    """获取任务仓库实例（按配置选择 json / mysql）。"""
    backend = _get_backend()
    if backend == "mysql":
        if "task_mysql" not in _backend_cache:
            _backend_cache["task_mysql"] = MysqlCronTaskRepository()
        return _backend_cache["task_mysql"]  # type: ignore[return-value]
    if "task_json" not in _backend_cache:
        _backend_cache["task_json"] = JsonCronTaskRepository()
    return _backend_cache["task_json"]  # type: ignore[return-value]


def get_record_repository() -> CronRecordRepository:
    """获取执行记录仓库实例（按配置选择 json / mysql）。"""
    backend = _get_backend()
    if backend == "mysql":
        if "record_mysql" not in _backend_cache:
            _backend_cache["record_mysql"] = MysqlCronRecordRepository()
        return _backend_cache["record_mysql"]  # type: ignore[return-value]
    if "record_json" not in _backend_cache:
        _backend_cache["record_json"] = JsonCronRecordRepository()
    return _backend_cache["record_json"]  # type: ignore[return-value]


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


def persist_turn_records(task_id: str, turn_id: str) -> None:
    """将 runner 写入的 turn/tool 文件记录导入存储后端。

    - JSON 后端：文件即存储，无需操作。
    - MySQL 后端：读取 history/cron/{task_id}/turn_*.json 与 tool_*.json，
      将附件路径转为相对 CRON_ROOT 的 relpath 后写入 cron_messages / cron_tool_calls。

    由 runner.main() 在执行完成后调用。失败仅打印日志，不影响任务状态回传。
    """
    if _get_backend() != "mysql" or not task_id or not turn_id:
        return
    try:
        from agent.utils.agent_utils import TURN_JSON_PREFIX

        sess_dir = os.path.join(CRON_ROOT, task_id)
        # 读取 turn 消息
        turn_path = os.path.join(sess_dir, f"{TURN_JSON_PREFIX}{turn_id}.json")
        messages: list[dict] = []
        if os.path.isfile(turn_path):
            with open(turn_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            messages = data.get("messages", []) or []
        # 读取工具调用
        tool_path = os.path.join(sess_dir, f"tool_{turn_id}.json")
        tool_calls: list[dict] = []
        if os.path.isfile(tool_path):
            with open(tool_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            tool_calls = data.get("tool_calls", []) or []
        # 附件路径转相对（数据库存 relpath，保证可移植性）
        messages = [_to_rel_paths(m, task_id) for m in messages]
        repo = get_record_repository()
        if hasattr(repo, "save_turn"):
            repo.save_turn(task_id, turn_id, messages)  # type: ignore[attr-defined]
        if hasattr(repo, "save_tool_calls"):
            repo.save_tool_calls(task_id, turn_id, tool_calls)  # type: ignore[attr-defined]
    except Exception as e:
        import sys
        print(f"[cron.storage] persist_turn_records 失败: {e}", file=sys.stderr)


# ---------- MySQL 表结构参考（已由 _ensure_mysql_tables 幂等建表实现） ----------
"""
CREATE TABLE cron_tasks (
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
);

CREATE TABLE cron_messages (
    id      BIGINT AUTO_INCREMENT PRIMARY KEY,
    task_id VARCHAR(64) NOT NULL,
    turn_id VARCHAR(64) NOT NULL,
    role    VARCHAR(16) NOT NULL,
    content JSON NOT NULL,
    meta    JSON DEFAULT NULL,
    INDEX idx_task_turn (task_id, turn_id)
);

CREATE TABLE cron_tool_calls (
    id         BIGINT AUTO_INCREMENT PRIMARY KEY,
    task_id    VARCHAR(64) NOT NULL,
    turn_id    VARCHAR(64) NOT NULL,
    tool_calls JSON NOT NULL,
    INDEX idx_task_turn (task_id, turn_id)
);

-- 附件路径统一存储相对 CRON_ROOT 的 relpath，读取时按本机 CRON_ROOT 拼绝对路径。
"""
