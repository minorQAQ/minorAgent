// api.js -- API 通信层

async function api(path, opts = {}) {
  const r = await fetch(path, {
    ...opts,
    headers: opts.body instanceof FormData ? {} : { "Content-Type": "application/json", ...(opts.headers || {}) },
  });
  if (!r.ok) {
    let detail = r.statusText;
    try {
      const j = await r.json();
      if (j.detail) detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* ignore */
    }
    throw new Error(detail || `HTTP ${r.status}`);
  }
  return r.json();
}

/**
 * SSE 流式 API 调用。
 * @param {string} path
 * @param {{ method?: string, body?: FormData, signal?: AbortSignal, onEvent?: (event: object) => void }} opts
 * @returns {Promise<void>}
 */
async function streamApi(path, opts = {}) {
  const { onEvent, ...fetchOpts } = opts;
  const r = await fetch(path, {
    ...fetchOpts,
    headers: fetchOpts.body instanceof FormData ? {} : { "Content-Type": "application/json", ...(fetchOpts.headers || {}) },
  });
  if (!r.ok) {
    let detail = r.statusText;
    try {
      const j = await r.json();
      if (j.detail) detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch { /* ignore */ }
    throw new Error(detail || `HTTP ${r.status}`);
  }

  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      const jsonStr = line.slice(6);
      try {
        const event = JSON.parse(jsonStr);
        if (onEvent) onEvent(event);
      } catch { /* ignore malformed JSON */ }
    }
  }
}

export { api, streamApi };
