# minor Agent 代码深度分析报告

> 分析范围：`Agent/llm_server/`、`Agent/src/agent/cron/`、`Agent/src/agent/tts/streaming_client.py`、`Agent/src/agent/utils/`、`Agent/src/agent/memory/system_prompt.py`、`Agent/src/agent/agents/agent_runtime.py`、`Agent/src/agent/history/`、`Agent/src/web/ui_session.py`。全部路径精确到文件与关键函数/类/变量。

---

## 一、`C:\Users\86166\Desktop\Agent_Learning_minor\Agent\llm_server\`（本地推理后端，6 个模型/5 个服务端口）

### 1. README.md —— 部署与总览

- 定位：为 minor Agent 提供**本地化推理后端**，全部跑在 GPU 服务器上，以 OpenAI 兼容 / 自定义 HTTP API 暴露；可整体部署或按需启用。
- 服务总览表（README 自称 6 个独立服务，实际为 **5 个服务、6 个模型** —— RAG 一个服务内装 Embedding+Reranker 两个模型）：

| 服务 | 端口 | 模型 | 启动脚本 | Python 服务端 | 关键端点 |
|---|---|---|---|---|---|
| LLM | 8900 | Qwen3.6-35B-A3B-FP8 | `start_llm.sh` | vLLM 内置 | `/v1/chat/completions` |
| ASR | 8901 | Qwen3-ASR-1.7B | `start_asr.sh` | vLLM 内置 | `/v1/chat/completions` |
| TTS | 8902 | VoxCPM 1.5 / 2 | `start_streaming_tts.sh` | `streaming_tts_server.py` | `/stream_tts` |
| RAG | 8903 | Qwen3-Embedding-0.6B + Qwen3-Reranker-4B | `start_rag_server.sh` | `rag_server.py` | `/embed` `/rerank` |
| Image Gen | 8904 | Z-Image-Turbo | `start_image_gen.sh` | `image_gen_server.py` | `/generate` |

- 所有脚本/服务端通过 `os.path.dirname(__file__)` 与 `${SCRIPT_DIR}` 动态定位模型路径，**目录整体迁移无需改代码**。
- 部署流程要点：
  1. `scp -r Agent/llm_server/*` 上传 → 服务器上 `chmod +x *.sh`。
  2. 环境准备：`export HF_ENDPOINT=https://hf-mirror.com`、`HF_HUB_ENABLE_XET=0`（国内必需）；`python3 -m venv myenv`；一次性安装 `vllm modelscope transformers fastapi uvicorn torch numpy torchaudio soundfile bitsandbytes huggingface_hub voxcpm diffusers`；`apt` 安装 ffmpeg 全家桶。
  3. 模型统一存 `~/llm_server/models/`，用 `modelscope download --model ... --local_dir ./models/...` 下载（注意 modelscope 目录名中 `/` 转 `___`、`.` 转 `_`，如 `Qwen3___6-35B-A3B-FP8`、`Qwen3-Embedding-0___6B`、`VoxCPM1__5`）。
  4. 每个 `start_*.sh` 支持环境变量覆盖：`HOST_PORT`（端口）、`LOCAL_MODEL_DIR`/`MODEL_PATH`/`VOXCPM_MODEL_PATH`（模型目录）、`CUDA_VISIBLE_DEVICES`/`SPECIFIC_GPU`（GPU 指定）。
- 本地调试：`ssh -fN -L 8900:0.0.0.0:8900 ...` 一次性映射 5 个端口；`curl http://localhost:$p/health` 验证。
- 停止服务：`for p in 8900..8904; do kill $(lsof -t -i:$p); done`。
- 接入 Agent（配置向导或 `env_config.json`）：`models[].base_url=http://localhost:8900/v1`、`ASR_BASE_URL=http://localhost:8901/v1`、`STREAMING_TTS_URL=http://localhost:8902`、`RAG_BASE_URL=http://localhost:8903`、图像生成由 `image_gen` 工具读取 `http://localhost:8904`。也支持任意 OpenAI 兼容云端 API。

### 2. start_llm.sh —— LLM 启动参数（vLLM 推理引擎）

固定 `CUDA_VISIBLE_DEVICES=3`，`VLLM_USE_MODELSCOPE=true`、`MODELSCOPE_DOWNLOAD_MODE=local`、`HF_HUB_OFFLINE=1` 等离线环境变量。vLLM 关键参数：

- `vllm serve <MODEL_DIR>`：`--tensor-parallel-size 1`、`--max-model-len 262144`（26 万超长上下文）、`--reasoning-parser qwen3`、`--enable-auto-tool-choice` + `--tool-call-parser qwen3_coder`（自动工具调用）、`--speculative-config '{"method":"qwen3_next_mtp","num_speculative_tokens":2}'`（MTP 投机解码，2 个投机 token）、`--enable-prefix-caching`、`--max_num_batched_tokens 4096`、`--max_num_seqs 8`、`--kv-cache-dtype fp8_e4m3`（KV 缓存 FP8）、`--chat-template chat_template.jinja`（自定义模板）、`--safetensors-load-strategy eager`、`--served-model-name Qwen/Qwen3.6-35B-A3B-FP8`。

### 3. chat_template.jinja —— ChatML 风格自定义模板

- `enable_thinking` 默认 `false`（`|default(false)`）。
- 有工具时：system 段 = 首条 system 消息（content 为 list 时把 image/audio/video part 替换为 `<|vision_start|><|image_pad|><|vision_end|>`、`<|audio_start|><|audio_pad|><|audio_end|>`、`<|vision_start|><|video_pad|><|vision_end|>` 占位符）+ 固定的 `# Tools\n...` 说明 + `<tools>...</tools>` 内逐条 `tool | tojson` 序列化工具签名；工具调用格式约束为 `<tool_call>\n{"name": ..., "arguments": ...}\n</tool_call>`。
- 无工具时：首条 system 按 content 类型输出多模态占位符或文本。
- **multi_step_tool 检测**（第 47-54 行）：从后往前找第一个"非 `<tool_response>` 包裹"的 user 消息，记为 `last_query_index`，用于判断后续 assistant 是否需要显式输出 `<think>` 块。
- assistant 消息：优先用 `message.reasoning_content`（字符串）；否则若 content 含 `</think>`，用 `split('<think>')`/`split('</think>')` 拆出 reasoning 与正文。`loop.index0 > last_query_index` 且（末条或含 reasoning）时，输出 `<think>...</think>` 包裹的思考段。`tool_calls` 逐个渲染为 `<tool_call>...</tool_call>`。
- tool（函数返回）消息：连续的 tool 消息被**合并进同一个 `user` 角色块**，每条包在 `<tool_response>\n...\n</tool_response>` 中，首条前加 `<|im_start|>user`、末条后加 `<|im_end|>`。
- `add_generation_prompt` 时输出 `<|im_start|>assistant\n`；若显式传 `enable_thinking=false` 则先输出空 `<think>\n\n</think>\n\n`（禁用思考）。

### 4. test_llm.py —— 测试方式

- `python test_llm.py [--url http://127.0.0.1:8900] [--model Qwen/Qwen3.6-35B-A3B-FP8] [--stream]`。
- 非流式 `test_non_stream`：POST `/v1/chat/completions`，打印完整响应 + 提取 model/finish_reason/content/tool_calls/usage（prompt/completion/total tokens）。
- 流式 `test_stream`：`stream=True`，逐行解析 `data: ` 前缀的 SSE，`[DONE]` 结束，累加 `delta.content` 输出。

### 5. start_asr.sh + test_asr.py —— ASR 服务

- **引擎 = vLLM**，模型 **Qwen3-ASR-1.7B**（README 标注；test_asr.py 文档字符串仍引用旧模型 Qwen3-Omni-30B-A3B-Captioner，说明测试脚本是从旧版继承）。启动参数：`--quantization fp8`、`--dtype auto`、`--kv-cache-dtype fp8`、`--max-model-len 16384`、`--allowed-local-media-path /`（允许读取本地媒体路径）、`--tensor-parallel-size 1`、`--gpu-memory-utilization 0.15`（只占 15% 显存）、`--max-num-batched-tokens 4096`；`CUDA_VISIBLE_DEVICES=3`。
- **调用方式**：`test_asr.py --audio <file> [--url http://127.0.0.1:8901/v1/chat/completions] [--base64]`。核心函数 `caption_audio(audio_path, server_url, use_base64)`：
  - 音频转 URL：本地直传用 `file://` + 绝对路径（`/` 分隔）；远程场景 `--base64` 用 `data:<mime>;base64,...`（`file_to_url`）。
  - **不带任何文本提示**，payload 仅一条 user 消息、content 为 `[{"type": "audio_url", "audio_url": {"url": audio_url}}]`（音频描述式 ASR，模型输出整段音频内容的描述/转写）。
  - 用 `soundfile`（回退 librosa）检查时长，>30s 打警告（建议裁剪到 ≤30s）。`timeout=120`，取 `result["choices"][0]["message"]["content"]`。

