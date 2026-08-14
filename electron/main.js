// main.js — Electron 主进程（桌面版最小安装包）
//
// 两种模式：
//   - 开发模式 (npm start):  使用项目本地的 src/ 和 myenv/
//   - 打包模式 (minor Agent.exe): 使用 resources/ 下的 src/ 和 myenv/
//
// 首次运行会弹出 setup.html 让用户配置 LLM API Key，
// 写入 env_config.json 后启动 FastAPI 并加载 Web UI。

const { app, BrowserWindow, dialog, ipcMain, Menu } = require('electron');
const { spawn, execSync } = require('child_process');
const path = require('path');
const http = require('http');
const fs = require('fs');

// ==================== 路径解析 ====================
const isPackaged = app.isPackaged;

// 开发模式下所有文件在项目目录中
// 打包模式下: 主进程代码 -> resources/app.asar，源码+venv -> resources/
const AGENT_DIR = isPackaged
  ? process.resourcesPath                             // resources/
  : path.join(__dirname, '..');                       // minors_app/

// 打包模式下 Python 源码在 resources/app/src/（非 resources/src/）
const SRC_DIR = isPackaged
  ? path.join(process.resourcesPath, 'app', 'src')
  : path.join(AGENT_DIR, 'src');

// 配置文件路径 (src/agent/config/env_config.json)
const CONFIG_PATH = path.join(SRC_DIR, 'agent', 'config', 'env_config.json');
const CONFIG_DIST_PATH = path.join(SRC_DIR, 'agent', 'config', 'env_config_dist.json');
const THEME_CONFIG_PATH = path.join(SRC_DIR, 'agent', 'config', 'theme_config.json');

const HOST = '127.0.0.1';
const PORT = 8765;
const BASE_URL = `http://${HOST}:${PORT}`;

// ==================== 主题检测（启动玻璃层随主题色变化） ====================
// 与前端 themes.js 的 dark 标记保持一致
const DARK_THEMES = new Set(['vscode-dark', 'cyber-neon', 'deep-space-indigo', 'pixel-gold']);

function getThemeMode() {
  try {
    if (fs.existsSync(THEME_CONFIG_PATH)) {
      const cfg = JSON.parse(fs.readFileSync(THEME_CONFIG_PATH, 'utf-8'));
      const id = cfg.theme || '';
      if (DARK_THEMES.has(id)) return 'dark';
      if (id) {
        // 未知主题按 id 推断（与 themes.js 的回退逻辑一致）
        return (!id.includes('light') && !id.includes('solarized')) ? 'dark' : 'light';
      }
    }
  } catch {}
  return 'dark'; // 默认深色，与窗口默认底色一致
}

// ==================== 全局状态 ====================
let mainWindow = null;
let pythonProcess = null;
let isQuitting = false;
let isLaunching = false;  // 防止 setup 窗口关闭时触发 app.quit

// ==================== 端口清理 ====================
function killPortProcess(port) {
  try {
    // 查找占用端口的所有 PID 并强制终止（含子进程树）
    const result = execSync(
      `powershell -Command "Get-NetTCPConnection -LocalPort ${port} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }"`,
      { timeout: 5000, stdio: 'pipe' }
    );
    return true;
  } catch {
    return false;
  }
}

// ==================== 首次运行检测 ====================
function isFirstRun() {
  if (!fs.existsSync(CONFIG_PATH)) {
    return true;
  }
  try {
    const config = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf-8'));
    const models = config.models || [];
    if (models.length === 0) return true;
    if (models[0].id === 'SETUP_REQUIRED') return true;
    if (!models[0].api_key || !models[0].base_url || !models[0].model) return true;
    return false;
  } catch {
    return true;
  }
}

