"""定时任务数据模型。

系统定位:
    定义 CronTask / Trigger / ExecutionLog 三个 dataclass，
    被 storage / scheduler / runner / API 共享。

可扩展性:
    - to_dict / from_dict 保证 JSON 持久化与未来 MySQL 序列化同构。
    - 新增触发类型时扩展 Trigger.type 的 Literal 并补 _compute_next_run 分支。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


TriggerType = Literal["cron", "interval", "once"]
TaskStatus = Literal["pending", "running", "completed", "failed", "expired", "disabled"]
TriggerSource = Literal["schedule", "manual"]


@dataclass
class Trigger:
    """触发配置。

    字段:
        type: "cron"（cron 表达式）| "interval"（固定间隔秒）| "once"（一次性延时）。
        cron: type=cron 时的标准 5 段 cron 表达式，如 "0 9 * * *"。
        interval_seconds: type=interval 时的间隔秒数。
        run_at: type=once 时的目标本地时间（ISO 字符串，如 "2026-07-29T18:00:00"）。
    """

    type: TriggerType = "cron"
    cron: str = ""
    interval_seconds: int = 0
    run_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "cron": self.cron,
            "interval_seconds": self.interval_seconds,
            "run_at": self.run_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "Trigger":
        data = data or {}
        return cls(
            type=data.get("type", "cron"),
            cron=data.get("cron", ""),
            interval_seconds=int(data.get("interval_seconds", 0) or 0),
            run_at=data.get("run_at", ""),
        )


@dataclass
class ExecutionLog:
    """单次执行记录。

    字段:
        started_at: 开始时间（ISO 字符串）。
        ended_at: 结束时间（ISO 字符串）。
        status: 本次执行结果状态。
        error: 失败时的错误描述。
        trigger: 触发来源——schedule（调度）| manual（手动/追问）。
        turn_id: 对应的 turn_id，用于关联工具调用记录。
    """

    started_at: str = ""
    ended_at: str = ""
    status: TaskStatus = "completed"
    error: str = ""
    trigger: TriggerSource = "schedule"
    turn_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "status": self.status,
            "error": self.error,
            "trigger": self.trigger,
            "turn_id": self.turn_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ExecutionLog":
        data = data or {}
        return cls(
            started_at=data.get("started_at", ""),
            ended_at=data.get("ended_at", ""),
            status=data.get("status", "completed"),
            error=data.get("error", ""),
            trigger=data.get("trigger", "schedule"),
            turn_id=data.get("turn_id", ""),
        )


@dataclass
class CronTask:
    """定时任务完整定义。

    字段:
        task_id: 任务唯一标识（时间戳风格，与 session_id 同构）。
        name: 任务名称（前端展示）。
        prompt: 触发时投递给 Agent 的用户提示词。
        trigger: 触发配置。
        enabled: 是否启用。
        timeout_seconds: 单次执行超时秒数。
        created_at: 创建时间（ISO 字符串）。
        next_run_at: 下次预计运行时间（ISO 字符串，空表示不再运行）。
        last_run_at: 上次运行时间（ISO 字符串）。
        last_status: 最近一次执行状态。
        last_error: 最近一次失败错误描述。
        executions: 历史执行记录列表。
    """

    task_id: str = ""
    name: str = ""
    prompt: str = ""
    trigger: Trigger = field(default_factory=Trigger)
    enabled: bool = True
    timeout_seconds: int = 300
    created_at: str = ""
    next_run_at: str = ""
    last_run_at: str = ""
    last_status: TaskStatus = "pending"
    last_error: str = ""
    executions: list[ExecutionLog] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "name": self.name,
            "prompt": self.prompt,
            "trigger": self.trigger.to_dict(),
            "enabled": self.enabled,
            "timeout_seconds": self.timeout_seconds,
            "created_at": self.created_at,
            "next_run_at": self.next_run_at,
            "last_run_at": self.last_run_at,
            "last_status": self.last_status,
            "last_error": self.last_error,
            "executions": [e.to_dict() for e in self.executions],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "CronTask":
        data = data or {}
        return cls(
            task_id=data.get("task_id", ""),
            name=data.get("name", ""),
            prompt=data.get("prompt", ""),
            trigger=Trigger.from_dict(data.get("trigger")),
            enabled=bool(data.get("enabled", True)),
            timeout_seconds=int(data.get("timeout_seconds", 300) or 300),
            created_at=data.get("created_at", ""),
            next_run_at=data.get("next_run_at", ""),
            last_run_at=data.get("last_run_at", ""),
            last_status=data.get("last_status", "pending"),
            last_error=data.get("last_error", ""),
            executions=[ExecutionLog.from_dict(e) for e in (data.get("executions") or [])],
        )

    def summary(self) -> dict[str, Any]:
        """返回前端列表展示用的精简字典（不含 executions 全量）。"""
        d = self.to_dict()
        d["executions_count"] = len(self.executions)
        d.pop("executions", None)
        return d


def now_iso() -> str:
    """当前本地时间的 ISO 字符串（无时区后缀，与前端一致）。"""
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
