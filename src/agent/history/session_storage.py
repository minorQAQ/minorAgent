"""会话历史存储转发层（统一实现在 agent.core.storage）。

本模块保持既有导入路径（``from agent.history import session_storage``），
实际实现与 cron 存储统一在 ``agent.core.storage``：
    - 消费方调用本模块的便捷函数即可，无需感知后端选择（json / mysql）。
    - 新增存储后端只需在 ``agent.core.storage`` 实现 Protocol 并注册工厂。
"""
from agent.core.storage import (
    # Protocol 与实现
    ConversationRecordRepository,
    JsonRecordRepository,
    MysqlRecordRepository,
    # 便捷函数（后端无关）
    save_turn,
    load_messages,
    load_turn_messages,
    list_turn_ids,
    save_tool_calls,
    get_turn_record,
    get_latest_turn_record,
    list_turn_records,
    persist_live_records,
    load_session_extra,
    save_session_extra,
    list_session_ids,
    get_last_turn_id,
    delete_turns_after,
    delete_tool_records,
    delete_session,
    # 作用域与工厂
    set_storage_scope,
    get_storage_scope,
    get_record_repository,
)
