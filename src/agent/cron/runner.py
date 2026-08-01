"""定时任务子进程入口。

系统定位:
    被 CronScheduler 通过 ``python -m agent.cron.runner`` 拉起的独立进程，
    无人值守地执行单个定时任务。与主进程 Chat 完全隔离，可多任务并行。

执行流程:
    1. 重定向 SESSIONS_ROOT / TOOL_CALLING_ROOT / ui_session.SESSIONS_ROOT 到
       history/cron/{task_id}/，使所有 turn/tool/token 文件写入 cron 目录。
    2. 构建主 AgentRuntime（复用 build_all_agent_runtimes）。
    3. 起后台线程订阅本进程 tool_call_recorder.subscribe_live(task_id)，
       将快照经 HTTP POST 转发到主进程 /api/cron/internal/live。
    4. 以 agent_mode="cron" 调用 execute_agent，工作线程超时则强制结束。
    5. POST /api/cron/internal/finished 回传最终状态后退出。

可扩展性:
    - 超时控制当前采用工作线程 + 进程退出；未来可改 asyncio + 信号。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any


# 主进程回传地址（uvicorn 单 worker，固定端口）
_MAIN_HOST = "127.0.0.1"
_MAIN_PORT = 8765
_LIVE_URL = f"http://{_MAIN_HOST}:{_MAIN_PORT}/api/cron/internal/live"
_FINISHED_URL = f"http://{_MAIN_HOST}:{_MAIN_PORT}/api/cron/internal/finished"


def _redirect_storage_roots(task_id: str) -> str:
    """将本进程的会话存储根目录重定向到 history/cron/{task_id}/。

    必须在构建 AgentRuntime 与调用 execute_agent 之前执行。三个模块全局均
    被显式覆盖（函数在调用时读取模块全局，故覆盖后即生效）：
      - agent.utils.agent_utils.SESSIONS_ROOT  → turn 文件、session_dir、get_history
      - agent.history.tool_call_recorder.TOOL_CALLING_ROOT → tool_*.json、token
      - web.ui_session.SESSIONS_ROOT → turn relpath 计算

    返回重定向后的任务目录绝对路径。
    """
    from agent.cron.storage import CRON_ROOT
    import agent.utils.agent_utils as au
    au.SESSIONS_ROOT = CRON_ROOT

    from agent.history import tool_call_recorder as tcr
    tcr.TOOL_CALLING_ROOT = Path(CRON_ROOT)

    import web.ui_session as ui
    ui.SESSIONS_ROOT = CRON_ROOT

    task_dir = os.path.join(CRON_ROOT, task_id)
    os.makedirs(task_dir, exist_ok=True)
    return task_dir


def _start_live_forwarder(task_id: str) -> threading.Event:
    """启动后台线程：订阅本进程 live 更新并转发到主进程。

    返回一个 stop Event，主线程在执行结束后 set 它以终止转发线程。
    """
    stop = threading.Event()

    def _forward():
        try:
            import requests
            from agent.history.tool_call_recorder import subscribe_live, unsubscribe_live
        except Exception:
            return
        q = subscribe_live(task_id)
        try:
            while not stop.is_set():
                try:
                    snapshot = q.get(timeout=0.5)
                except Exception:
                    continue
                if snapshot is None:
                    break
                try:
                    requests.post(
                        _LIVE_URL,
                        json={"task_id": task_id, "snapshot": snapshot},
                        timeout=5,
                    )
                except Exception:
                    # 主进程不可达时不阻塞子进程执行
                    pass
        finally:
            try:
                unsubscribe_live(task_id, q)
            except Exception:
                pass

    t = threading.Thread(target=_forward, name=f"cron-live-{task_id}", daemon=True)
    t.start()
    return stop


def _post_finished(task_id: str, status: str, error: str, turn_id: str) -> None:
    """回传最终状态到主进程。失败时仅打印日志，不影响子进程退出。"""
    try:
        import requests
        requests.post(
            _FINISHED_URL,
            json={
                "task_id": task_id,
                "status": status,
                "error": error,
                "turn_id": turn_id,
            },
            timeout=10,
        )
    except Exception as e:
        print(f"[cron.runner] 回传 finished 失败: {e}", file=sys.stderr)


def _run_with_timeout(func, timeout: float) -> tuple[Any, BaseException | None, bool]:
    """在工作线程中执行 func。

    返回 (result, exception, timed_out)：
      - 正常完成 → (value, None, False)
      - 抛异常   → (None, exc, False)
      - 超时     → (None, None, True)

    超时后无法真正杀死工作线程（Python 限制），但子进程随后 sys.exit 会使
    整个进程退出，工作线程随之销毁。
    """
    box: dict[str, Any] = {}
    done = threading.Event()

    def _worker():
        try:
            box["value"] = func()
        except BaseException as e:  # noqa: BLE001 — 子进程需捕获全部异常以回传状态
            box["error"] = e
        finally:
            done.set()

    t = threading.Thread(target=_worker, name="cron-exec", daemon=True)
    t.start()
    finished = done.wait(timeout=timeout if timeout > 0 else None)
    if not finished:
        return None, None, True
    if "error" in box:
        return None, box["error"], False
    return box.get("value"), None, False


def _classify_runner_error(e: Exception) -> str:
    """将执行异常归类为可读错误描述（复用 runtime 的分类逻辑）。"""
    try:
        from agent.core.runtime import _classify_error
        return _classify_error(e)
    except Exception:
        return f"执行过程中出现错误: {str(e)[:200]}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Agent 定时任务子进程执行器")
    parser.add_argument("--task-id", required=True, help="任务 ID")
    parser.add_argument("--prompt", required=True, help="触发时投递给 Agent 的提示词")
    parser.add_argument("--trigger", default="schedule", choices=["schedule", "manual"],
                        help="触发来源：schedule（调度）| manual（手动/追问）")
    parser.add_argument("--timeout", type=int, default=300, help="单次执行超时秒数")
    args = parser.parse_args()

    task_id = args.task_id
    prompt = args.prompt
    timeout = max(int(args.timeout or 300), 10)

    started_iso = ""
    try:
        from agent.cron.models import now_iso
        started_iso = now_iso()
    except Exception:
        pass

    # 1. 重定向存储根目录（必须在构建 runtime 之前）
    try:
        _redirect_storage_roots(task_id)
    except Exception as e:
        print(f"[cron.runner] 重定向存储根目录失败: {e}", file=sys.stderr)
        traceback.print_exc()
        _post_finished(task_id, "failed", f"存储初始化失败: {e}", "")
        return 1

    # 2. 构建 AgentRuntime
    try:
        from agent.agents.agent_runtime import build_all_agent_runtimes, get_main_agent_runtime
        build_all_agent_runtimes()
        runtime = get_main_agent_runtime()
        if runtime is None:
            _post_finished(task_id, "failed", "未找到可用的主 Agent 运行时", "")
            return 1
    except Exception as e:
        print(f"[cron.runner] 构建 AgentRuntime 失败: {e}", file=sys.stderr)
        traceback.print_exc()
        _post_finished(task_id, "failed", f"Agent 初始化失败: {e}", "")
        return 1

    # 3. 启动 live 转发线程
    stop_forwarder = _start_live_forwarder(task_id)

    # 4. 执行任务（agent_mode="cron"，直接走 core.runtime 绕开 {"agent","plan"} 归一化）
    from agent.core.runtime import execute_agent as execute_runtime_agent
    from agent.utils.agent_utils import get_last_turn_id

    chat_history = [{"role": "user", "content": prompt}]
    status = "completed"
    error_msg = ""

    def _exec():
        return execute_runtime_agent(
            runtime=runtime,
            chat_history=chat_history,
            session_id=task_id,
            agent_mode="cron",
        )

    try:
        result_chat_history, exc, timed_out = _run_with_timeout(_exec, float(timeout))
        if timed_out:
            status = "failed"
            error_msg = f"任务超时（超过 {timeout} 秒）"
        elif exc is not None:
            status = "failed"
            error_msg = _classify_runner_error(exc)
            traceback.print_exception(type(exc), exc, exc.__traceback__)
        else:
            # 正常完成；检查最后一条消息是否含错误文案（如 OOM、API 错误）
            if result_chat_history:
                last = result_chat_history[-1] if result_chat_history else {}
                if isinstance(last, dict) and last.get("role") == "assistant":
                    content = str(last.get("content") or "")
                    _ERROR_PREFIXES = (
                        "OOM:", "执行过程中出现错误", "API Key", "无法连接",
                        "指定的模型", "模型服务端", "对话内容超过", "API 调用频率",
                        "Agent 执行轮数超过限制",
                    )
                    if content.startswith(_ERROR_PREFIXES):
                        status = "failed"
                        error_msg = content
    except Exception as e:
        status = "failed"
        error_msg = _classify_runner_error(e)
        traceback.print_exc()

    # 5. 停止转发线程
    stop_forwarder.set()

    # 6. 获取本次 turn_id（用于关联执行记录）
    turn_id = ""
    try:
        turn_id = get_last_turn_id(task_id) or ""
    except Exception:
        pass

    # 6.5 MySQL 模式下把执行记录导入数据库（json 模式无操作，文件即存储）
    try:
        from agent.cron.storage import persist_turn_records
        persist_turn_records(task_id, turn_id)
    except Exception as e:
        print(f"[cron.runner] 导入执行记录失败: {e}", file=sys.stderr)

    # 7. 回传最终状态
    _post_finished(task_id, status, error_msg, turn_id)

    # 给转发线程一点时间发送最后的快照
    time.sleep(0.3)
    return 0 if status == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