// ==================== 配置管理 ====================
function writeEnvConfig(userInput) {
  let config;
  const templatePath = CONFIG_DIST_PATH;
  if (fs.existsSync(templatePath)) {
    config = JSON.parse(fs.readFileSync(templatePath, 'utf-8'));
  } else if (fs.existsSync(CONFIG_PATH)) {
    config = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf-8'));
  } else {
    config = {};
  }

  config.WORKING_DIR = isPackaged ? process.resourcesPath : AGENT_DIR;

  config.USER_NICKNAME = userInput.nickname || (config.USER_NICKNAME || '');
  config.USER_PYTHON_PATH = userInput.pythonPath || (config.USER_PYTHON_PATH || '');
  config.EMAIL_ADDRESS = userInput.emailAddr || (config.EMAIL_ADDRESS || '');
  config.EMAIL_AUTH_CODE = userInput.emailCode || (config.EMAIL_AUTH_CODE || '');
  config.WEB_SEARCH_API_KEY = userInput.webSearchKey || (config.WEB_SEARCH_API_KEY || '');
  config.ASR_BASE_URL = userInput.asrUrl || (config.ASR_BASE_URL || '');
  config.STREAMING_TTS_URL = userInput.ttsUrl || (config.STREAMING_TTS_URL || '');
  config.RAG_BASE_URL = userInput.ragUrl || (config.RAG_BASE_URL || '');

  config.LLM_CONTEXT_WINDOW = String(userInput.llmContextWindow || config.LLM_CONTEXT_WINDOW || 262144);
  config.MINI_COMPRESS_RATE = String(userInput.miniCompressRate || config.MINI_COMPRESS_RATE || 0.4);
  config.HARD_COMPRESS_RATE = String(userInput.hardCompressRate || config.HARD_COMPRESS_RATE || 0.7);
  config.CURRENT_TURNS = String(userInput.currentTurns || config.CURRENT_TURNS || 4);
  config.IMG_SIZE = String(userInput.imgSize || config.IMG_SIZE || 768);
  config.RAG_CHUNK_SIZE = String(userInput.ragChunkSize || config.RAG_CHUNK_SIZE || 500);
  config.RAG_CHUNK_OVERLAP = String(userInput.ragChunkOverlap || config.RAG_CHUNK_OVERLAP || 50);
  config.GROUNDING_WIDTH = String(userInput.groundingWidth || config.GROUNDING_WIDTH || 1000);
  config.GROUNDING_HEIGHT = String(userInput.groundingHeight || config.GROUNDING_HEIGHT || 1000);
  config.LOOP_DETECT_TODOLIST_STALE_ROUNDS = String(userInput.loopStaleRounds || config.LOOP_DETECT_TODOLIST_STALE_ROUNDS || 20);
  config.LOOP_DETECT_REPEATED_TOOL_WARN = String(userInput.loopRepeatedWarn || config.LOOP_DETECT_REPEATED_TOOL_WARN || 3);
  config.LOOP_DETECT_REPEATED_TOOL_END = String(userInput.loopRepeatedEnd || config.LOOP_DETECT_REPEATED_TOOL_END || 5);
  config.SEND_FILE_SIZE_LIMIT = String(userInput.sendFileSizeLimit || config.SEND_FILE_SIZE_LIMIT || 30);

  // 存储后端：json（本地文件） / mysql（数据库，存定时任务+会话历史）
  // 向后兼容：优先读 STORAGE_BACKEND，回退旧的 CRON_STORAGE_BACKEND
  config.STORAGE_BACKEND = userInput.cronStorageBackend || config.STORAGE_BACKEND || config.CRON_STORAGE_BACKEND || 'json';

  config.models = [{
    id: 'user_configured',
    name: userInput.model,
    model: userInput.model,
    api_key: userInput.apiKey,
    base_url: userInput.baseUrl,
    timeout: userInput.timeout || 60,
    max_retries: 0,
  }];

  config.gui_model_id = userInput.guiModelId || userInput.model || (config.gui_model_id || '');

  const configDir = path.dirname(CONFIG_PATH);
  fs.mkdirSync(configDir, { recursive: true });
  fs.writeFileSync(CONFIG_PATH, JSON.stringify(config, null, 2), 'utf-8');

  console.log('[Electron] CONFIG_PATH:', CONFIG_PATH);
}

// ==================== Python 检测 ====================
function findSystemPython() {
  // 1. 优先使用用户配置的 Python 路径
  try {
    if (fs.existsSync(CONFIG_PATH)) {
      const config = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf-8'));
      if (config.USER_PYTHON_PATH && fs.existsSync(config.USER_PYTHON_PATH)) {
        return config.USER_PYTHON_PATH;
      }
    }
  } catch {}

  // 2. 常见 Python 安装路径
  const candidates = [
    'python',
    'python3',
    path.join(process.env.LOCALAPPDATA || '', 'Programs', 'Python', 'Python312', 'python.exe'),
    path.join(process.env.LOCALAPPDATA || '', 'Programs', 'Python', 'Python311', 'python.exe'),
    path.join(process.env.LOCALAPPDATA || '', 'Programs', 'Python', 'Python313', 'python.exe'),
    'C:\\Python312\\python.exe',
    'C:\\Python311\\python.exe',
    'C:\\Python313\\python.exe',
  ];
  for (const p of candidates) {
    if (p === 'python' || p === 'python3') {
      // PATH 中的 python 直接用，无法预检
      return p;
    }
    if (fs.existsSync(p)) return p;
  }
  return 'python';  // 最后 fallback 到 PATH
}

