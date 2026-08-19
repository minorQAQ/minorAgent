"""共享数据库连接与建表工具。

系统定位:
    为 cron 任务存储与普通会话历史存储提供统一的数据库连接、配置读取、
    幂等建表与后端选择入口，避免多处存储后端配置漂移。

配置模型（env_config.json）:
    - 存储数据库: ``STORAGE_DB_*``（host/port/user/password/database/path），
      type 由 ``STORAGE_DB_TYPE`` 或 ``STORAGE_BACKEND`` 决定；缺省回退旧
      ``MYSQL_*``（同一角色，零迁移）。SQLite 文件默认
      ``<HISTORY_ROOT>/sqlite/storage.sqlite``。
    - 工具数据库: ``TOOL_DB_*``，与存储后端**完全隔离**（不回退 MYSQL_*），
      默认 mysql@localhost:3306/root。SQLite 默认 ``<HISTORY_ROOT>/sqlite/tool/``
      目录（目录模式下每个 database 名 = 一个 ``<目录>/<库名>.sqlite`` 文件）。

可扩展性:
    - 新增存储后端时复用 mysql_conn / ensure_tables / get_storage_backend /
      sqlite_conn / ensure_sqlite_tables。
    - ensure_tables 按表名细粒度幂等，cron 表与 session 表互不影响。
    - 向后兼容：旧配置中的 CRON_MYSQL_* 仍可读取（逐步迁移）。
"""
from __future__ import annotations

import os
import re
import sqlite3
import threading
from typing import Any


# ---------- 配置加载 ----------
def load_mysql_config() -> dict[str, Any]:
    """读取 env_config.json 的 MySQL 连接配置（MYSQL_*，存储后端旧键）。

    向后兼容：优先读 MYSQL_*，回退到旧的 CRON_MYSQL_*。
    存储后端新键见 load_storage_db_config；工具数据库见 load_tool_db_config。
    """
    try:
        from agent.core.config_manager import load_env_config
        cfg = load_env_config() or {}
    except Exception:
        cfg = {}
    return {
        "host": str(cfg.get("MYSQL_HOST") or cfg.get("CRON_MYSQL_HOST") or "localhost"),
        "port": int(cfg.get("MYSQL_PORT") or cfg.get("CRON_MYSQL_PORT") or 3306),
        "user": str(cfg.get("MYSQL_USER") or cfg.get("CRON_MYSQL_USER") or "root"),
        "password": str(cfg.get("MYSQL_PASSWORD") or cfg.get("CRON_MYSQL_PASSWORD") or ""),
        "database": str(cfg.get("MYSQL_DATABASE") or cfg.get("CRON_MYSQL_DATABASE") or "agent_history"),
    }


def load_storage_db_config() -> dict[str, Any]:
    """读取存储数据库连接配置（STORAGE_DB_*，缺省回退 MYSQL_*）。

    输出:
        {type, host, port, user, password, database, path}
        type: "mysql" | "sqlite"（由 STORAGE_DB_TYPE 显式指定，或按
              STORAGE_BACKEND 推导：sqlite 后端 → sqlite，否则 mysql）
        path: sqlite 数据库文件路径（仅 sqlite 使用）；缺省
              ``<HISTORY_ROOT>/sqlite/storage.sqlite``。
    """
    try:
        from agent.core.config_manager import load_env_config
        cfg = load_env_config() or {}
    except Exception:
        cfg = {}
    backend = str(cfg.get("STORAGE_BACKEND") or cfg.get("CRON_STORAGE_BACKEND") or "json").lower()
    db_type = str(cfg.get("STORAGE_DB_TYPE") or "").lower()
    if db_type not in ("mysql", "sqlite"):
        db_type = "sqlite" if backend == "sqlite" else "mysql"
    return {
        "type": db_type,
        "host": str(cfg.get("STORAGE_DB_HOST") or cfg.get("MYSQL_HOST")
                    or cfg.get("CRON_MYSQL_HOST") or "localhost"),
        "port": int(cfg.get("STORAGE_DB_PORT") or cfg.get("MYSQL_PORT")
                    or cfg.get("CRON_MYSQL_PORT") or 3306),
        "user": str(cfg.get("STORAGE_DB_USER") or cfg.get("MYSQL_USER")
                    or cfg.get("CRON_MYSQL_USER") or "root"),
        "password": str(cfg.get("STORAGE_DB_PASSWORD") or cfg.get("MYSQL_PASSWORD")
                        or cfg.get("CRON_MYSQL_PASSWORD") or ""),
        "database": str(cfg.get("STORAGE_DB_DATABASE") or cfg.get("MYSQL_DATABASE")
                        or cfg.get("CRON_MYSQL_DATABASE") or "agent_history"),
        "path": str(cfg.get("STORAGE_DB_PATH") or "") or _default_storage_sqlite_path(),
    }


