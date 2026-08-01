"""共享数据库连接与建表工具。

系统定位:
    为 cron 任务存储与普通会话历史存储提供统一的 MySQL 连接、配置读取、
    幂等建表与后端选择入口，避免两处存储后端配置漂移。

可扩展性:
    - 新增存储后端时复用 mysql_conn / ensure_tables / get_storage_backend。
    - ensure_tables 按表名细粒度幂等，cron 表与 session 表互不影响。
    - 连接配置统一读 MYSQL_*（cron 与 session 共用同一数据库）。
    - 向后兼容：旧配置中的 CRON_MYSQL_* 仍可读取（逐步迁移）。
"""
from __future__ import annotations

import re
import threading
from typing import Any


def load_mysql_config() -> dict[str, Any]:
    """从 env_config.json 读取 MySQL 连接配置（MYSQL_*，cron 与 session 共用）。

    向后兼容：优先读 MYSQL_*，回退到旧的 CRON_MYSQL_*。
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


def mysql_conn():
    """创建一个 MySQL 连接（DictCursor，手动提交）。调用方负责 close。

    系统定位:
        所有 MySQL 仓库（cron / session）获取连接的统一入口。
    """
    import pymysql
    from pymysql.cursors import DictCursor

    cfg = load_mysql_config()
    return pymysql.connect(
        host=cfg["host"],
        port=cfg["port"],
        user=cfg["user"],
        password=cfg["password"],
        database=cfg["database"],
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
    )


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

        cfg = load_mysql_config()
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


def get_storage_backend() -> str:
    """读取 env_config.json 的 STORAGE_BACKEND，默认 json。

    cron 任务与普通会话历史共用此后端开关：mysql 时两者都入库。
    向后兼容：优先读 STORAGE_BACKEND，回退到旧的 CRON_STORAGE_BACKEND。
    """
    try:
        from agent.core.config_manager import load_env_config
        cfg = load_env_config() or {}
        return str(cfg.get("STORAGE_BACKEND") or cfg.get("CRON_STORAGE_BACKEND") or "json").lower()
    except Exception:
        return "json"