// ==================== FastAPI 生命周期 ====================
let _fastapiStderr = '';       // 累积 stderr 用于超时诊断
let _fastapiReadySettled = false;  // 健康检查已结束（成功或超时），停止轮询

function startFastAPI() {
  return new Promise((resolve, reject) => {
    killPortProcess(PORT);
    _fastapiReadySettled = false;

    const pythonExe = findSystemPython();

    // 检查 Python 是否存在
    if (!fs.existsSync(pythonExe)) {
      reject(new Error(`Python 路径不存在:\n${pythonExe}\n\n请运行安装程序或手动配置 Python 路径。`));
      return;
    }

    console.log(`[Electron] Python: ${pythonExe}`);
    console.log(`[Electron] SRC_DIR: ${SRC_DIR}`);

    _fastapiStderr = '';

    // 启动 uvicorn：用 shell 模式确保 PYTHONPATH 含空格路径能正确传递
    const uvicornArgs = ['-m', 'uvicorn', 'web.server:app', '--host', HOST, '--port', String(PORT), '--log-level', 'warning'];

    pythonProcess = spawn(`"${pythonExe}"`, uvicornArgs, {
      cwd: SRC_DIR,
      env: {
        ...process.env,
        PYTHONPATH: SRC_DIR,
        PYTHONUNBUFFERED: '1',
        WORKING_DIR: path.resolve(AGENT_DIR, '.'),
      },
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
      shell: true,
    });

    console.log(`[Electron] FastAPI PID: ${pythonProcess.pid}`);

    pythonProcess.stdout.on('data', (d) => {
      const line = d.toString().trim();
      if (line) console.log(`[FastAPI] ${line}`);
    });
    pythonProcess.stderr.on('data', (d) => {
      const text = d.toString().trim();
      if (text) {
        console.log(`[FastAPI] ${text}`);
        _fastapiStderr += text + '\n';
        if (_fastapiStderr.length > 5000) _fastapiStderr = _fastapiStderr.slice(-3000);
      }
    });

    pythonProcess.on('error', (err) => {
      console.error('[Electron] FastAPI Failed:', err.message);
      reject(err);
    });

    pythonProcess.on('exit', (code) => {
      console.log(`[Electron] FastAPI Exit Code: ${code}`);
      pythonProcess = null;
      if (!isQuitting && code !== 0 && code !== null && mainWindow) {
        dialog.showErrorBox('Backend Service Exception', `FastAPI Exit Code: ${code}`);
      }
    });

    waitForReady(resolve, reject, 30);
  });
}

function waitForReady(resolve, reject, retriesLeft) {
  if (_fastapiReadySettled) return;
  if (retriesLeft <= 0) {
    _fastapiReadySettled = true;
    reject(new Error(
      `FastAPI 启动超时\n\nPython: ${findSystemPython()}\n工作目录: ${SRC_DIR}\n\n最后 stderr 输出:\n${_fastapiStderr || '(无输出)'}`
    ));
    return;
  }
  const req = http.get(`${BASE_URL}/api/health`, (res) => {
    res.resume(); // 及时排空响应体，避免 keep-alive 悬挂
    if (res.statusCode === 200) {
      if (!_fastapiReadySettled) {
        _fastapiReadySettled = true;
        console.log('[Electron] FastAPI Ready');
        resolve();
      }
    } else {
      retry();
    }
  });
  req.on('error', () => retry());
  req.setTimeout(2000, () => { req.destroy(); retry(); });
  function retry() {
    // 已就绪/已超时后不再轮询，防止反复打印日志
    setTimeout(() => {
      if (!_fastapiReadySettled) waitForReady(resolve, reject, retriesLeft - 1);
    }, 1000);
  }
}

