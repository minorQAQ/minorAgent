# README 展示图片说明

本目录存放 GitHub 项目页 README 中引用的展示图片。下方表格列出每张图的**文件名、引用位置、建议内容与尺寸**，按需制作后放入本目录即可（README 已用相对路径 `./git_image/xxx.png` 引用）。

| 文件名 | 在 README 中的位置 | 建议内容 | 建议尺寸 |
|--------|-------------------|----------|----------|
| `banner.png` | 顶部主图 | Agent 主界面截图（侧边栏 + 聊天区 + 工具调用面板 + Agent 面板同时可见，体现多模态对话与工具执行） | 宽 920px，比例 16:9 |
| `architecture.png` | 「项目架构」整体分层 | 系统分层图：Electron 主进程 → FastAPI → Agent 编排层 → LangGraph ReAct 图 → 工具/技能（可用 Mermaid 或 draw.io 导出 PNG） | 宽 860px |
| `react-loop.png` | 「ReAct 循环」节 | ReAct 循环流程图：`agent → tools → process_tool_artifact`，标注压缩 / 循环检测 / 视觉闭环注入 | 宽 780px |
| `wizard.png` | 「快速开始 → 桌面应用」 | 首次配置向导截图（3 步：Python 环境 / LLM 设置 / 高级参数） | 宽 720px |
| `multi-agent.png` | （可选补充）「多 Agent 模式」 | supervisor ↔ parallel_sub_agents 调度示意图 | 宽 720px |
| `desktop-demo.gif` | （可选补充）顶部或功能亮点 | GUI 自动化操作录屏（如自动填表单 / 操作 ERP），10–15s 循环 | 宽 720px |

## 制作建议

- **截图**：先 `npm start` 启动桌面端，进入主界面后用系统截图工具，裁掉无关边框
- **流程图**：推荐用 [Mermaid](https://mermaid.live/) 画好后导出 PNG，或 draw.io / Excalidraw
- **格式**：截图优先 PNG（无损）；录屏用 GIF 或 MP4（GitHub 支持 MP4 内联播放）
- **体积**：单张控制在 500KB 以内，可用 [TinyPNG](https://tinypng.com/) 压缩
- **命名**：保持与上表一致，README 引用路径无需改动

> 放入图片前，README 会显示破损图标占位；放入后自动渲染。