### 6. streaming_tts_server.py —— 流式 TTS 服务器（FastAPI + VoxCPM）

- **引擎 = OpenBMB VoxCPM**（`from voxcpm import VoxCPM`，README 注释"Whispera 同款"）。`DEFAULT_MODEL_PATH=models/VoxCPM1__5`，`DEFAULT_PORT=8902`。
- 音色克隆：`DEFAULT_PROMPT_WAV=reference_audio.wav` + `DEFAULT_PROMPT_TEXT="日子缓缓前行，不必急于追赶…"`，每次合成都克隆该音色；音频质量参数 `DEFAULT_CFG_VALUE=1.5`（音色贴合度）、`DEFAULT_INFERENCE_STEPS=15`（推理步数）。
- 单例与并发控制：`_get_model(model_path)` 线程安全惰性加载（`_singleton_lock`，`enable_denoiser=False, optimize=True`，采样率取 `model.tts_model.sample_rate`，默认 24000Hz）；`_model_lock` 全局模型锁（VoxCPM 只允许单线程）；`cancel_current_and_set(new_request_id)` 在**新请求到达时自动取消旧请求**（设置 cancel Event，并强制释放被旧请求持有的模型锁）；`set_cancel`/`is_cancelled` 请求级取消标志。
- 端点：
  - `POST /stream_tts`：body `{"text": ..., "request_id": ...}`（缺省 request_id 自动生成 `tts-{ms}`）。返回 `StreamingResponse(media_type="text/event-stream")`，头带 `Cache-Control: no-cache`、`X-Accel-Buffering: no`。空文本直接返回 `audio.error`。
  - `POST /cancel_tts`：`{"request_id": ...}` 取消指定合成。
  - `GET /health`。
- **流式音频块格式（SSE，`_build_sse` 为 `data: {json}\n\n`）**：
  - `audio.start`：`{type, request_id, sample_rate, audio_format: "pcm_f32le"}`。
  - `audio.chunk`：`{type, request_id, index, num_samples, sample_rate, data: base64(PCM float32 LE 字节)}` —— `np.asarray(chunk, float32).ravel()` → `tobytes()` → base64；生成循环中检查 `is_cancelled`，取消则发 `audio.cancelled` 并 return。
  - `audio.done`：`{type, request_id, total_samples, interrupted: false}`。
  - `audio.error`：`{type, request_id, message}`（模型加载失败、等锁超时 3 次等）。
  - 模型调用：`model.generate_streaming(text=text, prompt_wav_path=..., prompt_text=..., cfg_value=..., inference_timesteps=..., retry_badcase=False)`。
- **关于"分句"**：本文件**没有显式分句逻辑**——整段 text 一次性交给 `generate_streaming`，由 VoxCPM 内部流式产出音频块（docstring 说"按句分块合成"是沿用旧设计的注释；`test_tts.py` 里读取的 `num_segments`/`total_segments` 字段服务器实际并不发送，客户端读到默认值）。真实分句若需要，应在客户端或未来版本做文本切分。
- 启动：`uvicorn.run(app, host="0.0.0.0", port=args.port)`；lifespan 启动时预加载模型。

### 7. start_streaming_tts.sh + test_tts.py

- 启动脚本：`VOXCPM_MODEL_PATH` 可覆盖（默认 `models/VoxCPM1__5`）；依次尝试 `../myenv`、`../../myenv` 激活虚拟环境；`CUDA_VISIBLE_DEVICES` 默认 3；`exec python streaming_tts_server.py --port --model-path`。
- 测试脚本：健康检查 → `POST /stream_tts`（`stream=True, timeout=300`）→ 逐行解析 `data: ` SSE → 按事件类型处理：`audio.start` 取 sample_rate；`audio.chunk` 累积 base64 解码的 PCM、进度打印（idx%5==0）；`audio.done` 汇总；`audio.error` 退出；`audio.cancelled` break。结束后计算 RTF（耗时/音频时长，<1 即比实时快）。`_save_wav`：f32 → `(arr*32767).clip(-32768,32767).astype(int16)` 写 16-bit 单声道 WAV；`_play_pcm` 用 pyaudio 播放。实测产物 `test_output.wav` 已存在。

### 8. rag_server.py —— RAG 服务器（FastAPI + Transformers）

- **框架**：FastAPI + `modelscope.AutoTokenizer/AutoModel/AutoModelForCausalLM`（无 LangChain/RAG 框架，纯手写检索基座）。
- 模型路径：`EMBED_MODEL_PATH=models/Qwen/Qwen3-Embedding-0___6B`、`RERANK_MODEL_PATH=models/Qwen/Qwen3-Reranker-4B`。
- 加载（`@app.on_event("startup")` `load_models`）：Embedding 用 `AutoModel.from_pretrained(..., device_map="auto", dtype=torch.float16)`（fp16，未量化，注释里 8-bit 被禁用）；Reranker 用 `AutoModelForCausalLM.from_pretrained(..., quantization_config=BitsAndBytesConfig(load_in_8bit=True), device_map="auto", dtype=torch.float16)`。
- 工具函数：`last_token_pool`（取每条样本最后有效 token 的 hidden state，兼容左/右 padding）、`get_detailed_instruct`（query 拼 `Instruct: {task}\nQuery:{query}`，**document 不加指令**）、`format_rerank_instruction`（`<Instruct>: ...\n<Query>: ...\n<Document>: ...`，默认 instruct 文本 "Given a web search query, retrieve relevant passages that answer the query"）。
- Reranker 技巧：预编码固定 prefix/suffix（ChatML system+user 头、assistant 尾带空 think），`max_rerank_length=32768`；取 `logits[:, -1, :]` 中 `"yes"`/`"no"` 两个 token id 的 logit，`log_softmax([false, true])` 后取 true 的 `exp` 作为得分（生成式 rerank）。
- **API 端点**：
  - `POST /embed`：`{task_description, queries: [...], documents: [...]}` → `{query_embeddings, doc_embeddings}`（L2 归一化，queries 在前 documents 在后拼 batch）。
  - `POST /rerank`：`{task_description, query, documents}` → `{scores: [...]}`。
  - `GET /health`。
- 启动：`start_rag_server.sh` 用 `uvicorn rag_server:app --host 0.0.0.0 --port 8903 --workers 1`（离线环境变量 + `CUDA_VISIBLE_DEVICES=3`）。测试：`test_rag.py` 依次测 health/embed/rerank，打印向量维度与得分。

### 9. image_gen_server.py —— 图像生成服务器（Diffusers）

- **模型 = Tongyi-MAI/Z-Image-Turbo**（README：基于 Diffusers，9 步推理出 1024×1024；代码默认 `num_inference_steps=11`）。`LOCAL_MODEL_DIR` 环境变量优先本地路径，否则回退远程 model id；`SPECIFIC_GPU` 直接写 `CUDA_VISIBLE_DEVICES`。
- 加载：`DiffusionPipeline.from_pretrained(MODEL_PATH, torch_dtype=torch.bfloat16(if cuda), low_cpu_mem_usage=False, trust_remote_code=True)`；本地路径时 `local_files_only=True`；惰性单例 `_get_pipe()` + `_pipe_lock`。
- **`POST /generate`**：入参 `prompt`（必填）、`negative_prompt`、`height/width`（默认 1024，**须为 64 的整数倍**且 ∈[256,2048]）、`num_inference_steps`（默认 11）、`guidance_scale`（默认 0.0）、`seed`（-1 随机，≥0 用 `torch.Generator(device).manual_seed`）、`return_format`（`base64` 默认 | `url`）。响应 `{success, image: base64-PNG 或原始 PNG 流, format:"png", width, height, elapsed_seconds}`。`GET /health`。启动时 lifespan 预加载模型。

---

## 二、`C:\Users\86166\Desktop\Agent_Learning_minor\Agent\src\agent\cron\`（定时任务子系统）

