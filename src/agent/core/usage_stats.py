"""全局 Token 用量统计：跨会话、按小时聚合、按模型分账。

系统定位:
    独立于会话存储的全局诊断数据：每次主 Agent LLM 调用后累加 total_tokens，
    按 (日期, 小时) 与模型维度记录，供前端欢迎区的「活跃度矩阵 / 柱状图」展示。
    cron 任务同样计入（统一为真实消耗）；子 Agent 不计入（与 set_session_tokens 一致）。

存储:
    固定落盘 ``<HISTORY_ROOT>/usage_stats.json``，不随存储后端（JSON/MySQL）切换，
    也不受 cron 存储作用域重定向影响——统计是本地诊断数据，独立 JSON 足够。

    文件写入采用「临时文件 + os.replace」原子替换；多进程（主进程 + cron 子进程）
    并发写时可能出现一次读-改-写竞态导致的少量丢失，可接受。

可扩展性:
    可增加按月汇总、导出、TTL 配置。
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timedelta
from typing import Any

from agent.utils.agent_utils import HISTORY_ROOT

_HOUR_FMT = "%Y-%m-%dT%H"   # 小时粒度键
_DAY_FMT = "%Y-%m-%d"
_RETAIN_DAYS = 200          # 存储保留天数（前端展示最近 182 天，留余量）
_CLEANUP_INTERVAL = 6 * 3600  # 裁剪检查间隔（秒）

_FILE = os.path.join(HISTORY_ROOT, "usage_stats.json")

_lock = threading.Lock()
_last_cleanup = 0.0


def _load() -> dict[str, Any]:
    """读取全局统计文件；缺失或损坏时返回空结构。"""
    try:
        with open(_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("hours"), dict):
            return data
    except (OSError, ValueError):
        pass
    return {"hours": {}}


def _save(data: dict[str, Any]) -> None:
    """原子写盘：临时文件 + os.replace。"""
    tmp = _FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, _FILE)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _cleanup(data: dict[str, Any], now: float) -> None:
    """裁剪 _RETAIN_DAYS 天之前的小时键。"""
    global _last_cleanup
    if now - _last_cleanup < _CLEANUP_INTERVAL:
        return
    _last_cleanup = now
    cutoff = datetime.fromtimestamp(now) - timedelta(days=_RETAIN_DAYS)
    cutoff_key = cutoff.strftime(_HOUR_FMT)
    hours = data.get("hours", {})
    for key in [k for k in hours if k < cutoff_key]:
        hours.pop(key, None)


def record_usage(total: int, model: str = "", ts: float | None = None) -> None:
    """累加一次 LLM 调用的 token 用量到对应小时（按模型分账）。

    输入:
        total: total_tokens（>0 才记录）。
        model: 模型名（用于柱状图按模型分色）；空串时仅累计总量。
        ts: 调用时间戳；None 使用当前时间。
    """
    if total <= 0:
        return
    ts = ts if ts is not None else time.time()
    hour = datetime.fromtimestamp(ts).strftime(_HOUR_FMT)
    with _lock:
        data = _load()
        hours = data.setdefault("hours", {})
        entry = hours.setdefault(hour, {"total": 0, "by_model": {}})
        entry["total"] = entry.get("total", 0) + total
        if model:
            entry["by_model"][model] = entry["by_model"].get(model, 0) + total
        _cleanup(data, ts)
        _save(data)


def get_usage_summary(days: int = 182) -> dict[str, Any]:
    """聚合最近 N 天的用量统计。

    输出:
        {
          "total": int,                                   # 跨会话累计总量
          "by_model": {model: int},                       # 全局按模型总量
          "days": [{"date": "YYYY-MM-DD", "total": int,   # 最近 N 天（含 0 值，
                    "by_model": {model: int}}, ...],      #  供活跃度矩阵完整网格）
          "hours": {"YYYY-MM-DD": {"HH": {model: int}}}  # 有数据的小时（非 0）
        }
    """
    now = datetime.now()
    day_keys = [(now - timedelta(days=days - 1 - i)).strftime(_DAY_FMT) for i in range(days)]
    day_floor = day_keys[0]
    day_ceil = day_keys[-1]

    daily = {d: {"total": 0, "by_model": {}} for d in day_keys}
    hours_out: dict[str, dict[str, dict[str, int]]] = {}
    total = 0
    by_model: dict[str, int] = {}

    with _lock:
        data = _load()
        for hour, entry in data.get("hours", {}).items():
            date = hour[:10]
            if date < day_floor or date > day_ceil:
                continue
            e_total = entry.get("total", 0)
            e_model = entry.get("by_model", {}) or {}
            total += e_total
            for m, v in e_model.items():
                by_model[m] = by_model.get(m, 0) + v
            d = daily[date]
            d["total"] += e_total
            for m, v in e_model.items():
                d["by_model"][m] = d["by_model"].get(m, 0) + v
            hours_out.setdefault(date, {})[hour[11:]] = dict(e_model)

    return {
        "total": total,
        "by_model": by_model,
        "days": [{"date": k, "total": v["total"], "by_model": v["by_model"]} for k, v in daily.items()],
        "hours": hours_out,
    }