function stopFastAPI() {
  // 先通过端口杀一次（清理所有关联进程）
  killPortProcess(PORT);
  // 再通过 PID 杀一次（确保主进程被杀）
  if (pythonProcess) {
    console.log('[Electron] Killing FastAPI Process...');
    try {
      if (process.platform === 'win32') {
        execSync(`taskkill /pid ${pythonProcess.pid} /f /t 2>nul`, { stdio: 'ignore' });
      } else {
        pythonProcess.kill('SIGTERM');
      }
    } catch {}
    pythonProcess = null;
  }
}

// ==================== 窗口管理 ====================
async function createMainWindow(themeMode) {
  themeMode = themeMode || getThemeMode();

  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 800,
    minHeight: 600,
    title: 'minor Agent',
    backgroundColor: themeMode === 'dark' ? '#1a1a2e' : '#eef1f7',
    frame: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
    show: false,
  });

  // 清除缓存后再加载，确保获取最新 JS/CSS
  await mainWindow.webContents.session.clearCache();
  await mainWindow.webContents.session.clearStorageData({ storages: ['caches', 'serviceworkers'] });

  // 先显示本地过渡页：毛玻璃 + 中央图标（无任何按钮），主题随 theme_config.json 变化；
  // FastAPI 就绪后再切到应用页；应用页自带的同款玻璃覆盖层会无缝接手
  mainWindow.loadFile(path.join(__dirname, 'splash.html'), { query: { theme: themeMode } });

  mainWindow.once('ready-to-show', () => mainWindow.show());

  mainWindow.on('closed', () => { mainWindow = null; });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    require('electron').shell.openExternal(url).catch(() => {});
    return { action: 'deny' };
  });

  return mainWindow;
}

// 启动主流程：立即弹出毛玻璃窗口 → 后台启动 FastAPI → 就绪后加载应用页
async function launchMainFlow() {
  const themeMode = getThemeMode();
  try {
    // 1. 创建并显示主窗口（本地过渡页，秒开，无按钮），主题随 theme_config.json
    await createMainWindow(themeMode);
    // 2. 后台启动 FastAPI（窗口已先显示，用户不会盯着空白等待）
    await startFastAPI();
    if (!mainWindow) return; // 启动期间用户已关闭窗口（window-all-closed 会走退出流程）
    // 3. 后端就绪后加载应用页；带上主题参数，保证应用页首帧即为当前主题（避免深色闪屏），
    //    页面加载完成后由前端播放玻璃层淡出动画
    mainWindow.loadURL(`${BASE_URL}?theme=${themeMode}`);
  } catch (err) {
    dialog.showErrorBox('启动失败', `无法启动 minor Agent:\n${err.message}`);
    app.quit();
  }
}

// ==================== 应用生命周期 ====================
let setupWindow = null;

function createSetupWindow() {
  setupWindow = new BrowserWindow({
    width: 560,
    height: 720,
    minWidth: 500,
    minHeight: 600,
    title: 'minor Agent - 首次配置',
    backgroundColor: '#f8fafc',
    frame: false,
    resizable: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
    show: false,
  });

  setupWindow.loadFile(path.join(__dirname, 'setup.html'));

  setupWindow.once('ready-to-show', () => setupWindow.show());

  setupWindow.on('closed', () => { setupWindow = null; });
}

app.whenReady().then(async () => {
  // 隐藏菜单栏
  Menu.setApplicationMenu(null);

  if (isFirstRun()) {
    // 首次运行：打开配置窗口（Python 环境安装 + LLM 配置）
    createSetupWindow();
  } else {
    // 非首次：立即显示毛玻璃启动窗口，同时后台启动 FastAPI 和主流程
    await launchMainFlow();
  }
});

ipcMain.handle('save-config', async (_event, data) => {
  try {
    writeEnvConfig(data);
    const testOk = await testLLMConnection(data);
    if (!testOk) {
      return { success: false, error: '无法连接到 LLM 服务，请检查 API Key 和 Base URL' };
    }
    return { success: true };
  } catch (err) {
    return { success: false, error: err.message };
  }
});

ipcMain.on('launch-app', async () => {
  // 标记正在启动，防止关闭 setup 窗口时触发 app.quit
  isLaunching = true;

  // 关闭配置窗口
  if (setupWindow) {
    setupWindow.close();
    setupWindow = null;
  }

  // 立即显示毛玻璃启动窗口，后台启动 FastAPI 并加载应用页
  try {
    await launchMainFlow();
  } finally {
    isLaunching = false;
  }
});

