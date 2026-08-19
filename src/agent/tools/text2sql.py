"""text2sql 数据库操作工具。

系统定位:
    让 Agent 用自然语言/SQL 操作数据库：查看库结构、查看表结构、查询表内容（查），
    以及对库内容做增删改（INSERT/UPDATE/DELETE/DDL）。

    连接使用设置中的**工具数据库配置**（TOOL_DB_*，MySQL 或 SQLite），
    与存储后端配置完全隔离。MySQL 的 database 必须由调用方显式指定
    （用户需告知 Agent 要操作的数据库名），避免误操作系统存储库（agent_history）；
    SQLite 目录模式下库名 = 文件名（<工具库目录>/<库名>.sqlite），
    建库即幂等创建该文件。

权限策略（见 tool_config.json）:
    - action=list_tables / describe / query  → 查类，直接执行（auto_execute_rules 升级为 direct）
    - action=execute（增删改/DDL）            → 需用户确认（permission=confirm）

    图标: src/web/image/SQL.svg
"""
from __future__ import annotations

import json
import re
from typing import Any, Literal

from langchain.tools import BaseTool
from pydantic import BaseModel, Field


# 合法表名（防 DESCRIBE 注入）
_TABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# 合法数据库名（防注入）
_DB_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# 查询行数硬上限，防止单次返回过大
_MAX_ROWS = 1000


class Text2SQLInput(BaseModel):
    action: Literal["list_tables", "describe", "query", "execute", "create_database", "create_table"] = Field(
        ...,
        description="操作类型：list_tables=列出当前库所有表；describe=查看指定表结构；"
                    "query=执行只读 SELECT 查询；execute=执行增删改/DDL（INSERT/UPDATE/DELETE/CREATE 等）；"
                    "create_database=创建数据库（不存在则建，幂等，连服务器不指定库）；"
                    "create_table=建表（先确保库存在再执行建表 DDL）。",
    )
    database: str = Field(
        ...,
        description="目标数据库名（必填）。用户需告知要操作的数据库名，"
                    "Agent 不能自行猜测或使用默认库。连接同一 MySQL 服务器上的指定库。",
    )
    sql: str | None = Field(
        default=None,
        description="SQL 语句。query/execute 时必填；list_tables/describe 时忽略。",
    )
    table: str | None = Field(
        default=None,
        description="表名。describe 时必填。",
    )
    limit: int = Field(
        default=100,
        description="query 时返回的最大行数（上限 1000）。",
    )


