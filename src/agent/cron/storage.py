"""定时任务存储转发层（统一实现在 agent.core.storage）。

本模块保持既有导入路径（scheduler / cron_manager / server / runner），
实际实现与普通会话存储统一在 ``agent.core.storage``：
    - ``get_record_repository()`` 固定返回 cron 作用域记录仓库
      （cron_messages/cron_tool_calls 表，或 history/cron 下的 JSON 文件）。
    - 新增存储后端只需在 ``agent.core.storage`` 实现 Protocol 并注册工厂。
"""
from agent.core.storage import (
    CRON_ROOT,
    TaskConfigRepository,
    ConversationRecordRepository,
    get_task_repository,
    new_task_id,
    set_storage_scope,
    get_storage_scope,
    get_record_repository as _get_core_record_repository,
)


def get_record_repository() -> ConversationRecordRepository:
    """获取 cron 作用域的执行记录仓库实例（按 STORAGE_BACKEND 选择 json / mysql）。"""
    return _get_core_record_repository(scope="cron")  # type: ignore[return-value]