def load_tool_db_config() -> dict[str, Any]:
    """读取工具数据库连接配置（TOOL_DB_*，与存储后端完全隔离，不回退 MYSQL_*）。

    输出:
        {type, host, port, user, password, database, path}
        type: "mysql" | "sqlite"（TOOL_DB_TYPE，缺省 mysql）
        path: sqlite 数据库路径（仅 sqlite 使用）；缺省
              ``<HISTORY_ROOT>/sqlite/tool``（目录：每个库名一个 .sqlite 文件）。
    """
    try:
        from agent.core.config_manager import load_env_config
        cfg = load_env_config() or {}
    except Exception:
        cfg = {}
    db_type = str(cfg.get("TOOL_DB_TYPE") or "").lower()
    if db_type not in ("mysql", "sqlite"):
        db_type = "mysql"
    return {
        "type": db_type,
        "host": str(cfg.get("TOOL_DB_HOST") or "localhost"),
        "port": int(cfg.get("TOOL_DB_PORT") or 3306),
        "user": str(cfg.get("TOOL_DB_USER") or "root"),
        "password": str(cfg.get("TOOL_DB_PASSWORD") or ""),
        "database": str(cfg.get("TOOL_DB_DATABASE") or ""),
        "path": str(cfg.get("TOOL_DB_PATH") or "") or _default_tool_sqlite_dir(),
    }


def _default_storage_sqlite_path() -> str:
    """存储库默认 SQLite 文件：<HISTORY_ROOT>/sqlite/storage.sqlite。"""
    from agent.utils.agent_utils import HISTORY_ROOT
    return os.path.join(HISTORY_ROOT, "sqlite", "storage.sqlite")


def _default_tool_sqlite_dir() -> str:
    """工具库默认 SQLite 目录：<HISTORY_ROOT>/sqlite/tool（每库一个文件）。"""
    from agent.utils.agent_utils import HISTORY_ROOT
    return os.path.join(HISTORY_ROOT, "sqlite", "tool")


# ---------- MySQL 连接 ----------
def mysql_conn(cfg: dict[str, Any] | None = None, database: str | None = None):
    """创建一个 MySQL 连接（DictCursor，手动提交）。调用方负责 close。

    输入:
        cfg: 连接配置（默认读存储数据库配置 load_storage_db_config）。
        database: 覆盖目标库名（默认取 cfg 的 database）。

    系统定位:
        存储仓库（cron / session）获取 MySQL 连接的统一入口；
        工具侧请使用 load_tool_db_config + connect_db。
    """
    import pymysql
    from pymysql.cursors import DictCursor

    cfg = cfg or load_storage_db_config()
    return pymysql.connect(
        host=cfg["host"],
        port=cfg["port"],
        user=cfg["user"],
        password=cfg["password"],
        database=database or cfg["database"],
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
    )


# ---------- SQLite 连接 ----------
def sqlite_conn(path: str) -> sqlite3.Connection:
    """创建一个 SQLite 连接（row_factory=Row，WAL 模式，busy_timeout 5s）。

    输入:
        path: 数据库文件路径（不存在则自动创建；父目录需已存在，
              可用 ensure_sqlite_dir 预先创建）。

    输出:
        sqlite3.Connection。调用方负责 close。
    """
    conn = sqlite3.connect(path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except Exception:
        pass
    return conn


def sqlite_db_path(cfg: dict[str, Any], database: str | None = None) -> str:
    """解析 SQLite 工具库的目标文件路径。

    - cfg["path"] 为目录（或不存在且无 .sqlite 后缀）→ 每个库名一个文件：
      ``<目录>/<库名>.sqlite``（database 必填）。
    - cfg["path"] 为 .sqlite 文件 → 所有操作使用该文件（database 忽略）。
    """
    base = str(cfg.get("path") or "")
    if base.lower().endswith(".sqlite"):
        return base
    db = (database or "").strip()
    if not db:
        raise ValueError("SQLite 目录模式下 database 参数必填（库名 = 文件名）")
    return os.path.join(base, f"{db}.sqlite")


def ensure_sqlite_dir(path: str) -> None:
    """确保 SQLite 路径的父目录存在（幂等）。"""
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)