### models.py —— 数据模型（3 个 dataclass + 类型别名）

- `TriggerType = Literal["cron","interval","once"]`；`TaskStatus = Literal["pending","running","completed","failed","expired","disabled"]`；`TriggerSource = Literal["schedule","manual"]`。
- `Trigger`（触发配置）：`type`（默认 "cron"）、`cron`（标准 5 段 cron 表达式如 `"0 9 * * *"`）、`interval_seconds`、`run_at`（once 的目标本地时间 ISO）。有 `to_dict`/`from_dict`。
- `ExecutionLog`（单次执行记录）：`started_at`、`ended_at`、`status`、`error`、`trigger`（schedule/manual）、`turn_id`（关联工具调用记录）。
- `CronTask`（任务完整定义）：`task_id`（时间戳风格，与 session_id 同构）、`name`、`prompt`（触发时投递给 Agent 的提示词）、`trigger`、`enabled`、`timeout_seconds`（默认 300）、`created_at`、`next_run_at`、`last_run_at`、`last_status`、`last_error`、`executions: list[ExecutionLog]`。`summary()` 返回不含 executions 全量的精简 dict（附 `executions_count`）供前端列表。
- `now_iso()`：`datetime.now().strftime("%Y-%m-%dT%H:%M:%S")`（无时区，与前端一致）。

### scheduler.py —— 调度器（CronScheduler 单例）

- 常量：`_SCAN_INTERVAL = 5.0`（扫描周期秒）、`_CRON_TIME_PERIOD_MINUTES = 30.0`（时段长度，同一时间段只允许一个任务运行，全局并发=1；由 `env_config.json` 的 `CRON_TIME_PERIOD_MINUTES` 配置）。
- `_load_time_period_minutes()` / `get_cron_time_period()` / `set_cron_time_period(minutes)`：读取/热更新时段长度并持久化到 env_config.json（`save_env_config`）。
- `_parse_iso(dt_str)`：解析 `%Y-%m-%dT%H:%M:%S`，失败 None。
- `_compute_next_run(trigger, now)`：cron → `croniter(trigger.cron, now).get_next(datetime)`（异常返回 ""）；interval → `now + timedelta(interval_seconds)`；once → `run_at` 若未来，否则 ""（不再调度）。`compute_next_fire` 包装为 datetime。
- `detect_time_period_conflict(trigger, exclude_task_id=None)`：计算候选任务下次触发时刻，与所有 enabled 任务（排除自身）的下次触发时刻求**绝对差 < 时段长度 → conflict=True**，返回 `{"conflict", "conflict_with": [name...], "period_minutes", "next_fire"}`。供前端 check-conflict API 与 cron_manager 工具复用。
- `CronScheduler`（`get_instance()`/模块级 `get_scheduler()` 单例）：
  - 状态：`_thread`、`_stop_event`、`_running_procs: dict[task_id, Popen]`、`_procs_lock`、`_app_start_time`、`_started`、`_period_start_ts`（当前占用时段起点，None 空闲）。
  - `start()`：启动 daemon 线程 `cron-scheduler` 跑 `_run_loop`；`shutdown()`：set stop、terminate 所有子进程、join 3s。
  - `_run_loop`：先 `_on_startup()`（启动扫描），再每 5s `_scan_once()`。
  - `_on_startup`/`_handle_startup_task`（错失/过期处理）：once 目标已过且从未成功 → 追加 `expired` 执行记录并 `update_status(...,"expired", error="App was not running, missed execution time", next_run_at="")` + `enabled=False` 禁用；cron 若 `next_run_at < app 启动时间` → 记 expired 执行记录并推进 `_compute_next_run(trigger, now)`；interval 直接推进到 now+interval。
  - `_scan_once`：遍历 enabled 任务，`next_run_at <= now` 且不在 `_running_procs` → `_spawn(task, trigger_source="schedule", started_iso=now_iso_str)`。
  - `_get_python_and_cwd`：Python 解释器优先 `env_config.json` 的 `USER_PYTHON_PATH`（文件存在才用），否则 `sys.executable`；cwd = `agent/cron/storage.py` 的 `parents[2]`（即 src 目录）。
  - `_spawn(task, trigger_source, started_iso, prompt=None)`：**时段 gate** —— 锁内检查 `_running_procs` 非空或 `now - _period_start_ts < 时段秒数` 则跳过；否则占用新时段 `_period_start_ts = now_ts`。命令：`[py, "-m", "agent.cron.runner", "--task-id", ..., "--prompt", use_prompt, "--trigger", trigger_source, "--timeout", str(task.timeout_seconds)]`；env 注入 `PYTHONPATH=cwd`；Windows 用 `CREATE_NEW_PROCESS_GROUP`。spawn 失败 → `update_status(...,"failed", error="Failed to spawn subprocess: ...")` 并释放时段。成功后 `update_status(...,"running", last_run_at=started_iso)`，起 daemon 线程 `_monitor_proc`。
  - `_monitor_proc`：`proc.wait()` 回收；**子进程自身会 POST `/api/cron/internal/finished` 回传终态，本线程仅兜底**——若 `last_status` 已是 completed/failed/expired 则不覆盖；否则按 exit code 推断（0→completed，非 0→failed `Subprocess exited abnormally (exit code N)`），并补记 execution。
  - `spawn_now(task_id, prompt=None)`：手动立即运行/追问（trigger=manual，prompt 可覆盖原任务提示词）；`is_running(task_id)`；`kill_task(task_id)`（terminate）；`reload_task(task_id)`（配置变更后重算 next_run_at，供 cron_manager 工具调用）。

### runner.py —— 子进程执行器（`python -m agent.cron.runner`）

- 回传地址常量：`_MAIN_HOST="127.0.0.1"`、`_MAIN_PORT=8765`、`_LIVE_URL=http://127.0.0.1:8765/api/cron/internal/live`、`_FINISHED_URL=http://127.0.0.1:8765/api/cron/internal/finished`。
- `_redirect_storage_roots(task_id)`（**必须在构建 runtime 前调用**）：把三个模块的全局根目录显式覆盖到 cron 目录，并把统一存储作用域切到 "cron"：
  - `agent.utils.agent_utils.SESSIONS_ROOT = CRON_ROOT`（turn 文件/session_dir/get_history）
  - `agent.history.tool_call_recorder.TOOL_CALLING_ROOT = Path(CRON_ROOT)`（tool_*.json、token）
  - `web.ui_session.SESSIONS_ROOT = CRON_ROOT`（turn relpath 计算）
  - `agent.core.storage.set_storage_scope("cron")`（消息/工具调用记录直写 cron 作用域：CRON_ROOT 文件或 cron_* 表，**无需执行后的文件→DB 桥接**）
  - 任务目录 `task_dir = CRON_ROOT/{task_id}` 并 mkdir。
- `_start_live_forwarder(task_id)`：后台线程 `cron-live-{task_id}` 订阅 `subscribe_live(task_id)`，把每个快照 `POST {"task_id": task_id, "snapshot": snapshot}` 到 `_LIVE_URL`（timeout=5，失败不阻塞），返回 stop Event。
- `_post_finished(task_id, status, error, turn_id)`：POST `{"task_id","status","error","turn_id"}` 到 `_FINISHED_URL`（timeout=10，失败仅打印）。
- `_run_with_timeout(func, timeout)`：daemon 工作线程执行，`done.wait(timeout)` 判超时；超时返回 `(None, None, True)`（Python 无法杀线程，靠子进程随后 `sys.exit` 一起销毁）；异常 `(None, exc, False)`；成功 `(value, None, False)`。
- `_classify_runner_error`：复用 `agent.core.runtime._classify_error`。
- `main()` 流程：
  1. 解析 `--task-id/--prompt/--trigger/--timeout`（timeout 下限 10s）→ `_redirect_storage_roots(task_id)`，失败则 `_post_finished(failed, "存储初始化失败...")` 返回 1。
  2. `agent.core.workspace_policy.mark_headless()`：无人值守标记，approval 模式退化为拦截（待审批项随进程退出丢失）。
  3. `build_all_agent_runtimes()` + `get_main_agent_runtime()`，无主 Agent → failed。
  4. `_start_live_forwarder(task_id)`。
  5. `execute_runtime_agent(runtime=runtime, chat_history=[{"role":"user","content":prompt}], session_id=task_id, agent_mode="cron")`（直接走 core.runtime，绕开 {"agent","plan"} 归一化），包 `_run_with_timeout`；超时→failed"任务超时"；异常→`_classify_runner_error`；正常完成时检查最后一条 assistant content 是否以错误前缀开头（`"OOM:"、"执行过程中出现错误"、"API Key"、"无法连接"、"指定的模型"、"模型服务端"、"对话内容超过"、"API 调用频率"、"Agent 执行轮数超过限制"`）→ 判定 failed。
  6. `stop_forwarder.set()` → `get_last_turn_id(task_id)` 取 turn_id → `_post_finished(task_id, status, error_msg, turn_id)` → `sleep(0.3)` 给转发线程发最后快照 → 返回 0/1。

