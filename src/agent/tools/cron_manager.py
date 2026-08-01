"""定时任务管理工具 cron_manager。

系统定位:
    让 Agent 自身能够查询、新增、修改、删除定时任务（含状态查看），
    无需用户手动操作前端。直接读写 CronTaskRepository，并在 create/update
    后通知调度器重算 next_run_at。

    图标: src/web/image/时钟.svg
"""
from __future__ import annotations

import json
from typing import Any, Literal, Optional

from langchain.tools import BaseTool
from pydantic import BaseModel, Field

from agent.cron.models import Trigger


class CronManagerInput(BaseModel):
    action: Literal["list", "get", "create", "update", "delete"] = Field(
        ...,
        description="操作类型：list=列出所有任务（含状态）；get=查看单个任务详情；"
                    "create=新建任务；update=修改任务；delete=删除任务。",
    )
    task_id: Optional[str] = Field(
        default=None,
        description="任务 ID。get/update/delete 时必填；list/create 时忽略。",
    )
    name: Optional[str] = Field(
        default=None,
        description="任务名称（create/update 时使用）。",
    )
    prompt: Optional[str] = Field(
        default=None,
        description="触发时投递给 Agent 的提示词（create/update 时使用）。",
    )
    trigger_type: Optional[Literal["cron", "interval", "once"]] = Field(
        default=None,
        description="触发类型：cron=cron 表达式；interval=固定间隔秒；once=一次性延时（create/update 时使用）。",
    )
    cron: Optional[str] = Field(
        default=None,
        description="trigger_type=cron 时的标准 5 段 cron 表达式，如 '0 9 * * *' 表示每天 9 点。",
    )
    interval_seconds: Optional[int] = Field(
        default=None,
        description="trigger_type=interval 时的间隔秒数，如 3600 表示每小时。",
    )
    run_at: Optional[str] = Field(
        default=None,
        description="trigger_type=once 时的目标本地时间，ISO 格式如 '2026-07-29T18:00:00'。",
    )
    timeout_seconds: Optional[int] = Field(
        default=None,
        description="单次执行超时秒数（默认 300）。",
    )
    enabled: Optional[bool] = Field(
        default=None,
        description="是否启用（update 时使用）。",
    )


