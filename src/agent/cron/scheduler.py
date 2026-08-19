"""定时任务调度器。

系统定位:
    主进程后台 daemon 线程，每 5s 扫描所有启用的定时任务，到点则拉起
    子进程（agent.cron.runner）执行。负责 next_run_at 计算、错失/过期处理、
    子进程生命周期回收。

设计要点:
    - croniter 计算 cron 表达式的下一次触发时刻。
    - once 类型若错过且从未成功 → 标记 expired 并禁用。
    - cron 类型启动扫描时若发现错过一轮 → 记 expired 执行记录并推进到下一时刻。
    - _running_procs 防止同任务并发执行。
    - spawn_now 供手动立即运行 / 追问使用（trigger=manual）。
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from agent.cron.models import CronTask, now_iso
from agent.cron.storage import get_task_repository

# 扫描间隔（秒）
_SCAN_INTERVAL = 5.0

# 时间段长度（分钟）：同一时间段内只允许一个定时任务运行（全局并发=1）。
# 由 env_config.json 的 CRON_TIME_PERIOD_MINUTES 配置，默认 30。
_CRON_TIME_PERIOD_MINUTES = 30.0


def _load_time_period_minutes() -> float:
    """从 env_config.json 读取 CRON_TIME_PERIOD_MINUTES，失败回退默认 30。"""
    global _CRON_TIME_PERIOD_MINUTES
    try:
        from agent.core.config_manager import load_env_config
        cfg = load_env_config() or {}
        val = float(cfg.get("CRON_TIME_PERIOD_MINUTES", 30) or 30)
        if val > 0:
            _CRON_TIME_PERIOD_MINUTES = val
    except Exception:
        pass
    return _CRON_TIME_PERIOD_MINUTES


def get_cron_time_period() -> float:
    """获取当前时间段长度（分钟），供 API 暴露给前端与冲突检测使用。"""
    return _CRON_TIME_PERIOD_MINUTES


def set_cron_time_period(minutes: float) -> float:
    """热更新时间段长度（分钟），并持久化到 env_config.json。

    输入:
        minutes: 新的时间段长度（必须为正数）。

    输出:
        生效后的时间段长度（分钟）。
    """
    global _CRON_TIME_PERIOD_MINUTES
    val = float(minutes)
    if val <= 0:
        raise ValueError("Time period must be a positive number")
    _CRON_TIME_PERIOD_MINUTES = val
    try:
        from agent.core.config_manager import load_env_config, save_env_config
        cfg = load_env_config() or {}
        cfg["CRON_TIME_PERIOD_MINUTES"] = int(val) if float(val).is_integer() else val
        save_env_config(cfg)
    except Exception as e:
        print(f"[CronScheduler] Failed to save CRON_TIME_PERIOD_MINUTES: {e}")
    return val


def _parse_iso(dt_str: str) -> datetime | None:
    """解析 ISO 字符串（无时区）为 datetime，失败返回 None。"""
    if not dt_str:
        return None
    try:
        return datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None


def _compute_next_run(trigger, now: datetime) -> str:
    """根据触发配置计算下一次运行时刻（ISO 字符串）。

    输入:
        trigger: Trigger 实例。
        now: 当前 datetime。

    输出:
        下次运行 ISO 字符串；不再运行（once 已过）时返回 ""。
    """
    t_type = trigger.type
    if t_type == "cron":
        if not trigger.cron:
            return ""
        try:
            from croniter import croniter
            itr = croniter(trigger.cron, now)
            return itr.get_next(datetime).strftime("%Y-%m-%dT%H:%M:%S")
        except Exception:
            return ""
    if t_type == "interval":
        if trigger.interval_seconds <= 0:
            return ""
        nxt = now + timedelta_safe(trigger.interval_seconds)
        return nxt.strftime("%Y-%m-%dT%H:%M:%S")
    if t_type == "once":
        target = _parse_iso(trigger.run_at)
        if target is None or target <= now:
            # 已过时，不再调度
            return ""
        return trigger.run_at
    return ""


def timedelta_safe(seconds: int):
    from datetime import timedelta
    return timedelta(seconds=seconds)


def compute_next_fire(trigger, now: datetime | None = None) -> datetime | None:
    """计算下一次触发时刻（datetime），供新建/修改任务的时段冲突检测使用。

    输入:
        trigger: Trigger 实例（type/cron/interval_seconds/run_at）。
        now: 基准时刻，默认 datetime.now()。

    输出:
        下一次触发的 datetime；不再触发（once 已过等）返回 None。
    """
    now = now or datetime.now()
    iso = _compute_next_run(trigger, now)
    if not iso:
        return None
    return _parse_iso(iso)


def detect_time_period_conflict(trigger, exclude_task_id: str | None = None) -> dict[str, Any]:
    """检测候选任务下次触发时刻是否落入某现有任务时段窗口内。

    供前端 check-conflict API 与 cron_manager 工具复用，保证两条入口判定一致。

    输入:
        trigger: 候选任务的 Trigger 实例。
        exclude_task_id: 修改任务时排除自身 task_id，避免与自身比较。

    输出:
        {"conflict": bool, "conflict_with": [name,...], "period_minutes": float, "next_fire": "ISO"|""}
        若候选下次触发时刻与某已启用任务的下次触发时刻绝对差 < 时段长度则 conflict=True。
    """
    period_min = get_cron_time_period()
    period_sec = period_min * 60
    now = datetime.now()
    cand_fire = compute_next_fire(trigger, now)
    result: dict[str, Any] = {
        "conflict": False,
        "conflict_with": [],
        "period_minutes": period_min,
        "next_fire": cand_fire.strftime("%Y-%m-%dT%H:%M:%S") if cand_fire else "",
    }
    if cand_fire is None:
        # 候选不再触发（once 已过等），无冲突
        return result
    exclude_id = str(exclude_task_id or "")
    repo = get_task_repository()
    for t in repo.list_tasks():
        if not t.enabled:
            continue
        if t.task_id == exclude_id:
            continue
        ex_fire = compute_next_fire(t.trigger, now)
        if ex_fire is None:
            continue
        if abs((cand_fire - ex_fire).total_seconds()) < period_sec:
            result["conflict"] = True
            if t.name and t.name not in result["conflict_with"]:
                result["conflict_with"].append(t.name)
    return result


class CronScheduler:
    """单例调度器。

    生命周期:
        start() → 启动 daemon 线程；shutdown() → 终止线程并 kill 所有子进程。
        由 FastAPI lifespan 调用。
    """

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._running_procs: dict[str, subprocess.Popen] = {}
        self._procs_lock = threading.Lock()
        self._app_start_time = datetime.now()
        self._started = False
        # 当前占用时段起点（time.time() 秒），None 表示空闲。
        # 任务启动时置为 now，时段自然到期（超过 CRON_TIME_PERIOD_MINUTES）后释放；
        # _monitor_proc 回收时不清除，确保"一个时间段一个任务"。
        self._period_start_ts: float | None = None

    # ---------- 单例 ----------
    _instance: "CronScheduler | None" = None
    _instance_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "CronScheduler":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    # ---------- 生命周期 ----------
    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._stop_event.clear()
        self._app_start_time = datetime.now()
        # 启动时加载时间段长度配置（CRON_TIME_PERIOD_MINUTES）
        _load_time_period_minutes()
        self._thread = threading.Thread(target=self._run_loop, name="cron-scheduler", daemon=True)
        self._thread.start()
        print("[CronScheduler] Scheduler thread started")

    def shutdown(self) -> None:
        if not self._started:
            return
        self._stop_event.set()
        # 终止所有运行中的子进程
        with self._procs_lock:
            procs = list(self._running_procs.values())
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=3.0)
        self._started = False
        print("[CronScheduler] Scheduler thread stopped")

    # ---------- 主循环 ----------
    def _run_loop(self) -> None:
        # 启动时重算缺失的 next_run_at，并处理错失/过期
        try:
            self._on_startup()
        except Exception as e:
            print(f"[CronScheduler] Startup scan error: {e}")

        while not self._stop_event.is_set():
            try:
                self._scan_once()
            except Exception as e:
                print(f"[CronScheduler] Scan error: {e}")
            self._stop_event.wait(_SCAN_INTERVAL)

    def _on_startup(self) -> None:
        """启动扫描：重算 next_run_at，处理应用未运行期间错失的触发。"""
        repo = get_task_repository()
        now = datetime.now()
        for task in repo.list_tasks():
            if not task.enabled:
                continue
            if task.task_id in self._running_procs:
                continue
            self._handle_startup_task(task, now, repo)

    def _handle_startup_task(self, task: CronTask, now: datetime, repo) -> None:
        """处理单个任务在启动时的 next_run_at 重算与错失判定。"""
        trigger = task.trigger
        t_type = trigger.type

        # once 类型：若目标时间已过且从未成功完成 → 标记 expired 并禁用
        if t_type == "once":
            target = _parse_iso(trigger.run_at)
            if target is not None and target < now:
                ever_succeeded = any(e.status == "completed" for e in task.executions)
                if not ever_succeeded:
                    repo.append_execution(task.task_id, {
                        "started_at": trigger.run_at,
                        "ended_at": now_iso(),
                        "status": "expired",
                        "error": "App was not running, missed execution time",
                        "trigger": "schedule",
                        "turn_id": "",
                    })
                    repo.update_status(task.task_id, "expired",
                                        error="App was not running, missed execution time",
                                        next_run_at="")
                    task.enabled = False
                    task.last_status = "expired"
                    repo.save_task(task)
                    return
            # once 未过或已成功：重算 next_run_at
            nxt = _compute_next_run(trigger, now)
            if nxt != task.next_run_at:
                repo.update_status(task.task_id, task.last_status, next_run_at=nxt)
            return

        # cron 类型：若 next_run_at 早于 app 启动时间 → 说明错过了一轮
        if t_type == "cron":
            if not task.next_run_at:
                nxt = _compute_next_run(trigger, now)
                repo.update_status(task.task_id, task.last_status, next_run_at=nxt)
                return
            nxt_dt = _parse_iso(task.next_run_at)
            if nxt_dt is not None and nxt_dt < self._app_start_time:
                # 错过该次触发：记 expired 执行记录，推进到下一个未来时刻
                repo.append_execution(task.task_id, {
                    "started_at": task.next_run_at,
                    "ended_at": now_iso(),
                    "status": "expired",
                    "error": "App was not running, missed this trigger",
                    "trigger": "schedule",
                    "turn_id": "",
                })
                new_nxt = _compute_next_run(trigger, now)
                repo.update_status(task.task_id, task.last_status, next_run_at=new_nxt)
            return

        # interval 类型：直接推进到 now + interval（不记过期）
        if t_type == "interval":
            nxt_dt = _parse_iso(task.next_run_at)
            if not task.next_run_at or (nxt_dt is not None and nxt_dt < now):
                new_nxt = _compute_next_run(trigger, now)
                repo.update_status(task.task_id, task.last_status, next_run_at=new_nxt)
            return

    def _scan_once(self) -> None:
        """单次扫描：到点且未在跑的任务 → spawn 子进程。"""
        repo = get_task_repository()
        now = datetime.now()
        now_iso_str = now_iso()
        for task in repo.list_tasks():
            if not task.enabled:
                continue
            if task.task_id in self._running_procs:
                continue
            if not task.next_run_at:
                continue
            nxt_dt = _parse_iso(task.next_run_at)
            if nxt_dt is None or nxt_dt > now:
                continue
            # 到点触发
            self._spawn(task, trigger_source="schedule", started_iso=now_iso_str)

    # ---------- 子进程管理 ----------
    def _get_python_and_cwd(self) -> tuple[str, str]:
        """获取子进程使用的 Python 解释器路径与工作目录（src）。"""
        try:
            from agent.core.config_manager import load_env_config
            cfg = load_env_config() or {}
            py = cfg.get("USER_PYTHON_PATH", "")
            if py and os.path.isfile(py):
                pass
            else:
                py = sys.executable
        except Exception:
            py = sys.executable
        # cwd = src 目录（agent/web 包所在目录）
        from agent.cron import storage as _storage
        cwd = str(Path(_storage.__file__).resolve().parents[2])
        return py, cwd

    def _spawn(self, task: CronTask, trigger_source: str, started_iso: str, prompt: str | None = None) -> bool:
        """拉起子进程执行任务。

        输入:
            task: 任务对象。
            trigger_source: "schedule" | "manual"。
            started_iso: 本次开始时间 ISO。
            prompt: 可选覆盖提示词（手动追问时使用）；None 则用 task.prompt。

        输出:
            True 表示已成功 spawn。
        """
        with self._procs_lock:
            if task.task_id in self._running_procs:
                return False
            # 时段 gate：同一时间段内只允许一个任务运行。
            # 1) 已有任务在跑 → 跳过；
            # 2) 上一个任务启动后仍在 CRON_TIME_PERIOD_MINUTES 时段窗口内 → 跳过。
            now_ts = time.time()
            if self._running_procs:
                print(f"[CronScheduler] Task already running in period, skipping {task.task_id}")
                return False
            if self._period_start_ts is not None and (now_ts - self._period_start_ts) < _CRON_TIME_PERIOD_MINUTES * 60:
                print(f"[CronScheduler] Task exists in period, skipping {task.task_id}")
                return False
            # 占用新时段
            self._period_start_ts = now_ts

        py, cwd = self._get_python_and_cwd()
        use_prompt = prompt if prompt is not None else task.prompt
        cmd = [
            py, "-m", "agent.cron.runner",
            "--task-id", task.task_id,
            "--prompt", use_prompt,
            "--trigger", trigger_source,
            "--timeout", str(task.timeout_seconds),
            "--workspace", task.workspace or "",
        ]
        env = dict(os.environ)
        # 确保 src 在 PYTHONPATH（与 cwd 配合，-m 已能定位 agent 包）
        try:
            if cwd not in env.get("PYTHONPATH", ""):
                env["PYTHONPATH"] = cwd + os.pathsep + env.get("PYTHONPATH", "")
        except Exception:
            pass

        try:
            proc = subprocess.Popen(
                cmd,
                cwd=cwd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                # 避免子进程随父进程退出被信号干扰
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0,
            )
        except Exception as e:
            print(f"[CronScheduler] Failed to spawn subprocess task={task.task_id}: {e}")
            get_task_repository().update_status(task.task_id, "failed", error=f"Failed to spawn subprocess: {e}")
            # 子进程未启动成功，释放占用的时段（避免空占时段阻塞后续任务）
            with self._procs_lock:
                if not self._running_procs:
                    self._period_start_ts = None
            return False

        with self._procs_lock:
            self._running_procs[task.task_id] = proc

        repo = get_task_repository()
        repo.update_status(task.task_id, "running", error="", last_run_at=started_iso)

        # 后台线程监控子进程退出
        monitor = threading.Thread(
            target=self._monitor_proc,
            args=(task.task_id, proc, trigger_source, started_iso),
            name=f"cron-monitor-{task.task_id}",
            daemon=True,
        )
        monitor.start()
        return True

    def _monitor_proc(self, task_id: str, proc: subprocess.Popen, trigger_source: str, started_iso: str) -> None:
        """监控子进程退出，回收并更新状态。

        注意：子进程自身会 POST /api/cron/internal/finished 回传最终状态（含超时/异常）。
        本监控线程作为兜底：若子进程异常退出且未回传，则据 exit code 推断状态；
        若已回传（status 已被 finished handler 更新为 completed/failed），则不覆盖。
        """
        exit_code = proc.wait()
        ended_iso = now_iso()

        with self._procs_lock:
            self._running_procs.pop(task_id, None)

        repo = get_task_repository()
        task = repo.get_task(task_id)
        if task is None:
            return

        # 若 finished handler 已更新状态为终态（completed/failed/expired），则不覆盖
        if task.last_status in ("completed", "failed", "expired"):
            return

        # 兜底：子进程未回传 finished（如被 kill、崩溃），据 exit code 推断
        if exit_code == 0:
            status = "completed"
            error = ""
        else:
            status = "failed"
            error = f"Subprocess exited abnormally (exit code {exit_code})"
        repo.update_status(task_id, status, error=error, last_run_at=started_iso)
        repo.append_execution(task_id, {
            "started_at": started_iso,
            "ended_at": ended_iso,
            "status": status,
            "error": error,
            "trigger": trigger_source,
            "turn_id": "",
        })

    # ---------- 手动触发 / 立即运行 ----------
    def spawn_now(self, task_id: str, prompt: str | None = None) -> bool:
        """立即运行指定任务（手动触发或追问）。

        输入:
            task_id: 任务 ID。
            prompt: 追问时传入的新提示词；None 则使用任务原始 prompt。

        输出:
            True 表示已成功 spawn。
        """
        task = get_task_repository().get_task(task_id)
        if task is None:
            return False
        with self._procs_lock:
            if task_id in self._running_procs:
                return False
        return self._spawn(task, trigger_source="manual", started_iso=now_iso(), prompt=prompt)

    def is_running(self, task_id: str) -> bool:
        with self._procs_lock:
            return task_id in self._running_procs

    def kill_task(self, task_id: str) -> bool:
        """终止运行中的子进程。"""
        with self._procs_lock:
            proc = self._running_procs.get(task_id)
        if proc is None:
            return False
        try:
            proc.terminate()
            return True
        except Exception:
            return False

    def reload_task(self, task_id: str) -> None:
        """任务配置变更后重算 next_run_at（供 cron_manager 工具调用）。"""
        task = get_task_repository().get_task(task_id)
        if task is None:
            return
        if not task.enabled:
            return
        nxt = _compute_next_run(task.trigger, datetime.now())
        get_task_repository().update_status(task_id, task.last_status, next_run_at=nxt)


def get_scheduler() -> CronScheduler:
    """获取全局调度器单例。"""
    return CronScheduler.get_instance()