### storage.py —— 转发层

纯转发到 `agent.core.storage`：导出 `CRON_ROOT`、`TaskConfigRepository`、`ConversationRecordRepository`、`get_task_repository`、`new_task_id`、`set_storage_scope`、`get_storage_scope`；并自定义 `get_record_repository()` = `_get_core_record_repository(scope="cron")`（固定返回 cron 作用域记录仓库：`cron_messages`/`cron_tool_calls` 表或 `history/cron` 下 JSON 文件，按 `STORAGE_BACKEND` 选择 json/mysql）。

### live.py —— 主进程侧实时流中继

- 子进程无法直接与前端建 SSE，故经 HTTP 回传主进程后由本模块按 task_id 分发。
- `_cron_live_subs: dict[task_id, list[Queue]]` + `_subscribers_lock`。
- `subscribe(task_id)`/`unsubscribe(task_id, q)`：每任务订阅者队列（maxsize=64）。
- `push_snapshot(task_id, snapshot)`：向所有订阅者 `put_nowait({"type":"update","data":snapshot})`（队列满丢最旧）。
- `push_finished(task_id, payload)`：推 `{"type":"finished","data":payload}`，前端据此重载消息并刷新状态。
- 快照格式与 `tool_call_recorder._build_live_snapshot` 一致：`{tool_calls, reflections, started_at}`（前端复用 toolcalls.js 渲染）。

### __init__.py

包说明：Cron 模式与 Edit/Chat 模式并列，通过子进程隔离执行；子模块 roles：models/storage/scheduler/runner/live。

### ★ cron 与主进程的通信机制（总结）

1. **调度**：主进程 FastAPI lifespan 启动 `CronScheduler`（daemon 线程）→ 5s 扫描 → `subprocess.Popen([py, "-m", "agent.cron.runner", ...])` 拉起子进程。
2. **子进程 → 主进程**（HTTP 回传，主进程固定监听 127.0.0.1:8765）：
   - `POST /api/cron/internal/live`：`{task_id, snapshot}` → 主进程 `cron.live.push_snapshot` → 分发给前端 SSE 订阅者。
   - `POST /api/cron/internal/finished`：`{task_id, status, error, turn_id}` → 主进程 finished handler 更新任务状态（scheduler `_monitor_proc` 以此为兜底依据，不重复覆盖终态）。
3. **主进程 → 前端**：SSE（cron live 订阅队列），前端收 `update`/`finished` 事件。
4. 存储天然隔离：子进程把 `SESSIONS_ROOT`/`TOOL_CALLING_ROOT`/`ui_session.SESSIONS_ROOT` 重定向到 `history/cron/{task_id}/`，且统一存储 scope="cron"，无需桥接导入。

---

## 三、`C:\Users\86166\Desktop\Agent_Learning_minor\Agent\src\agent\tts\streaming_client.py`（流式 TTS 客户端）

- `TTSEvent` dataclass：`type`（audio.start | audio.chunk | audio.done | audio.error | audio.cancelled）、`request_id`、`index=0`、`num_samples=0`、`sample_rate=24000`、`data: bytes|None`（**PCM f32le 原始字节**，已由 base64 解码）、`message=""`。
- `StreamingTTSClient(base_url="http://localhost:8902")`：
  - `stream_tts(text, request_id="")` → **Generator[TTSEvent]**：`requests.post(f"{base_url}/stream_tts", json={"text","request_id"}, stream=True, timeout=300)`；`resp.raise_for_status()`；`resp.iter_lines(decode_unicode=True)` 逐行，跳过非 `data: ` 行；`json.loads(line[len("data: "):])`，解码失败 continue；按 payload 字段构造 `TTSEvent`，`data=_decode_pcm_b64(payload.get("data"))`；`yield evt`。
  - `cancel_tts(request_id)` → bool：POST `{base_url}/cancel_tts`（timeout=5），200 即成功。
- `_decode_pcm_b64(b64_data)`：base64 解码失败返回 None。

---

## 四、`C:\Users\86166\Desktop\Agent_Learning_minor\Agent\src\agent\utils\`（工具函数集）

### env_utils.py —— 环境变量加载与全局配置

- `_get_env(name, default, cast, required)`：读 os.environ，支持必填校验（缺失抛 `EnvironmentError`）与类型转换（失败抛 `ValueError`）。
- 配置加载链：`_load_config()` 优先 `agent.core.config_manager.load_env_config()`（单一数据源），把非 `models` 键写入 `os.environ`，并从 `models[0]` 提取 `api_key/base_url/model/timeout` 写入 `LLM_API_KEY/LLM_BASE_URL/LLM_MODEL/LLM_TIMEOUT`；config_manager 不可用时回退直接读 `src/agent/config/env_config.json`；最后 `_refresh_globals()`。模块导入时执行 `_load_config(); _refresh_globals()`。
- `_refresh_globals()` 定义的模块级常量（均可用环境变量覆盖）：
  - 路径：`WORKING_DIR`（相对路径转绝对）、`WORKSPACE_DIR`、`USER_PYTHON_PATH`。
  - LLM：`LLM_BASE_URL`/`LLM_API_KEY`/`LLM_MODEL`（**required=True**）、`LLM_TIMEOUT`（默认 60.0）、`LLM_CONTEXT_WINDOW`（默认 262144）。
  - 多模态服务：`STREAMING_TTS_URL`、`ASR_BASE_URL`、`RAG_BASE_URL`（三者均为可选，对应 llm_server 的 8902/8901/v1、8903）。
  - 压缩/图像：`COMPRESS_RATE`（0.6）、`IMG_SIZE`（768）、`RAG_CHUNK_SIZE`（500）、`RAG_CHUNK_OVERLAP`（50）、`GROUNDING_WIDTH/HEIGHT`（1000）、`SEND_FILE_SIZE_LIMIT`（30MB）。
- **THINKING_LEVELS 各档位**（`("low","high","xhigh","max","ultra")`，默认 `"low"`；非法值回退 low）：
  - `low` = agent 模式 + 不思考；`high` = plan 模式 + 不思考；`xhigh` = agent 模式 + 思考；`max` = plan 模式 + 思考；`ultra` 为未来 react→审批图预留占位，暂按 "agent+思考" 处理。
  - `_THINKING_ENABLED_LEVELS = {"xhigh","max","ultra"}`。
- `thinking_enabled(level=None)`：档位是否启用深度思考。
- `get_thinking_extra_body(level=None)`：思考开启返回 `{}`（恢复模型原生行为=启用思考）；否则返回 `None`（禁用思考，默认）。该 extra_body 注入 `Multimodel_LLM`。
- `reload_config()`：热重载并刷新全局（调用方须 `import agent.utils.env_utils as env_utils` 访问属性，`from ... import` 会绑定旧值）。
- `BROWSER_MAP`：edge/chrome/firefox/safari/opera/brave → (可执行名, 显示名)。
- `get_workspace_dir()`：WORKSPACE_DIR 绝对化（相对则相对 WORKING_DIR），缺省回退 WORKING_DIR，确保目录存在。
- `get_venv_dir()`：由 `USER_PYTHON_PATH`（`.../Scripts/python.exe`）取上级目录。

### agent_utils.py —— 会话/历史/附件/文档核心工具