// ===== 首次运行检测（供前端查询） =====
ipcMain.handle('is-first-run', () => isFirstRun());

async function testLLMConnection(data) {
  const https = require('https');
  return new Promise((resolve) => {
    // 检查 LLM 服务健康状态：GET /models 返回 200 即可
    const url = new URL(data.baseUrl + (data.baseUrl.endsWith('/') ? '' : '/') + 'models');
    const isHttps = url.protocol === 'https:';
    const mod = isHttps ? https : http;
    const req = mod.request({
      hostname: url.hostname,
      port: url.port || (isHttps ? 443 : 80),
      path: url.pathname,
      method: 'GET',
      headers: {
        'Authorization': `Bearer ${data.apiKey}`,
      },
      timeout: 15000,
      rejectUnauthorized: false,
    }, (res) => {
      resolve(res.statusCode === 200);
    });
    req.on('error', () => resolve(false));
    req.on('timeout', () => { req.destroy(); resolve(false); });
    req.end();
  });
}

// ==================== IPC：文件系统操作 ====================
const SUPPORTED_FILE_EXTS = new Set([
  '.txt','.json','.md','.cpp','.c','.py','.m','.java','.html','.htm',
  '.svg','.css','.js','.ts','.xml','.yaml','.yml','.toml',
  '.csv','.log','.env','.ini','.cfg','.sh','.bat','.ps1','.sql',
  '.r','.go','.rs','.rb','.php','.swift','.kt','.scala',
  '.docx','.pptx','.pdf','.xlsx','.doc','.xls','.ppt',
  '.png','.jpg','.jpeg','.gif','.bmp','.webp','.ico',
]);

function isSupportedFile(name) {
  const ext = '.' + (name.split('.').pop() || '').toLowerCase();
  return SUPPORTED_FILE_EXTS.has(ext);
}

function _getMime(filePath) {
  const ext = '.' + (filePath.split('.').pop() || '').toLowerCase();
  const map = {
    '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
    '.gif': 'image/gif', '.bmp': 'image/bmp', '.webp': 'image/webp',
    '.ico': 'image/x-icon',
    '.svg': 'image/svg+xml', '.pdf': 'application/pdf',
    '.html': 'text/html', '.htm': 'text/html',
  };
  return map[ext] || 'application/octet-stream';
}

function readDirRecursive(dirPath, depth, currentDepth, rootDir) {
  if (currentDepth > depth) return [];
  const baseRoot = rootDir || dirPath;
  let results = [];
  try {
    const entries = fs.readdirSync(dirPath, { withFileTypes: true });
    for (const entry of entries) {
      const fullPath = path.join(dirPath, entry.name);
      if (entry.name.startsWith('.') || entry.name === 'node_modules' || entry.name === '__pycache__') continue;
      if (entry.isDirectory()) {
        if (currentDepth < depth) {
          results = results.concat(readDirRecursive(fullPath, depth, currentDepth + 1, baseRoot));
        }
      } else if (entry.isFile()) {
        if (isSupportedFile(entry.name)) {
          try {
            const stat = fs.statSync(fullPath);
            results.push({
              path: path.relative(baseRoot, fullPath).replace(/\\/g, '/'),
              name: entry.name,
              is_dir: false,
              size: stat.size,
            });
          } catch {}
        }
      }
    }
  } catch {}
  return results;
}

ipcMain.handle('fs:readFile', async (_event, filePath) => {
  try {
    const content = fs.readFileSync(filePath, 'utf-8');
    return { content, status: 'ok' };
  } catch (err) {
    return { content: '', status: 'error', error: err.message };
  }
});

ipcMain.handle('fs:readBinaryFile', async (_event, filePath) => {
  try {
    const buf = fs.readFileSync(filePath);
    return { data: buf.toString('base64'), mime: _getMime(filePath), status: 'ok' };
  } catch (err) {
    return { data: '', mime: '', status: 'error', error: err.message };
  }
});

ipcMain.handle('fs:writeFile', async (_event, filePath, content) => {
  try {
    fs.mkdirSync(path.dirname(filePath), { recursive: true });
    fs.writeFileSync(filePath, content, 'utf-8');
    return { ok: true };
  } catch (err) {
    return { ok: false, error: err.message };
  }
});

ipcMain.handle('fs:readDir', async (_event, dirPath, depth = 10) => {
  try {
    const files = readDirRecursive(dirPath, depth, 0);
    return { files, status: 'ok' };
  } catch (err) {
    return { files: [], status: 'error', error: err.message };
  }
});

