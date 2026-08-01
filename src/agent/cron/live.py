"""定时任务实时流中继（主进程侧）。

系统定位:
    子进程（agent.cron.runner）无法直接与前端建立 SSE，故将 live 快照经
    HTTP POST 回传主进程，由本模块按 task_id 分发给前端 SSE 订阅者。

    快照格式与 tool_call_recorder._build_live_snapshot 一致：
    {tool_calls, reflections, started_at}，前端复用 toolcalls.js 渲染。
"""
from __future__ import annotations

import queue as _queue_module
import threading
from typing import Any

# per-task 订阅者队列列表
_cron_live_subs: dict[str, list[_queue_module.Queue]] = {}
_subscribers_lock = threading.Lock()


def subscribe(task_id: str) -> _queue_module.Queue:
    """订阅指定任务的实时更新，返回一个 Queue。"""
    q: _queue_module.Queue = _queue_module.Queue(maxsize=64)
    with _subscribers_lock:
        if task_id not in _cron_live_subs:
            _cron_live_subs[task_id] = []
        _cron_live_subs[task_id].append(q)
    return q


def unsubscribe(task_id: str, q: _queue_module.Queue) -> None:
    """取消订阅。"""
    with _subscribers_lock:
        subs = _cron_live_subs.get(task_id, [])
        if q in subs:
            subs.remove(q)
        if not subs:
            _cron_live_subs.pop(task_id, None)


def push_snapshot(task_id: str, snapshot: dict[str, Any]) -> None:
    """将子进程回传的 live 快照推送给该任务的所有订阅者。"""
    with _subscribers_lock:
        subs = list(_cron_live_subs.get(task_id, []))
    if not subs:
        return
    for q in subs:
        try:
            q.put_nowait({"type": "update", "data": snapshot})
        except _queue_module.Full:
            try:
                q.get_nowait()
                q.put_nowait({"type": "update", "data": snapshot})
            except Exception:
                pass


def push_finished(task_id: str, payload: dict[str, Any]) -> None:
    """推送任务结束信号，前端据此重载消息并刷新状态。"""
    with _subscribers_lock:
        subs = list(_cron_live_subs.get(task_id, []))
    if not subs:
        return
    for q in subs:
        try:
            q.put_nowait({"type": "finished", "data": payload})
        except _queue_module.Full:
            try:
                q.get_nowait()
                q.put_nowait({"type": "finished", "data": payload})
            except Exception:
                pass