class Text2SQLTool(BaseTool):
    """数据库操作工具：查（结构/表内容）直接执行，增删改需确认。"""

    args_schema: type[BaseModel] = Text2SQLInput
    name: str = "text2sql"
    description: str = (
        "数据库操作工具（text2sql）。支持查看数据库结构、查询表内容、对数据库内容做增删改，以及建库建表。\n"
        "适用场景：用户希望用自然语言查询/操作数据库，或 Agent 需要读取/修改数据库内容，或需创建新库/新表。\n"
        "连接使用设置中的工具数据库配置（MySQL 或 SQLite，与存储库隔离）；SQLite 目录模式下每个库名对应一个 .sqlite 文件。\n"
        "参数说明：\n"
        "- action: list_tables（列出所有表）/ describe（查看表结构）/ query（只读查询）/ execute（增删改/DDL）/ create_database（建库，幂等）/ create_table（建表，先确保库存在）\n"
        "- database: 目标数据库名（必填，用户需告知要操作的数据库）\n"
        "- sql: query/execute/create_table 时的 SQL 语句\n"
        "- table: describe 时的表名\n"
        "- limit: query 返回最大行数（默认 100，上限 1000）\n"
        "权限：list_tables/describe/query/create_database 为查类或幂等安全操作直接执行；execute/create_table 需用户确认。\n"
        "调用示例：\n"
        '- 列出所有表: {"action": "list_tables", "database": "my_agent_data"}\n'
        '- 查看表结构: {"action": "describe", "database": "my_agent_data", "table": "users"}\n'
        '- 查询数据: {"action": "query", "database": "my_agent_data", "sql": "SELECT * FROM users LIMIT 10"}\n'
        '- 新增数据: {"action": "execute", "database": "my_agent_data", "sql": "INSERT INTO users (name) VALUES (\'test\')"}\n'
        '- 建库: {"action": "create_database", "database": "my_agent_data"}\n'
        '- 建表: {"action": "create_table", "database": "my_agent_data", "sql": "CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT)"}\n'
    )

    def _run(
        self,
        action: str = "list_tables",
        database: str | None = None,
        sql: str | None = None,
        table: str | None = None,
        limit: int = 100,
        **kwargs: Any,
    ) -> str:
        try:
            # database 必填校验
            if not database or not database.strip():
                return json.dumps(
                    {"error": "database 参数必填。请用户提供要操作的数据库名。"},
                    ensure_ascii=False,
                )
            db_name = database.strip()
            if not _DB_NAME_RE.match(db_name):
                return json.dumps({"error": f"非法数据库名: {db_name}"}, ensure_ascii=False)

            if action == "list_tables":
                return self._list_tables(db_name)
            if action == "describe":
                return self._describe(table, db_name)
            if action == "query":
                return self._query(sql, db_name, limit)
            if action == "execute":
                return self._execute(sql, db_name)
            if action == "create_database":
                return self._create_database(db_name)
            if action == "create_table":
                return self._create_table(sql, db_name)
            return json.dumps({"error": f"未知 action: {action}"}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": f"text2sql 执行失败: {str(e)}"}, ensure_ascii=False)

    # ---------- 连接 ----------
    @staticmethod
    def _tool_cfg() -> dict:
        """读取工具数据库配置（TOOL_DB_*，与存储后端完全隔离）。"""
        from agent.core.db import load_tool_db_config
        return load_tool_db_config()

    @classmethod
    def _db_type(cls) -> str:
        """当前工具数据库类型："mysql" | "sqlite"。"""
        return cls._tool_cfg().get("type", "mysql")

    @staticmethod
    def _connect(database: str):
        """创建数据库连接（按工具数据库配置分发 mysql/sqlite）。

        - mysql: 复用 TOOL_DB_* 的 host/port/user/password，database 由调用方指定；
        - sqlite: 目录模式库名 = 文件名（<目录>/<库名>.sqlite），单文件模式用配置路径。

        调用方负责 close。
        """
        from agent.core.db import connect_db

        cfg = Text2SQLTool._tool_cfg()
        # database 由调用方指定，不使用配置中的默认库
        return connect_db(cfg, database)

    # ---------- 查类 ----------
    def _list_tables(self, database: str) -> str:
        conn = self._connect(database)
        try:
            if self._db_type() == "sqlite":
                cur = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%' ORDER BY name"
                )
                rows = [dict(r) for r in cur.fetchall()]
                names = [str(r.get("name", "")) for r in rows]
                db_name = database
            else:
                with conn.cursor() as cur:
                    cur.execute("SHOW TABLES")
                    rows = cur.fetchall()
                    cur.execute("SELECT DATABASE() AS db")
                    db_name = (cur.fetchone() or {}).get("db") or ""
                names: list[str] = []
                for r in rows:
                    for v in r.values():
                        names.append(str(v))
            return json.dumps(
                {"action": "list_tables", "database": db_name, "tables": names, "count": len(names)},
                ensure_ascii=False,
                default=str,
            )
        finally:
            conn.close()

    def _describe(self, table: str | None, database: str) -> str:
        if not table:
            return json.dumps({"error": "describe 操作需提供 table"}, ensure_ascii=False)
        if not _TABLE_NAME_RE.match(str(table)):
            return json.dumps({"error": f"非法表名: {table}"}, ensure_ascii=False)
        conn = self._connect(database)
        try:
            if self._db_type() == "sqlite":
                # PRAGMA table_info → 与 SHOW FULL COLUMNS 同构的列结构
                cur = conn.execute(f"PRAGMA table_info(`{table}`)")
                cols = []
                for r in cur.fetchall():
                    d = dict(r)
                    cols.append({
                        "Field": d.get("name", ""),
                        "Type": d.get("type", ""),
                        "Null": "NO" if d.get("notnull") else "YES",
                        "Key": "PRI" if d.get("pk") else "",
                        "Default": d.get("dflt_value"),
                        "Extra": "",
                    })
            else:
                with conn.cursor() as cur:
                    cur.execute(f"SHOW FULL COLUMNS FROM `{table}`")
                    cols = cur.fetchall()
            return json.dumps(
                {"action": "describe", "database": database, "table": table, "columns": cols, "count": len(cols)},
                ensure_ascii=False,
                default=str,
            )
        finally:
            conn.close()

    def _query(self, sql: str | None, database: str, limit: int) -> str:
        if not sql or not sql.strip():
            return json.dumps({"error": "query 操作需提供 sql"}, ensure_ascii=False)
        stmt = sql.strip()
        # 仅允许只读语句，防止通过 query 绕过确认执行写操作
        if not _is_readonly_sql(stmt):
            return json.dumps(
                {"error": "query 仅允许 SELECT/WITH/SHOW/DESCRIBE/EXPLAIN；写操作请用 action=execute"},
                ensure_ascii=False,
            )
        row_limit = max(1, min(int(limit or 100), _MAX_ROWS))
        conn = self._connect(database)
        try:
            if self._db_type() == "sqlite":
                rows = self._query_sqlite(conn, stmt, row_limit)
            else:
                with conn.cursor() as cur:
                    cur.execute(stmt)
                    rows = cur.fetchmany(row_limit)
            columns = list(rows[0].keys()) if rows else []
            return json.dumps(
                {
                    "action": "query",
                    "database": database,
                    "columns": columns,
                    "row_count": len(rows),
                    "limit": row_limit,
                    "rows": rows,
                },
                ensure_ascii=False,
                default=str,
            )
        finally:
            conn.close()

    @staticmethod
    def _query_sqlite(conn: Any, stmt: str, row_limit: int) -> list[dict]:
        """SQLite 只读查询：SHOW TABLES / DESCRIBE / DESC 翻译为 sqlite 等价语法。"""
        up = stmt.lstrip("(").lstrip().upper()
        if up.startswith("SHOW TABLES"):
            cur = conn.execute(
                "SELECT name AS `Tables_in_db` FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
            return [dict(r) for r in cur.fetchmany(row_limit)]
        if up.startswith(("DESCRIBE", "DESC")):
            parts = stmt.split()
            t = parts[1].strip('`"[]') if len(parts) > 1 else ""
            if not t:
                return []
            cur = conn.execute(f"PRAGMA table_info(`{t}`)")
            cols = []
            for r in cur.fetchall():
                d = dict(r)
                cols.append({
                    "Field": d.get("name", ""),
                    "Type": d.get("type", ""),
                    "Null": "NO" if d.get("notnull") else "YES",
                    "Key": "PRI" if d.get("pk") else "",
                    "Default": d.get("dflt_value"),
                    "Extra": "",
                })
            return cols[:row_limit]
        cur = conn.execute(stmt)
        return [dict(r) for r in cur.fetchmany(row_limit)]

    # ---------- 增删改类 ----------
    def _execute(self, sql: str | None, database: str) -> str:
        if not sql or not sql.strip():
            return json.dumps({"error": "execute 操作需提供 sql"}, ensure_ascii=False)
        conn = self._connect(database)
        try:
            if self._db_type() == "sqlite":
                cur = conn.execute(sql.strip())
            else:
                with conn.cursor() as cur:
                    cur.execute(sql.strip())
            affected = cur.rowcount
            last_id = cur.lastrowid
            conn.commit()
            return json.dumps(
                {
                    "action": "execute",
                    "database": database,
                    "success": True,
                    "affected_rows": affected,
                    "last_insert_id": last_id,
                },
                ensure_ascii=False,
                default=str,
            )
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            conn.close()

    # ---------- 建库建表 ----------
    def _create_database(self, database: str) -> str:
        """幂等创建数据库。

        - mysql: CREATE DATABASE IF NOT EXISTS（连服务器，不指定 database）；
        - sqlite: 库 = 文件，幂等创建（建父目录 + 空文件），无 CREATE DATABASE 语句。
        """
        if self._db_type() == "sqlite":
            from agent.core.db import load_tool_db_config, sqlite_db_path, ensure_sqlite_database
            try:
                cfg = load_tool_db_config()
                path = sqlite_db_path(cfg, database)
                ensure_sqlite_database(path)
            except Exception as e:
                return json.dumps(
                    {"error": f"create_database 失败: {str(e)}", "database": database},
                    ensure_ascii=False,
                )
            return json.dumps(
                {"action": "create_database", "database": database, "success": True,
                 "note": "sqlite 库即文件，已幂等创建"},
                ensure_ascii=False,
            )
        import pymysql
        from pymysql.cursors import DictCursor
        from agent.core.db import load_tool_db_config

        cfg = load_tool_db_config()
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
                    cur.execute(
                        f"CREATE DATABASE IF NOT EXISTS `{database}` "
                        f"CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci"
                    )
            finally:
                conn.close()
        except Exception as e:
            return json.dumps(
                {"error": f"create_database 失败: {str(e)}", "database": database},
                ensure_ascii=False,
            )
        return json.dumps(
            {"action": "create_database", "database": database, "success": True},
            ensure_ascii=False,
        )

    def _create_table(self, sql: str | None, database: str) -> str:
        """建表：先确保库存在（幂等建库），再连接目标库执行建表 DDL。"""
        if not sql or not sql.strip():
            return json.dumps({"error": "create_table 操作需提供 sql（建表 DDL）"}, ensure_ascii=False)
        # 先确保库存在（幂等）；若建库失败直接返回错误
        db_result = self._create_database(database)
        try:
            r = json.loads(db_result)
            if not r.get("success"):
                return db_result
        except Exception:
            pass
        conn = self._connect(database)
        try:
            if self._db_type() == "sqlite":
                conn.execute(sql.strip())
            else:
                with conn.cursor() as cur:
                    cur.execute(sql.strip())
            conn.commit()
            return json.dumps(
                {"action": "create_table", "database": database, "success": True, "ddl": sql.strip()},
                ensure_ascii=False,
                default=str,
            )
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            return json.dumps(
                {"error": f"create_table 失败: {str(e)}", "database": database},
                ensure_ascii=False,
            )
        finally:
            conn.close()


def _is_readonly_sql(stmt: str) -> bool:
    """判断 SQL 是否为只读语句（防 query 通道执行写操作）。"""
    s = stmt.lstrip("(").lstrip().upper()
    return s.startswith(("SELECT", "WITH", "SHOW", "DESCRIBE", "DESC", "EXPLAIN"))