ipcMain.handle('fs:stat', async (_event, filePath) => {
  try {
    const s = fs.statSync(filePath);
    return { exists: true, is_dir: s.isDirectory(), size: s.size, mtime: s.mtimeMs };
  } catch {
    return { exists: false };
  }
});

ipcMain.handle('fs:rename', async (_event, oldPath, newPath) => {
  try {
    fs.mkdirSync(path.dirname(newPath), { recursive: true });
    fs.renameSync(oldPath, newPath);
    return { ok: true };
  } catch (err) {
    return { ok: false, error: err.message };
  }
});

ipcMain.handle('fs:delete', async (_event, filePath) => {
  try {
    // 使用 shell.trashItem 移入回收站，而非永久删除
    const { shell } = require('electron');
    await shell.trashItem(filePath);
    return { ok: true };
  } catch (err) {
    // 回收站不可用时回退到永久删除（如网络驱动器、U盘等）
    try {
      const s = fs.statSync(filePath);
      if (s.isDirectory()) {
        fs.rmSync(filePath, { recursive: true, force: true });
      } else {
        fs.unlinkSync(filePath);
      }
      return { ok: true };
    } catch (err2) {
      return { ok: false, error: err2.message };
    }
  }
});

ipcMain.handle('fs:mkdir', async (_event, dirPath) => {
  try {
    fs.mkdirSync(dirPath, { recursive: true });
    return { ok: true };
  } catch (err) {
    return { ok: false, error: err.message };
  }
});

ipcMain.handle('fs:copyFile', async (_event, srcPath, destDir) => {
  try {
    const srcName = path.basename(srcPath);
    let destPath = path.join(destDir, srcName);

    // 避免重名：追加 _1, _2 ...
    let counter = 1;
    const ext = path.extname(srcName);
    const base = path.basename(srcName, ext);
    while (fs.existsSync(destPath)) {
      destPath = path.join(destDir, `${base}_${counter}${ext}`);
      counter++;
    }

    fs.mkdirSync(destDir, { recursive: true });
    const stat = fs.statSync(srcPath);
    if (stat.isDirectory()) {
      // 目录递归复制（Node.js 16.7+）
      fs.cpSync(srcPath, destPath, { recursive: true });
    } else {
      fs.copyFileSync(srcPath, destPath);
    }
    return { ok: true, destPath, destName: path.basename(destPath) };
  } catch (err) {
    return { ok: false, error: err.message };
  }
});

ipcMain.handle('fs:writeFromBuffer', async (_event, destDir, fileName, base64Data) => {
  try {
    let destPath = path.join(destDir, fileName);

    // 避免重名
    let counter = 1;
    const ext = path.extname(fileName);
    const base = path.basename(fileName, ext);
    while (fs.existsSync(destPath)) {
      destPath = path.join(destDir, `${base}_${counter}${ext}`);
      counter++;
    }

    fs.mkdirSync(destDir, { recursive: true });
    const buf = Buffer.from(base64Data, 'base64');
    fs.writeFileSync(destPath, buf);
    return { ok: true, destPath, destName: path.basename(destPath) };
  } catch (err) {
    return { ok: false, error: err.message };
  }
});

ipcMain.handle('fs:exists', async (_event, filePath) => {
  return fs.existsSync(filePath);
});

// ==================== IPC：对话框 ====================
ipcMain.handle('dialog:openFolder', async () => {
  const win = BrowserWindow.getFocusedWindow();
  const result = await dialog.showOpenDialog(win, {
    properties: ['openDirectory'],
    title: '选择工作文件夹',
  });
  if (result.canceled || result.filePaths.length === 0) {
    return { canceled: true };
  }
  return { canceled: false, path: result.filePaths[0] };
});

ipcMain.handle('dialog:openFile', async () => {
  const win = BrowserWindow.getFocusedWindow();
  const result = await dialog.showOpenDialog(win, {
    properties: ['openFile'],
    title: '打开文件',
    filters: [
      { name: '支持的文件', extensions: [
        'txt','json','md','cpp','c','py','m','java','html','htm',
        'svg','css','js','ts','xml','yaml','yml','toml',
        'csv','log','env','ini','cfg','sh','bat','ps1','sql',
        'r','go','rs','rb','php','swift','kt','scala',
        'docx','pptx','pdf','xlsx',
        'png','jpg','jpeg','gif','bmp','webp',
      ]},
      { name: '所有文件', extensions: ['*'] },
    ],
  });
  if (result.canceled || result.filePaths.length === 0) {
    return { canceled: true };
  }
  const filePath = result.filePaths[0];
  const name = path.basename(filePath);
  try {
    const content = fs.readFileSync(filePath, 'utf-8');
    return { canceled: false, path: filePath, name, content };
  } catch {
    return { canceled: false, path: filePath, name, content: '' };
  }
});