- 常量：`AUDIO_FILE_EXTENSIONS`（wav/mp3/flac/ogg/m4a/aac/wma/opus/aiff/ape/amr/au）、`DOC_EXT_MAP`（txt/json/md/cpp/c/java/m/html/svg→plain_text；docx→docx；pptx→pptx；pdf→pdf；csv/xlsx/xls→tabular）、**路径**：`HISTORY_ROOT = src/agent/history`、`SESSIONS_ROOT = history/sessions`（启动即 mkdir）。
- `JsonChatMessageHistory(session_id)`（替代 SQLite）：基于 turn 文件读写 LangChain 消息，`_load()` 用 `load_all_turn_messages`，`_dict_to_langchain` 把 user/assistant 条目转 HumanMessage/AIMessage；`get_history(session_id)` 返回实例。
- session_meta：`_load_session_meta`/`_save_session_meta`（经 `session_storage.load_session_extra/save_session_extra` 的 `"agent_meta"` 键）；`get_session_meta(session_id, agent_name)` → `{cursor_index, compressed_content}`；`update_session_meta` 写入。
- **动态尾部长期记忆**：`update_session_dynamic_tail(session_id, agent_key, text, max_entries=100)` —— 存 `dynamic_tail_history` 列表，连续相同内容去重，超出上限丢最旧；`get_session_dynamic_tail_history` 读取（时间正序）。用于 TodoList 状态/循环提醒长期记忆，与 compressed_content 合并保存不覆盖（前缀缓存友好：变化部分在消息末尾）。
- `build_tool_history_messages(session_id, agent_key="main")`：读 cursor_index，把压缩游标**之后**所有轮次工具调用构造成 synthetic HumanMessage（`additional_kwargs={"synthetic":True,"tool_ctx":True}`，`id=f"tool_ctx_{idx}"` 供压缩节点 RemoveMessage 精确移除），内容 `[历史工具调用] {name}({args[:300]}) → {result[:500]}`。
- Turn 存储：`TURN_JSON_PREFIX="turn_"`；`turn_files_dir(session_id, turn_id)` = `sessions/{sid}/{turn_id}/files`；`save_turn_messages`（→ `session_storage.save_turn`，后端无关，附件二进制由调用方落盘）；`load_all_turn_messages`；`delete_turns_after(session_id, keep_until_turn_id)`（按目录名排序删除 > keep 的 turn 目录 + 存储记录，**keep 自身保留**）；`get_last_turn_id`；`session_dir(session_id)` = `sessions/{sid}`。
- pending turn_id：`set_pending_turn_id`/`take_pending_turn_id`（跨请求共享，`_pending_turn_ids` dict + 锁，仅取一次）。
- `summarize_chat_text(llm, chat_text)`：`ChatPromptTemplate(SUMMARY_SYSTEM_PROMPT + 压缩指令) | llm`，`config={"metadata":{"output_type":"text"}}`，供 in-loop 压缩节点复用。
- `assistant_text(value)`：str/list/dict 多形态归一为纯文本（dict 依次尝试 text/content/input/output/query/answer/result 键，失败 json.dumps）。
- `make_attachment_text(category, file_path, extra="")`：生成附件描述文本——图片（含尺寸 `[用户提供了图片，文件路径: ...，尺寸: ...]`）、音频（路径 + extra）、有 extra 时直接返回 extra（如 ASR 结果/文档内容）、附件文件/通用格式。
- `Documents_process`（静态方法类）：`doc_classify(file_path)` 按扩展名+MIME 返回 `plain_text|docx|pdf|image|audio|tabular`（不支持抛 ValueError）；`process_plain_text`（UTF-8 读取）；`process_docx`（python-docx，按文档顺序遍历段落/表格，run 中提取 `<image>N</image>` 占位与图片字节，表格转 `<table>`，支持"表1/图1"短标题缓存合并）；`process_pdf`（pypdf，逐页文字 + `<image>N</image>` 占位 + 图片字节）；`process_pptx`（python-pptx 提文字 + `ppt_utils.convert_pptx_to_svg` 提布局，SVG 内 base64 data URL 替换为 `#[内嵌图片 N]` 占位，输出 `<slide>N</slide>[文字][布局]` 结构）；`process_tabular`（csv → `<table>Sheet1...`；xlsx openpyxl 多 sheet；xls xlrd 日期转可读）；`process_image`/`process_audio`（读字节，文本为空）；`process(file_path)` 统一分发入口（供 `core/llm._preprocess_messages` 调用）。
- `audio_file_to_text(audio_path)`：**ASR 调用链** —— 非 wav 先用 pydub `AudioSegment.from_file` 转临时 wav（`tempfile.mkstemp(prefix="asr_", suffix=".wav")`）；读字节 → base64 → `data:audio/wav;base64,...`；payload `messages=[{role:user, content:[{"type":"audio_url","audio_url":{"url": data_url}}]}]`；POST `{ASR_BASE_URL.rstrip('/')}/v1/chat/completions`（timeout=120）；返回 `choices[0].message.content.strip()`；finally 删除临时 wav。
- **附件存储规则（归纳）**：
  - 用户上传附件：`web/ui_session._rewrite_user_files_to_dir` 把外部文件 `shutil.copy2` 复制到 `SESSIONS_ROOT/{session_id}/`（会话根目录），命名 `{清洗后文件名主干}_{session_id}_{递增序号}{ext}`（`_next_session_copy_name`）；已在该目录内的跳过。
  - 单 turn 附件目录：`turn_files_dir` = `sessions/{sid}/{turn_id}/files`。
  - 工具产物（tool_call_recorder）：直接写 `TOOL_CALLING_ROOT/{session_id}/`，命名 `_artifact_{工具名}_{序号}.png`（图片）、`_file_{工具名}{序号}{ext}`（send_file 文件），音频不落盘只存路径元信息。

### image_utils.py —— 图片多模态适配

- `IMAGE_FILE_EXTENSIONS = {.png,.jpg,.jpeg,.bmp,.gif,.webp,.ico}`。
- `resize_image_if_needed(image_path_or_bytes, max_size=IMG_SIZE=768)`：超长边等比缩放（LANCZOS）；RGBA/LA 透明图贴白底后转 JPEG；JPEG quality=70 + optimize + progressive，PNG 走 optimize。
- `image_to_base64`：路径/字节 → base64（失败 None）。
- `_mime_from_magic`：按魔数判 jpeg（`FFD8`）/png（`\x89PNG`）/gif，默认 jpeg。
- `image_bytes_to_openai_image_url_part(image_bytes, detail=None)` / `image_path_to_openai_image_url_part(file_path, detail=None)`：统一返回 `{"type":"image_url","image_url":{"url": "data:{mime};base64,...", "detail": 可选}}`。供 `core/nodes.process_tool_artifact`（工具截图注入对话）与 `core/llm`（用户上传图片）使用。

### tool_call_utils.py —— 工具执行钳点

- `_invoke_with_timeout(tool, tool_call_input, timeout)`：daemon 线程执行 `tool.invoke`；**用 `contextvars.copy_context()` 把调用方上下文（session/turn、agent 名称、sub_agent_context、tool_call_id 等 ContextVar）复制进线程**（保证并行工具/子 Agent 隔离）；`t.join(timeout)`，超时返回 None；工具异常在主线程 re-raise（保留 ABORTED_BY_USER 冒泡）。
- `invoke_tool_and_build_message(tool, tool_name, tool_args, tool_call_id="", timeout=None)` → `(content, artifact)`。**工具执行前的唯一钳点，顺序**：
  1. **工作空间越界拦截**：`workspace_policy.decision(tool_name, tool_args) == "block"` → 直接返回 `build_block_message(tool_name, tool_args)`（策略模块异常不阻断执行）。
  2. **人工确认钳点**（human_interaction 除外）：`classify_tool_execution(...)=="confirm"` 或 workspace decision=="approve"（附 `check_violation` 说明）→ `ask_human(session_id, meta)`，meta 含 `{type:"tool_call", title:"待确认执行工具：{name}", args, instruction, options:["approve","reject","skip"], policy_note, agent_name, is_sub_agent, resolved:false}`；decision reject/skip → 返回 `"用户拒绝/已跳过此工具调用（{name}）：{hint}"`；timeout → `"等待用户确认超时，未执行工具"`；approve 继续。`RuntimeError`（ABORTED_BY_USER）向上冒泡。
  3. 超时取值：显式 timeout > `config_manager.get_tool_timeout(tool_name)`（缺省 `DEFAULT_TOOL_TIMEOUT` 300）。
  4. `human_interaction` 为阻塞工具**绕过超时包装直连 invoke**（内部 ask_human 的 ABORTED_BY_USER 直接冒泡 runtime 按暂停处理）；其余走 `_invoke_with_timeout`，`None` → `"工具执行超时（{n}s）"`。
  5. 返回归一化：ToolMessage → (content, artifact)；tuple → (str(t0), t1)；否则 str(result)。
