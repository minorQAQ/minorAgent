"""Agent 定时任务（Cron）模式。

系统定位:
    为 Agent 应用提供无人值守的定时执行能力。与 Edit/Chat 模式并列，
    通过子进程隔离执行，不干扰主进程 Chat 流程。

子模块:
    - models: 数据模型（CronTask / Trigger / ExecutionLog）
    - storage: 存储抽象层（JSON 实现 + MySQL stub + 工厂）
    - scheduler: 调度器（croniter + 自写线程，spawn 子进程）
    - runner: 子进程入口（重定向 SESSIONS_ROOT，转发 live，回传 finished）
    - live: 主进程侧 live 快照中继（SSE pub/sub）
"""