ipcMain.handle('dialog:saveFile', async (_event, defaultPath) => {
  const win = BrowserWindow.getFocusedWindow();
  const result = await dialog.showSaveDialog(win, {
    defaultPath: defaultPath,
    title: '保存文件',
  });
  if (result.canceled) return { canceled: true };
  return { canceled: false, path: result.filePath };
});

// ==================== IPC：应用信息 ====================
ipcMain.handle('app:getPath', () => AGENT_DIR);

// ===== Python 检测 =====
ipcMain.handle('python:detect', async () => {
  const pythonPath = findSystemPython();
  let version = '';
  let versionOk = false;
  try {
    const result = execSync(`"${pythonPath}" --version`, { timeout: 5000, stdio: 'pipe' });
    version = result.toString().trim();
    // 检查版本 >= 3.12
    const m = version.match(/Python\s+(\d+)\.(\d+)/i);
    if (m) {
      const major = parseInt(m[1]), minor = parseInt(m[2]);
      versionOk = major > 3 || (major === 3 && minor >= 12);
    }
  } catch {}
  return { pythonPath, version, versionOk };
});

// ===== 选择 Python 可执行文件 =====
ipcMain.handle('dialog:pickPython', async () => {
  const win = BrowserWindow.getFocusedWindow();
  const result = await dialog.showOpenDialog(win, {
    properties: ['openFile'],
    title: '选择 Python 可执行文件',
    filters: [
      { name: 'Python 可执行文件', extensions: ['exe'] },
    ],
  });
  if (result.canceled || result.filePaths.length === 0) {
    return { canceled: true };
  }
  return { canceled: false, path: result.filePaths[0] };
});

// ===== Python 环境安装 =====
ipcMain.handle('python:setup', async (event, pythonPath) => {
  const win = BrowserWindow.fromWebContents(event.sender);
  const send = (type, data) => {
    try { win?.webContents?.send('python:setup-progress', { type, ...data }); } catch {}
  };

  try {
    send('status', { text: '检测 Python...' });
    // 验证 Python 可用
    try {
      execSync(`"${pythonPath}" --version`, { timeout: 5000, stdio: 'pipe' });
    } catch {
      return { ok: false, error: 'Python 无法启动，请检查路径' };
    }

    // 确定 venv 路径（在安装目录下，卸载时可一并清理）
    const installDir = isPackaged ? path.dirname(app.getPath('exe')) : AGENT_DIR;
    const venvDir = path.join(installDir, 'agent_venv');
    const venvPython = path.join(venvDir, 'Scripts', 'python.exe');

    if (!fs.existsSync(venvPython)) {
      send('status', { text: '创建虚拟环境...' });
      try {
        execSync(`"${pythonPath}" -m venv "${venvDir}"`, { timeout: 60000, stdio: 'pipe' });
      } catch (e) {
        return { ok: false, error: '创建虚拟环境失败: ' + e.message };
      }
    } else {
      send('status', { text: '使用已有虚拟环境' });
    }

    // pip install -r requirements.txt
    const reqPath = path.join(__dirname, '..', 'requirements.txt');
    if (!fs.existsSync(reqPath)) {
      return { ok: false, error: '未找到 requirements.txt' };
    }

    send('status', { text: '安装依赖包...' });
    const pipArgs = ['-m', 'pip', 'install', '-r', reqPath];

    const proc = spawn(venvPython, pipArgs, {
      cwd: path.dirname(venvDir),
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    });

    // 实时流式输出安装日志
    let logLines = [];
    let stderrBuf = '';
    let pendingLine = '';

    const flushLine = (line) => {
      const trimmed = line.trim();
      if (!trimmed) return;
      // 过滤掉无意义的进度条和空白行
      if (/^\s*\d+%/.test(trimmed)) return;
      if (/^\s*[-|/\\]+\s*$/.test(trimmed)) return;
      logLines.push(trimmed);
      if (logLines.length > 200) logLines = logLines.slice(-150);
      send('log', { lines: [trimmed], all: logLines.join('\n') });
    };

    proc.stdout.on('data', (chunk) => {
      const text = chunk.toString();
      const parts = (pendingLine + text).split('\n');
      pendingLine = parts.pop() || '';
      for (const line of parts) flushLine(line);
    });

    proc.stderr.on('data', (chunk) => {
      const text = chunk.toString();
      stderrBuf += text;
      if (stderrBuf.length > 10000) stderrBuf = stderrBuf.slice(-8000);
      const parts = text.split('\n');
      // stderr 最后一行可能不完整，但 pip 进度条通常每行独立
      for (const line of parts) {
        const trimmed = line.trim();
        if (trimmed && !trimmed.includes('%')) flushLine(trimmed);
      }
    });

    return new Promise((resolve) => {
      proc.on('close', (code) => {
        if (code === 0) {
          send('done', { venvDir, venvPython });
          resolve({ ok: true, venvDir, venvPython });
        } else {
          const errDetail = stderrBuf.split('\n').filter(l => l.trim()).slice(-10).join('\n');
          resolve({ ok: false, error: `pip install 退出码 ${code}${errDetail ? '\n' + errDetail : ''}` });
        }
      });
      proc.on('error', (err) => {
        resolve({ ok: false, error: err.message });
      });
    });
  } catch (e) {
    send('status', { text: '安装失败' });
    return { ok: false, error: e.message };
  }
});