- `json_safe(value)`：递归转 JSON 可序列化（UUID→str、datetime→isoformat、dict/list/tuple 递归、其余 str）。
- `normalize_tool_call(tool_call)`：兼容 dict 或对象，args 为 JSON 字符串时解析（失败 `{"raw": args}`），输出固定 `{"id","name","args"}`。供 `core/routing` 判断工具执行策略/提取待确认项。
- `split_inline_thinking(text)`：按**最后一个** `</think>` 拆分（兼容 `"思考\n</think>\n\n回复"` 与 `<think>思考</think>回复`），返回 (thinking, reply)；无标记 → ("", text)。
- `extract_reasoning_text(msg)`：思考开启（xhigh/max/ultra）优先 `additional_kwargs.reasoning_content`，其次 content 内联 `<think>` 块；思考关闭（low/high）content 即一句话反思直接返回。供 nodes 与 tool_call_recorder 提取思维链。
- `format_args_summary(args, max_len=80)`：`json.dumps(default=str)` 截断 + "..."，供死循环检测与记录展示。

### ppt_utils.py —— PPT 读取/预览（仅 pptx→SVG，不生成 PPT）

- 模块头明确：**原先 svg→pptx 制作路线已移除**，仅保留 PPT 读取/解析与预览渲染（自研 PPTX 解析，不依赖外部 ppt-master 项目）。
- 常量：`EMU_PER_INCH=914400`、`EMU_PER_PX=9525`、`HUNDREDTHS_PT_PER_PX=75`、`ANGLE_UNIT=60000`；XML 命名空间 NS_A/NS_P/NS_R/NS_REL/NS_SVG；`_ns`/`_etree_fromstring`。
- 单位换算：`emu_to_px`、`px_to_emu`、`fmt_num`（去尾零）。
- 颜色：`_resolve_srgb`（`srgbClr`→`#RRGGBB`）、`_find_color_elem`、`_resolve_color`（srgbClr/schemeClr/sysClr/prstClr + alpha）、`_parse_color_simple`。
- `OoxmlPackage(pptx_path)`：zipfile 打开，读 `_rels/.rels` → presentation.xml（`sldSz` 取画布尺寸 px）→ `sldIdLst` 按顺序列出 slide → 每 slide 解析 layout/master 链（`_resolve_related`）；`resolve_theme(master)` 从 master→theme 的 `clrScheme` 取主题色映射；`iter_slides`/`read_media`/`close`（支持 with）。
- `Xfrm`（坐标变换）：x/y/w/h/rot/flip_h/flip_v/ch_*（group），`to_svg_transform` 生成 rotate/translate+scale 字符串；`parse_xfrm`。
- 预设几何 `_convert_prst_geom`：rect/roundRect（rx=min*0.05）/ellipse/line。
- `_resolve_fill_svg`：noFill→`fill:none`，solidFill→hex，默认 `#CCCCCC`。
- `_convert_picture`：媒体按扩展名映射 MIME，内联 `data:...;base64` 的 `<image>` 元素（preserveAspectRatio="none"）。
- `_convert_txbody`：bodyPr 内边距/锚点/换行；段落对齐（l/ctr/r→start/middle/end）；run 级 sz（/100 得 px）、b/i、latin/ea typeface、颜色；行高 1.25、y = inner_y + font_size + idx*1.25*font_size；超出形状高度截断；wrap none 加 `white-space:pre`。
- `ShapeNode`（kind: shape/picture/group/graphic）+ `walk_sp_tree`（递归遍历 sp/cxnSp、pic、grpSp、graphicFrame，读 hidden）。
- 主入口 `convert_pptx_to_svg(pptx_path)` → `PptxToSvgResult{slides:[SlideSvgResult{index, svg, media_files}], canvas_px, theme_colors}`：每页画背景 rect → 遍历形状树 `_convert_node` → 组装 `<svg viewBox>`。`_convert_shape_to_svg`/`_convert_pic_to_svg`/`_convert_group_to_svg` 递归实现。

---

## 五、`C:\Users\86166\Desktop\Agent_Learning_minor\Agent\src\agent\memory\system_prompt.py`（提示词体系）

- `_BASE_PROMPT`（基础主提示词，未命名 MAIN_SYSTEM_PROMPT，实际入口为 `get_main_system_prompt()`）：多模态桌面操作助手。要点：理解意图高效完成任务；图片/音频/文件直接多模态分析，**不为此调用截图等无关工具**；只有信息确实无法获取才调工具；拿到工具结果必须观察实际返回继续推进、严禁编造；**同一页面 GUI 连续操作合并为一次 gui_tool 调用（actions 列表），严禁逐个单步**；复杂任务才用 todo_list 拆解并 done_step 标记进度，简单任务直接执行；完成时总结。
- `_WS_TAIL`：`{workspace_dir}` 占位的工作空间配置（代码/脚本/图片默认存工作空间；terminal_execute 默认 cwd；doc_tool 用绝对路径；越界访问拦截或审批）。
- `get_main_system_prompt(workspace_dir=None)` = `_BASE_PROMPT + _reflection_section() + _WS_TAIL`；`set_current_workspace(dir)` 热改 `_current_workspace_dir`。
- `get_cron_system_prompt(workspace_dir=None)` = `CRON_MODE_PROMPT.format(workspace_dir=...) + _reflection_section()`（.format 失败时替换占位符兜底）。
- `SUMMARY_SYSTEM_PROMPT`：Summary Agent 摘要助手（客观准确、抓要点、简洁、保原意；默认压到 20%~30% 或 3~5 句；对话记录总结主题/立场/共识/分歧/行动项；过短回复"内容过短，无法生成有效摘要"；多语言同语言输出）。
- `VISION_SYSTEM_PROMPT`：专业图像理解助手（客观中文描述、命名品牌/时间/地点/人物、多图编号「图1」「图2」、看不清如实说明、结合图片回答问题）。
- `DB_SYSTEM_PROMT`（注意拼写为 PROMT）：PostgreSQL 数据分析助手（只读 SELECT/WITH、先展示表/查结构/验证后执行、结果归纳成人话、安全底线、非 DB 问题直接回复）。
- `_PLAN_CORE_RULES`（Plan 模式核心规则）：任务模糊先 `human_interaction` 确认；计划写入工作空间 `.minorAgent/任务名.md`（目标/步骤/产出物）；`send_file` 发给用户确认，**确认前不得执行**；每步完成 doc_tool 更新 `[x]` 进度；完成总结并告知计划位置。
- `PLAN_MODE_PROMPT = _PLAN_CORE_RULES + "\n\n" + _BASE_PROMPT`；`get_plan_system_prompt` = PLAN_MODE_PROMPT + 反思段 + WS_TAIL。
- `CRON_MODE_PROMPT`：无人值守自主完成；**慎用 human_interaction**（用户大概率不在场）；复杂任务 todo_list；时效性判断（滞后说明/已过时效跳过）；执行汇报（做了什么/关键结果/是否有异常）；**【强制规则】PPT 制作、代码项目等复杂产出或系统操作类任务必须先调 skill_router 查询 Skill 并严格遵循**；可自用 cron_manager 管理定时任务；无人值守越界访问直接拦截。
- `REFLECTION_PROMPT`（固定反思引导）：不需要工具直接回复不输出反思；需要工具先一句话反思再调用；GUI 操作未命中按最新截图重估坐标重试；成功则继续。**gui_tool 批量调用规则**同上（一次 actions 传全部动作）。
- `_reflection_section()`：**思考关闭档位（low/high）注入 REFLECTION_PROMPT 到系统提示词前缀（前缀缓存友好），思考开启档位（xhigh/max/ultra）返回空**（保持模型原生思考语义）。惰性导入 env_utils 防循环依赖。
- `SUB_AGENT_OOM_PROMPT`：`{total_tokens}/{threshold}` 占位，子 Agent 上下文超限时注入——立即停止调用工具、整理进度（已完成/关键结果/问题原因）、直接文字回复主 Agent。
- Skill Router 相关：`SKILL_ROUTER_PROMPT`（从 Skill 列表选 1~3 个，每行一个 name，无匹配输出 NONE）、`SKILL_ROUTER_NO_MATCH_MSG`/`SKILL_ROUTER_EMPTY_MSG`/`SKILL_ROUTER_NO_QUERY_MSG`/`SKILL_ROUTER_NO_SKILLS_MSG`。
- `DEFAULT_SUB_AGENT_PROMPT`（子 Agent 默认提示词）：主 Agent 委派的专业执行助手；专注任务不越权；工作流程（接收→工具逐步完成→清晰摘要→复杂先 todo_list）；关键准则（聚焦/高效/如实/按需用工具/结果导向）；输出格式（简洁概括、分点编号、`[完成]` 标记）。
- `get_default_sub_agent_prompt()` = `DEFAULT_SUB_AGENT_PROMPT + _reflection_section()`。

