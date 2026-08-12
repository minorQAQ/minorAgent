// state.js -- 全局共享状态
// 所有可变状态封装在 state 对象中，避免 ES module 只读绑定问题

export const STORAGE_DOF = "minor_web_bg_dof";
export const STORAGE_VIG = "minor_web_bg_vignette";
export const STORAGE_HEADER_COLLAPSED = "minor_web_header_collapsed";

// 声音阈值配置（已优化）
export const START_THRESHOLD = 0.18;
export const STOP_THRESHOLD = 0.06;
export const AUTO_START_DELAY = 100;
export const AUTO_STOP_DELAY = 800;

export const state = {
  /** @type {string} */
  sessionId: "",
  /** @type {string[]} */
  sessions: [],
  /** @type {File[]} */
  pendingFiles: [],
  pendingRefs: [],  // Edit 模式引用：[{path, name, startLine, endLine, text}]
  sending: false,
  abortController: null,
  mediaRecorder: null,
  recorderStream: null,
  recordedChunks: [],
  recordingMimeType: "",
  sidebarCollapsed: false,

  // 自动语音输入相关变量
  autoInputEnabled: false,
  audioContext: null,
  analyser: null,
  dataArray: null,
  mediaStreamSource: null,
  autoInputStream: null,
  autoRecordingTimeout: null,
  silenceTimeout: null,

  /** 最近一次 renderMessages 的 JSON 可序列化快照 */
  lastRenderedMessages: [],
  activeAudioController: null,

  // 工具调用 / think 展开状态
  liveToolCallExpanded: false,
  thinkExpanded: false,

  // 设置面板缓存
  cachedAgentConfigs: [],
  cachedToolConfigs: [],
  cachedEnvConfig: {},
  cachedModels: [],
  registeredToolNames: [],
  cachedGuiConfig: { monitors: [], selected_name: "", gui_model_id: "", models: [] },
  editingModelIdx: -1,

  // Skills 缓存
  cachedSkills: [],
  editingSkillName: "",
  editingSkillAttachments: [],

  // Todo 悬浮窗引用
  _currentTodoOverlay: null,

  // HumanInteraction 浮窗引用
  _currentPendingOverlay: null,

  // HumanInteraction 等待中标记（暂停按钮不恢复）
  _pendingHumanAction: false,

  // 当前会话的 token 用量
  currentTokens: 0,

  // 模型选择
  selectedModelId: "",

  // 输出模式（文字/语音，由 文本语音.svg 按钮开关控制）
  outputMode: "text",

  // 思考模式档位：low | high | xhigh | max | ultra
  thinkingLevel: "low",

  // 工作空间
  workspacePath: "",    // 当前选中的工作空间路径（空=使用默认）
  workspaceList: [],    // 已保存的工作空间路径列表
  workspaceDefault: "", // 默认工作空间路径
  accessMode: "restricted", // 工作空间访问模式：restricted(限制访问) | approval(权限审查) | full(完全访问)

  // Edit 模式
  editMode: false,
  docFiles: [],
  docOpenTabs: [],
  activeDocFile: null,
  activeDocTab: null,
  _docTreeFolders: {},
  _lastSelection: null,
  _docRootPath: null,  // 打开文件夹的根路径

  // 当前模式：chat | edit | cron（统一源，editMode 保留向后兼容）
  mode: "chat",

  // Cron 定时任务模式
  cronTasks: [],            // 任务列表（summary）
  activeCronTaskId: "",     // 当前选中的任务 ID
  cronRunning: false,       // 是否有任务正在运行（控制发送按钮）
  _cronLiveStopFn: null,    // 当前 cron SSE 连接的停止函数
  _cronPollTimer: null,     // cron 模式下的状态轮询定时器
  _cronEditingTaskId: "",   // 正在编辑的任务 ID（空=新建）
};