// ===== 文件系统 IPC =====
let _fsWatcher = null;
let _watchedPath = null;

ipcMain.handle('fs:watch', async (_event, dirPath) => {
  if (_fsWatcher) { _fsWatcher.close(); _fsWatcher = null; }
  _watchedPath = dirPath;
  try {
    _fsWatcher = fs.watch(dirPath, { recursive: true }, (eventType, filename) => {
      if (!filename || !mainWindow) return;
      const rel = filename.replace(/\\/g, '/');
      if (filename.startsWith('.') || filename.includes('node_modules') || filename.includes('__pycache__')) return;
      const absPath = path.join(dirPath, filename);
      try {
        const stat = fs.statSync(absPath);
        const file = {
          path: rel, name: path.basename(filename),
          is_dir: stat.isDirectory(), size: stat.size,
        };
        mainWindow.webContents.send('fs:changed', { event: eventType, file });
      } catch {
        // 文件可能已被删除，仍然发送事件让前端感知变化
        mainWindow.webContents.send('fs:changed', {
          event: eventType,
          file: { path: rel, name: path.basename(filename), is_dir: false, size: 0 },
        });
      }
    });
    return { ok: true };
  } catch (e) {
    return { ok: false, error: e.message };
  }
});

ipcMain.handle('fs:unwatch', async () => {
  if (_fsWatcher) { _fsWatcher.close(); _fsWatcher = null; _watchedPath = null; }
  return { ok: true };
});

// ===== 窗口控制（自定义标题栏） =====
ipcMain.on('window:minimize', () => {
  if (mainWindow) mainWindow.minimize();
});

// ===== 配置窗口关闭 =====
ipcMain.on('setup:close', () => {
  if (setupWindow) setupWindow.close();
  else app.quit();
});
let _maximizeLock = false;
ipcMain.on('window:maximize', () => {
  if (_maximizeLock || !mainWindow) return;
  _maximizeLock = true;
  mainWindow.isMaximized() ? mainWindow.unmaximize() : mainWindow.maximize();
  setTimeout(() => { _maximizeLock = false; }, 300);
});
ipcMain.on('window:close', () => {
  if (mainWindow) mainWindow.close();
});

// 最大化/还原状态变化时通知渲染进程
app.on('browser-window-created', (_, win) => {
  win.on('maximize', () => win.webContents.send('window:maximized', true));
  win.on('unmaximize', () => win.webContents.send('window:maximized', false));
});

app.on('window-all-closed', () => {
  if (isLaunching) return;  // setup → main 过渡中，不退出
  isQuitting = true;
  stopFastAPI();
  app.quit();
});

app.on('before-quit', () => {
  isQuitting = true;
  stopFastAPI();
});

app.on('activate', () => {
  if (mainWindow === null) {
    launchMainFlow();
  }
});

// 防止多实例
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });
}