---

## 六、`C:\Users\86166\Desktop\Agent_Learning_minor\Agent\src\agent\agents\agent_runtime.py`（动态 Agent 工厂 + Web 入口）

- `AgentMode = Literal["agent","plan","cron"]`；缓存 `_all_agent_runtimes: dict[str, AgentRuntime]`、`_main_agent_name`。
- `_build_llm_for_agent(cfg)`：从 `load_models()`（env_config 的 models 列表）按 `cfg.llm_model_id` 找模型配置，构造 `Multimodel_LLM(model, api_key, base_url, timeout, max_retries, extra_body=get_thinking_extra_body())`——深度思考由全局 THINKING_LEVEL 档位控制，取代 per-model enable_thinking 开关；未匹配回退 `build_default_llm()`（优先主 Agent 配置模型）。
- `_build_agent_runtime(cfg)`：① 构建 LLM；② `get_tools()` 全量按 `cfg.tools` 过滤；**主 Agent（role=="main"）强制加载 doc_tool 与 todo_list**（不可移除）；③ `agent_llm.bind_tools(agent_tools, tool_choice="auto")`；④ `build_agent_graph(tools, model_with_tools, trajectory_rounds=cfg.trajectory_rounds)`；⑤ 组装 `AgentRuntime(name, description, graph, llm, tools, tools_by_name, system_prompt, max_iterations, trajectory_rounds)`。
- `_refresh_subagent_tool_description()`：遍历非 main 的 runtime 收集 `sub_names`/`sub_descriptions`，调用主 Agent 中 `CallSubAgentTool._refresh_description(sub_names, sub_descriptions)`，让主 Agent 知晓可委派的子 Agent。
- `build_all_agent_runtimes()`：`load_agent_configs()` 只构建 enabled；第一个 `role=="main"` 记为 `_main_agent_name`；无 main 时自动把第一个设为主；**先刷新 call_subagent 描述，再重建主 Agent**（bind_tools 携带最新子 Agent 列表）。
- 取值函数：`get_main_agent_runtime()`/`get_all_agent_runtimes()`/`get_agent_runtime(name)`（缓存空则自动构建）。
- `reload_all_agent_runtimes()`：清空重建；同步模块级引用 `main_agent_runtime/agent_graph/tools/TOOLS_BY_NAME/llm`；再刷新子 Agent 描述；返回 `{"agents":[{name,description,tools_count,max_iterations}], "main_agent"}`。
- `execute_agent(chat_history, session_id="test", agent_mode="agent")`：**Web/API 层入口**，直接委托 `execute_runtime_agent(runtime=main_agent_runtime, ...)`。
- 模块导入时（底部）即执行 `build_all_agent_runtimes()` 并缓存 `main_agent_runtime/agent_graph/tools/TOOLS_BY_NAME/llm`。

---

## 七、`C:\Users\86166\Desktop\Agent_Learning_minor\Agent\src\agent\history\`（会话/工具调用记录）

### session_storage.py —— 转发层

纯转发 `agent.core.storage`：`ConversationRecordRepository`/`JsonRecordRepository`/`MysqlRecordRepository`（Protocol+实现）、便捷函数 `save_turn`/`load_messages`/`load_turn_messages`/`list_turn_ids`/`save_tool_calls`/`get_turn_record`/`get_latest_turn_record`/`list_turn_records`/`persist_live_records`/`load_session_extra`/`save_session_extra`/`list_session_ids`/`get_last_turn_id`/`delete_turns_after`/`delete_tool_records`/`delete_session`，作用域 `set_storage_scope`/`get_storage_scope`/`get_record_repository`。消费方无需感知 json/mysql 后端。

### tool_call_recorder.py —— 工具调用记录器（live 实时推送 + 持久化）

- 全局：`TOOL_CALLING_ROOT = Path(SESSIONS_ROOT)`（默认 `history/sessions`；cron 子进程改指 CRON_ROOT）。
- 上下文 ContextVar：`_current_turn_id`/`_current_session_id`（带线程安全 fallback `_current_turn_fallback`/`_current_session_fallback`）、`_sub_agent_context`（子 Agent 执行标记）、`_current_tool_call_id`（并行工具隔离）。配套 `set_current_turn`/`get_current_turn`/`set_current_session`/`get_current_session`/`set_current_tool_call_id`/`get_current_tool_call_id`/`is_sub_agent_context`。
- `start_live_turn(session_id)`：turn_id = `datetime.now().strftime("%Y%m%d_%H%M%S")`；`init_live_turn_with_id(session_id, turn_id)`：清空该 session 的 `_live_records`、记 `_turn_start_times`、加 `_active_sessions`、清 pending thinking。
- `record_tool_call_live(session_id, name, args, tool_call_id=None)`：条目 `{id, name, args(JSON安全), args_summary(format_args_summary 40 字符), status:"running", result_text:"", 可选 thinking}`；**消费 pending thinking**（上一条反思附加到本条）；子 Agent 上下文路由到 `_sub_live_records[(session, tool_call_id)]`（隔离 key 取父级 call_subagent 的 tool_call_id，并行/同名子 Agent 互不串扰）；结尾 `_notify_live(session_id)`。
- `record_tool_result_live(session_id, name, result_text, artifact=None)`：从后往前找同名 running 条目 → status="done"、result_text 截 500 字、`result_images`（`_artifact_image_data_urls`：artifact 内 bytes/image_bytes/images 列表/data_url/http URL → data URL 列表）、`result_audio`（`_artifact_audio_info`，仅路径元数据）、`result_file_info`（`_artifact_file_infos`：file/image/folder）；json 后端额外 `_safe_persist_live_records` 增量落盘防崩溃丢失。
- `record_reflection_live(session_id, content)`：写 `_think_store`（去重，summary=content[:60] 换行转空格）并置 pending thinking；子 Agent 上下文只写 `_sub_pending_thinking`（不独立显示，嵌套在各子工具条目的 thinking 中）。`get_live_reflections`/`clear_live_reflections`。
- **订阅推送**：`subscribe_live(session_id)` → Queue(maxsize=64)；`unsubscribe_live`；`_build_live_snapshot(session_id)` = `{tool_calls: get_live_tool_calls(), reflections, started_at, human_requests(惰性导入 human_request)}`；`_notify_live` 向所有订阅者 `put_nowait(snapshot)`（满则丢最旧放最新）。cron 子进程正是复用该 subscribe_live 转发到主进程。
- `get_live_tool_calls(session_id)`：内存优先；空且 session 活跃 → 回退磁盘最近 `tool_*.json`；session 已结束直接返回空（避免跨 turn 残留）；并把 `_sub_live_records` 按 tool_call_id 精确注入 call_subagent/agent_call 条目的 `sub_tool_calls`（无 id 回退"最后一条 running"）。
- `get_turn_started_at(session_id)`：轮次开始时间戳（内存 → 磁盘回退）。
- `end_live_turn(session_id)`：清 turn/反思/pending、清理该 session 所有子 Agent 槽、`_active_sessions.discard`、返回并弹出 `_live_records`。
- `save_aborted_turn(session_id, turn_id)`：Abort 时把内存 live 记录转 save_turn 兼容格式落盘（meta 含 `aborted: True`）。
- `extract_tool_calls_from_messages(messages)`：从图执行结果消息提取完整工具链——AIMessage.tool_calls（首个附加 thinking，`extract_reasoning_text`）→ pending；ToolMessage 配对 → result_text + artifact 落盘（`_save_artifact_files` → `_artifact_{name}_{idx}.png` / `_file_{name}{ext}`）+ result_images/audio/file_info；未配对 pending 标记 done。
- `save_turn(session_id, turn_id, user_message, messages)`：工具调用持久化唯一入口。① extract；② 产物字节直接写 `session_tool_dir(session_id)`；③ 从存储读 live 记录（`get_turn_record`）合并（`_merge_extracted_with_live`：按索引优先、name+顺序回退，从 live 补 thinking/args_summary）；④ `_inject_sub_traces_to_record` 注入子 Agent 轨迹；⑤ `session_storage.save_tool_calls(..., meta={started_at, ended_at, duration})`（轮次级计时，单条工具计时已移除）。
- 读取 API：`list_turns(session_id, limit=5)`（倒序）、`get_latest_turn`、`get_tool_calls_for_latest_turn`、`get_tool_calls_for_turn`、`get_turn_meta`（started_at/ended_at/duration）、`get_thinking_for_turn`（从 tool_calls 各条 thinking 提取链）。
- `_tool_calls_from_turn_record(record, session_id)`：为每条工具调用补 `result_files_full`（`session_tool_dir(sid)/fname` 绝对路径）、`result_images`（`_artifact_*.png` → `/api/tool-image?path=...&session={turn_id}`；仅当 live 无 data URL 时回退）、`result_download_files`（`_file_*` → `/api/tool-file?path=...&session={turn_id}`）、`result_audio.api_url`、`turn_id`。
- 子 Agent 轨迹：`_sub_trace_key = f"{session_id}/{turn_id}/{agent_name}[/{tool_call_id}]"`；`record_sub_agent_trace`/`get_sub_agent_traces_for_turn`（内存 `_sub_traces_store`，并行按 tool_call_id 精确隔离）。
- Token 统计：`set_session_tokens(session_id, total_tokens, breakdown)`（内存 + 经 session extra 持久化；breakdown={messages, tools, system} 估算占比由 `nodes._estimate_token_breakdown` 算）、`get_session_tokens`（内存→磁盘→0）、`get_session_token_breakdown`、`clear_session_tokens`。
- **目录结构（session_tool_dir）**：`history/sessions/{session_id}/` 下：`turn_*.json`（对话消息，由 ui_session 写）、`tool_*.json`（每 turn 工具调用记录 + started_at/ended_at/duration）、`_artifact_*.png`/`_file_*`（工具产物字节）、session extra（`agent_meta` 键含 cursor/compressed_content/dynamic_tail_history，`tokens`/`token_breakdown`）；turn 附件在 `{session_id}/{turn_id}/files/`。cron 场景整体换到 `history/cron/{task_id}/`。