def connect_db(cfg: dict[str, Any], database: str | None = None):
    """按数据库类型创建连接（统一分发入口）。

    输入:
        cfg: load_tool_db_config() / load_storage_db_config() 的输出。
        database: 目标库名（mysql 覆盖 cfg.database；sqlite 目录模式为文件名）。

    输出:
        pymysql 连接或 sqlite3.Connection。调用方负责 close。
    """
    if cfg.get("type") == "sqlite":
        path = sqlite_db_path(cfg, database)
        ensure_sqlite_dir(path)
        return sqlite_conn(path)
    return mysql_conn(cfg, database)


# ---------- MySQL 建表 ----------
_ensured_tables: set[str] = set()
_database_ensured: bool = False
_ensure_lock = threading.Lock()
_TABLE_NAME_RE = re.compile(
    r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+`?(\w+)`?", re.IGNORECASE
)


def ensure_database() -> None:
    """幂等创建 MySQL 数据库（CREATE DATABASE IF NOT EXISTS）。

    系统定位:
        在 ensure_tables 之前调用，确保目标数据库存在。
        如果数据库不存在，mysql_conn() 会连接失败，导致建表无法执行。
        此函数连接 MySQL 服务器（不指定 database）并创建数据库。
    """
    global _database_ensured
    if _database_ensured:
        return
    with _ensure_lock:
        if _database_ensured:
            return
        import pymysql
        from pymysql.cursors import DictCursor

        cfg = load_storage_db_config()
        try:
            conn = pymysql.connect(
                host=cfg["host"],
                port=cfg["port"],
                user=cfg["user"],
                password=cfg["password"],
                charset="utf8mb4",
                cursorclass=DictCursor,
                autocommit=True,
            )
            try:
                with conn.cursor() as cur:
                    db_name = cfg["database"]
                    cur.execute(
                        f"CREATE DATABASE IF NOT EXISTS `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci"
                    )
                _database_ensured = True
            finally:
                conn.close()
        except Exception as e:
            import sys
            print(f"[db] ensure_database 失败: {e}", file=sys.stderr)


def ensure_tables(ddls: list[str]) -> None:
    """幂等建表：对未建过的表执行 CREATE TABLE IF NOT EXISTS。

    输入:
        ddls: CREATE TABLE IF NOT EXISTS 语句列表。

    输出: 无。

    系统定位:
        cron 与 session 仓库在初始化时调用，传入各自的建表 DDL。

    可扩展性:
        按表名细粒度缓存（_ensured_tables），已建过的表跳过；新表首次执行。
        多线程安全（_ensure_lock）。
    """
    # 先确保数据库存在，否则建表连接会失败
    ensure_database()
    with _ensure_lock:
        pending: list[tuple[str, str]] = []
        for ddl in ddls:
            m = _TABLE_NAME_RE.search(ddl)
            name = m.group(1) if m else ddl
            if name not in _ensured_tables:
                pending.append((name, ddl))
        if not pending:
            return
        conn = mysql_conn()
        try:
            with conn.cursor() as cur:
                for name, ddl in pending:
                    cur.execute(ddl)
                    _ensured_tables.add(name)
            conn.commit()
        finally:
            conn.close()


# ---------- SQLite 建库建表 ----------
def ensure_sqlite_database(path: str) -> None:
    """幂等创建 SQLite 数据库（数据库文件，等价 MySQL 的 CREATE DATABASE IF NOT EXISTS）。

    输入:
        path: 数据库文件路径（父目录自动创建）。

    输出: 无。

    系统定位:
        在 ensure_sqlite_tables 之前调用，确保数据库文件存在；
        不存在时创建空文件，已存在时为 no-op。
    """
    ensure_sqlite_dir(path)
    if not os.path.isfile(path):
        # sqlite3.connect 即创建空数据库文件（SQLite 无 CREATE DATABASE 语句）
        conn = sqlite_conn(path)
        conn.close()