class CronManagerTool(BaseTool):
    """定时任务管理工具：支持查看（含状态）、新增、修改、删除定时任务。"""

    args_schema: type[BaseModel] = CronManagerInput
    name: str = "cron_manager"
    description: str = (
        "定时任务管理工具。用于查看、新增、修改、删除定时任务（含任务状态）。\n"
        "适用场景：用户希望设置/查看/修改定时任务，或 Agent 在定时任务模式下需要管理其他定时任务。\n"
        "参数说明：\n"
        "- action: list（列出所有任务含状态）/ get（查看单个任务详情含执行历史）/ create / update / delete\n"
        "- task_id: get/update/delete 时必填\n"
        "- name/prompt/trigger_type/cron/interval_seconds/run_at/timeout_seconds/enabled: create/update 时使用\n"
        "触发类型说明：\n"
        "- cron: 标准 cron 表达式，如 '0 9 * * *'（每天9点）、'*/30 * * * *'（每30分钟）\n"
        "- interval: 固定间隔秒数，如 3600（每小时）、86400（每天）\n"
        "- once: 一次性延时，指定 ISO 本地时间如 '2026-07-29T18:00:00'\n"
        "调用示例：\n"
        '- 列出所有任务: {"action": "list"}\n'
        '- 创建每分钟任务: {"action": "create", "name": "定时查时间", "prompt": "查询当前时间并汇报", "trigger_type": "cron", "cron": "* * * * *"}\n'
        '- 查看任务详情: {"action": "get", "task_id": "20260729_120000"}\n'
    )

    def _run(self, action: str = "list", task_id: str | None = None, **kwargs: Any) -> str:
        try:
            from agent.cron.storage import get_task_repository, new_task_id
            from agent.cron.models import CronTask, Trigger, now_iso
            from agent.cron.scheduler import _compute_next_run, get_scheduler, detect_time_period_conflict
            from datetime import datetime

            repo = get_task_repository()

            if action == "list":
                tasks = repo.list_tasks()
                items = []
                for t in tasks:
                    d = t.summary()
                    try:
                        d["is_running"] = get_scheduler().is_running(t.task_id)
                    except Exception:
                        d["is_running"] = False
                    items.append(d)
                return json.dumps({"action": "list", "count": len(items), "tasks": items}, ensure_ascii=False, indent=2)

            if action == "get":
                if not task_id:
                    return json.dumps({"error": "get 操作需提供 task_id"}, ensure_ascii=False)
                task = repo.get_task(task_id)
                if task is None:
                    return json.dumps({"error": f"任务 {task_id} 不存在"}, ensure_ascii=False)
                d = task.to_dict()
                try:
                    d["is_running"] = get_scheduler().is_running(task_id)
                except Exception:
                    d["is_running"] = False
                return json.dumps({"action": "get", "task": d}, ensure_ascii=False, indent=2)

            if action == "create":
                trigger = self._build_trigger(kwargs)
                if isinstance(trigger, str):  # 错误信息
                    return json.dumps({"error": trigger}, ensure_ascii=False)
                # 时段冲突检测：与前端 check-conflict 复用同一套逻辑
                conflict = detect_time_period_conflict(trigger)
                if conflict.get("conflict"):
                    names = "、".join(conflict.get("conflict_with") or []) or "其他任务"
                    return json.dumps({
                        "error": (
                            f"时间段内已有其他任务（{names}），需调整触发时间。"
                            f"当前时间段长度：{conflict.get('period_minutes')} 分钟，"
                            f"候选下次触发：{conflict.get('next_fire') or '无'}"
                        )
                    }, ensure_ascii=False)
                task = CronTask(
                    task_id=new_task_id(),
                    name=str(kwargs.get("name") or "未命名任务"),
                    prompt=str(kwargs.get("prompt") or ""),
                    trigger=trigger,
                    enabled=True,
                    timeout_seconds=int(kwargs.get("timeout_seconds") or 300),
                    created_at=now_iso(),
                    last_status="pending",
                )
                task.next_run_at = _compute_next_run(trigger, datetime.now())
                repo.save_task(task)
                try:
                    get_scheduler().reload_task(task.task_id)
                except Exception:
                    pass
                return json.dumps({"action": "create", "success": True, "task": task.summary()}, ensure_ascii=False, indent=2)

            if action == "update":
                if not task_id:
                    return json.dumps({"error": "update 操作需提供 task_id"}, ensure_ascii=False)
                task = repo.get_task(task_id)
                if task is None:
                    return json.dumps({"error": f"任务 {task_id} 不存在"}, ensure_ascii=False)
                if kwargs.get("name") is not None:
                    task.name = str(kwargs["name"])
                if kwargs.get("prompt") is not None:
                    task.prompt = str(kwargs["prompt"])
                if kwargs.get("timeout_seconds") is not None:
                    task.timeout_seconds = int(kwargs["timeout_seconds"])
                if kwargs.get("enabled") is not None:
                    task.enabled = bool(kwargs["enabled"])
                if kwargs.get("trigger_type") is not None:
                    trigger = self._build_trigger(kwargs)
                    if isinstance(trigger, str):
                        return json.dumps({"error": trigger}, ensure_ascii=False)
                    task.trigger = trigger
                    # 触发时间变更且任务启用时，检测时段冲突（排除自身）
                    if task.enabled:
                        conflict = detect_time_period_conflict(trigger, exclude_task_id=task_id)
                        if conflict.get("conflict"):
                            names = "、".join(conflict.get("conflict_with") or []) or "其他任务"
                            return json.dumps({
                                "error": (
                                    f"时间段内已有其他任务（{names}），需调整触发时间。"
                                    f"当前时间段长度：{conflict.get('period_minutes')} 分钟，"
                                    f"候选下次触发：{conflict.get('next_fire') or '无'}"
                                )
                            }, ensure_ascii=False)
                if task.enabled:
                    task.next_run_at = _compute_next_run(task.trigger, datetime.now())
                else:
                    task.next_run_at = ""
                repo.save_task(task)
                try:
                    get_scheduler().reload_task(task.task_id)
                except Exception:
                    pass
                return json.dumps({"action": "update", "success": True, "task": task.summary()}, ensure_ascii=False, indent=2)

            if action == "delete":
                if not task_id:
                    return json.dumps({"error": "delete 操作需提供 task_id"}, ensure_ascii=False)
                try:
                    get_scheduler().kill_task(task_id)
                except Exception:
                    pass
                repo.delete_task(task_id)
                return json.dumps({"action": "delete", "success": True, "task_id": task_id}, ensure_ascii=False)

            return json.dumps({"error": f"未知 action: {action}"}, ensure_ascii=False)

        except Exception as e:
            return json.dumps({"error": f"cron_manager 执行失败: {str(e)}"}, ensure_ascii=False)

    @staticmethod
    def _build_trigger(kwargs: dict[str, Any]) -> Trigger | str:
        """从工具参数构建 Trigger，校验失败返回错误字符串。"""
        t_type = kwargs.get("trigger_type")
        if t_type is None:
            return "create/update 需提供 trigger_type（cron/interval/once）"
        if t_type == "cron":
            cron_expr = str(kwargs.get("cron") or "")
            if not cron_expr:
                return "trigger_type=cron 需提供 cron 表达式"
            return Trigger(type="cron", cron=cron_expr)
        if t_type == "interval":
            interval = kwargs.get("interval_seconds")
            if not interval or int(interval) <= 0:
                return "trigger_type=interval 需提供大于 0 的 interval_seconds"
            return Trigger(type="interval", interval_seconds=int(interval))
        if t_type == "once":
            run_at = str(kwargs.get("run_at") or "")
            if not run_at:
                return "trigger_type=once 需提供 run_at 时间"
            return Trigger(type="once", run_at=run_at)
        return f"不支持的 trigger_type: {t_type}"