---

## 八、`C:\Users\86166\Desktop\Agent_Learning_minor\Agent\src\web\ui_session.py`（会话 UI 状态管理）

- `_AUDIO_EXTENSIONS = AUDIO_FILE_EXTENSIONS`（别名，向后兼容）；`_memory_session_ids: set[str]`（内存会话 id 缓存防冲突）。
- `session_dir(session_id)` = agent_utils 的 `sessions/{sid}`。
- `list_session_ids_ordered()`：`session_storage.list_session_ids()`（mysql 按 sessions 表 updated_at 倒序；json 扫描目录含 turn_*.json 的按 mtime 倒序）。
- `new_timestamp_session_id()`：`datetime.now().strftime("%Y%m%d_%H%M%S")`，与磁盘+内存已有 id 冲突时追加 `_1`、`_2` 后缀；新 id 加入 `_memory_session_ids`。
- `prune_memory_session_ids()`：把已持久化的 id 从内存集合移除，防无限增长（每次会话操作后调用）。
- `delete_session(session_id)`：删内存缓存 → `shutil.rmtree(session_dir)` + `session_tool_dir` → `session_storage.delete_session`（后端无关）。
- `_build_user_chat_content(query)`：`query={text, files, file_names}` → 多模态 content：图片文件 → `{"type":"image_url","image_url":{"url": filepath}, "name": 原名}`；其余（含音频）→ `{"path": filepath, "name": 原名}`（**音频作为普通文件 part，不再生成 audio part**；麦克风录音由 `/api/chat/start` 阻塞 ASR 转 text，不走此函数）；文本 → `{"type":"text","text": text}`；仅一段纯文本时直接返回 str。
- `_sanitize_filename_stem(name)`：清洗 `<>:"/\|?*` 为 `_`、去尾部空格点、空回退 "file"。
- `_next_session_copy_name(dest_dir, session_id, original_name, ext)`：`{stem}_{session_id}_{max_index+1}{ext}`（扫描目录现有同名前缀取最大序号递增）。
- `_rewrite_user_files_to_dir(user_msg, dest_dir, session_id)`：**附件从临时目录复制到会话目录的核心**——遍历 content list，text 直接保留；对 path/image_url.url/audio_path 源文件：若已在 dest_dir 内跳过；否则 `_next_session_copy_name` 生成唯一名 → `shutil.copy2(src, dest)` → 原地更新 `piece["path"]`（image_url 同时更新 `image_url.url`，audio 更新 `audio_path`）。
- `rewrite_user_message_files_to_session_dir(user_msg, session_id)`：向后兼容包装，dest = 会话根目录。
- `_serialize_user_msg_for_turn(user_msg)`：序列化为 turn 文件 user 条目——str 拆 text part；list 中 text 保留、附件转 `{"type":"image_url"|"file", "relpath": 相对 SESSIONS_ROOT 的路径, "name"}`。
- `_turn_user_entry_to_content(user_entry)`：还原 UI/LLM content——relpath 拼绝对路径并校验在 SESSIONS_ROOT 内；image_url part 文件存在给 `{"type":"image_url","image_url":{"url": abs}, "path", "name"}`，缺失累计 `any_image_missing`；历史 audio part 降级为普通文件；file part 缺失 → `[附件已丢失: name]`；有图丢失补 `[图片已丢失]`；纯文本单段直接返回 str。
- `_serialize_assistant_entry`：`{text, output_type, turn_id}`；voice 输出额外 `autoplay`/`audio_duration_seconds`/`audio_relpath`（相对 SESSIONS_ROOT）。
- `_serialize_message_for_turn(msg)`：按 role 分发 → `{"role":"user","user":...}` / `{"role":"assistant","assistant":...}`。
- `sync_turn_from_chat_history(session_id, chat_history, latest_user_image_description)`：**turn 级消息落盘**——`get_last_turn_id` 得 turn_id；从最后一条 user 消息起截取本轮消息区间；逐条序列化并把 `turn_id` 注入 meta；`save_turn_messages(session_id, turn_id, messages_out)`（内部 → `session_storage.save_turn`）。
- `rollback_turns_from_history(session_id, chat_history)`：从 chat_history 找最后一个 turn_id，`delete_turns_after(session_id, keep_turn_id)` 删除多余 turn 目录。
- `_assistant_turn_entry_to_content`/`_assistant_turn_entry_to_message`：还原 assistant 消息（text/voice → `{"type":"text"}` + `{"type":"audio","audio_path","autoplay","duration_seconds"}`，meta 含 output_type/autoplay/pending_action/turn_id/audio{path,format:"wav",sample_rate:24000}）。
- `_load_ui_messages_from_turn(session_id)` / `load_ui_messages_for_session(session_id)`：从 turn 文件重建 UI 消息列表（无数据返回空列表）。
- `rewrite_user_files_for_last_turn(chat_history, session_id)`：若末条为 user 消息，将其附件复制到会话目录（API 层添加用户消息后立即调用）。
- `add_message(chat_history, query)`：`_build_user_chat_content` → 无有效内容返回 None，否则 append `{"role":"user","content": user_content}` 并返回新 chat_history（API 层构造用户消息核心）。
- `clear_ui_and_turns(session_id)`：`delete_turns_after(session_id, "00000000_000000")` 全删，返回 `([], {"text":"","files":[]})`。

---

## 附：跨模块关键链路速查

- **语音输入**：`/api/chat/start`（阻塞 ASR）→ `agent_utils.audio_file_to_text` → POST `{ASR_BASE_URL}/v1/chat/completions`（audio_url data URL，无文本提示）→ `choices[0].message.content`。
- **语音输出**：`StreamingTTSClient.stream_tts`（SSE 逐事件收 PCM f32le chunk）→ 前端 Web Audio 播放；服务端新请求自动打断旧请求。
- **图片入模**：`image_utils.image_path_to_openai_image_url_part`（缩放→base64→data URL）或 `Documents_process.process`（docx/pdf/pptx 提取文本+图片字节）。
- **工具执行**：`tool_call_utils.invoke_tool_and_build_message`（workspace block → confirm ask_human → 超时 → 归一化 ToolMessage）→ `tool_call_recorder` 实时/持久化记录 → SSE 推送前端。
- **Cron**：`CronScheduler`（5s 扫描 + 时段互斥）→ 子进程 `agent.cron.runner`（重定向存储根 + headless + execute_agent(agent_mode="cron")）→ HTTP 回传 `:8765/api/cron/internal/live|finished` → 主进程 `cron.live` 分发 SSE。