def ensure_sqlite_tables(path: str, ddls: list[str]) -> None:
    """幂等创建 SQLite 表（CREATE TABLE/INDEX IF NOT EXISTS）。

    输入:
        path: 数据库文件路径（不存在则先建库，镜像 MySQL ensure_tables →
              ensure_database 的顺序）。
        ddls: DDL 语句列表（含索引 DDL，全部 IF NOT EXISTS 幂等）。

    输出: 无。

    系统定位:
        SqliteRecordRepository / SqliteTaskConfigRepository 初始化时调用，
        传入各自的建表 DDL。
    """
    # 先确保数据库文件存在，否则建表连接会创建空库后才有表结构
    ensure_sqlite_database(path)
    conn = sqlite_conn(path)
    try:
        with conn:
            for ddl in ddls:
                conn.execute(ddl)
    finally:
        conn.close()


# SQLite 表 DDL（幂等，session / cron 互不影响）。
# JSON 数据以 TEXT 列存储（sqlite 无原生 JSON 类型）；sessions 直接含 extra 列。
_SQLITE_SESSION_TABLE_DDLS = [
    """
    CREATE TABLE IF NOT EXISTS sessions (
        session_id   TEXT PRIMARY KEY,
        created_at   TEXT NOT NULL,
        updated_at   TEXT NOT NULL,
        last_turn_id TEXT DEFAULT '',
        extra        TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS session_messages (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        turn_id    TEXT NOT NULL,
        seq        INTEGER NOT NULL DEFAULT 0,
        message    TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_sess_turn ON session_messages (session_id, turn_id)",
    """
    CREATE TABLE IF NOT EXISTS session_tool_calls (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        turn_id    TEXT NOT NULL,
        tool_calls TEXT NOT NULL,
        meta       TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_sess_tc_turn ON session_tool_calls (session_id, turn_id)",
]

_SQLITE_CRON_TABLE_DDLS = [
    """
    CREATE TABLE IF NOT EXISTS cron_tasks (
        task_id          TEXT PRIMARY KEY,
        name             TEXT NOT NULL,
        prompt           TEXT NOT NULL,
        trigger_type     TEXT NOT NULL,
        cron_expr        TEXT DEFAULT '',
        interval_seconds INTEGER DEFAULT 0,
        run_at           TEXT DEFAULT '',
        enabled          INTEGER DEFAULT 1,
        timeout_seconds  INTEGER DEFAULT 300,
        workspace        TEXT DEFAULT '',
        created_at       TEXT NOT NULL,
        next_run_at      TEXT DEFAULT '',
        last_run_at      TEXT DEFAULT '',
        last_status      TEXT DEFAULT 'pending',
        last_error       TEXT,
        executions       TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS cron_messages (
        id      INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id TEXT NOT NULL,
        turn_id TEXT NOT NULL,
        role    TEXT NOT NULL,
        content TEXT NOT NULL,
        meta    TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_task_turn ON cron_messages (task_id, turn_id)",
    """
    CREATE TABLE IF NOT EXISTS cron_tool_calls (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id    TEXT NOT NULL,
        turn_id    TEXT NOT NULL,
        tool_calls TEXT NOT NULL,
        meta       TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_task_tc_turn ON cron_tool_calls (task_id, turn_id)",
]


def get_storage_backend() -> str:
    """读取 env_config.json 的 STORAGE_BACKEND，默认 json。

    cron 任务与普通会话历史共用此后端开关：mysql / sqlite 时两者都入库。
    向后兼容：优先读 STORAGE_BACKEND，回退到旧的 CRON_STORAGE_BACKEND。
    """
    try:
        from agent.core.config_manager import load_env_config
        cfg = load_env_config() or {}
        return str(cfg.get("STORAGE_BACKEND") or cfg.get("CRON_STORAGE_BACKEND") or "json").lower()
    except Exception:
        return "json"
