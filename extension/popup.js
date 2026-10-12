// 弹窗：查看登录态、在当前网址启用一键导入、管理自动续期
const $ = (id) => document.getElementById(id);
const REQUIRED = ["unb", "cookie2", "_m_h5_tk"];
const RESULT_TEXT = {
  healthy: "账号正常",
  renewed: "已自动恢复登录",
  invalid: "浏览器里的登录态也失效了，请重新登录闲鱼",
  not_found: "浏览器登录的闲鱼号还没添加到鱼塘管家",
  browser_logged_out: "浏览器没有登录闲鱼",
  token_invalid: "授权已过期，请在管理台重新开启",
  unreachable: "连不上鱼塘管家",
};

function show(text, ok = true) {
  $("msg").textContent = text;
  $("msg").className = ok ? "ok" : "bad";
}

async function readCookies() {
  const cookies = await chrome.cookies.getAll({ domain: "goofish.com" });
  return cookies.map((c) => ({ name: c.name, value: c.value, domain: c.domain }));
}

async function renderStatus() {
  const cookies = await readCookies();
  const names = new Set(cookies.map((c) => c.name));
  const loggedIn = REQUIRED.every((n) => names.has(n));
  const nick = cookies.find((c) => c.name === "tracknick");
  // 用 DOM 节点拼装，不把 Cookie 里的昵称交给 HTML 解析
  const tag = document.createElement("span");
  tag.className = loggedIn ? "ok" : "bad";
  tag.textContent = loggedIn ? "已登录闲鱼" : "未检测到闲鱼登录态";
  let tail = "";
  if (loggedIn && nick) {
    try {
      tail = "（" + decodeURIComponent(nick.value) + "）";
    } catch {
      tail = "（" + nick.value + "）";
    }
  }
  $("status").replaceChildren(tag, document.createTextNode(tail));
  $("login-hint").hidden = loggedIn;
}

async function renderTargets() {
  const { targets = {} } = await chrome.storage.local.get("targets");
  const origins = Object.keys(targets);
  $("sync").hidden = !origins.length;
  if (!origins.length) return;
  const box = $("targets");
  box.replaceChildren();
  for (const origin of origins) {
    const t = targets[origin];
    const row = document.createElement("div");
    row.className = "target";
    const info = document.createElement("div");
    info.className = "info";
    const o = document.createElement("div");
    o.className = "origin";
    o.textContent = origin;
    const r = document.createElement("div");
    r.className = "hint";
    r.textContent = t.lastResult
      ? `${RESULT_TEXT[t.lastResult] || t.lastResult} · ${new Date(t.lastAt).toLocaleString()}`
      : "已开启，等待第一次检查";
    info.append(o, r);
    const stop = document.createElement("button");
    stop.className = "link";
    stop.textContent = "停用";
    stop.addEventListener("click", async () => {
      const { targets: cur = {} } = await chrome.storage.local.get("targets");
      delete cur[origin];
      await chrome.storage.local.set({ targets: cur });
      location.reload();
    });
    row.append(info, stop);
    box.append(row);
  }
}

async function currentTabOrigin() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  try {
    const url = new URL(tab?.url || "");
    if (!/^https?:$/.test(url.protocol)) return null;
    if (url.hostname.endsWith("goofish.com") || ["localhost", "127.0.0.1"].includes(url.hostname)) return null;
    return { origin: url.origin, tabId: tab.id };
  } catch {
    return null;
  }
}

async function renderConnect() {
  const cur = await currentTabOrigin();
  if (!cur) return;
  const registered = await chrome.scripting.getRegisteredContentScripts({ ids: [`bridge:${cur.origin}`] });
  if (registered.length) return;
  $("connect-box").hidden = false;
  $("connect").textContent = `在 ${cur.origin} 启用一键导入`;
  $("connect").addEventListener("click", async () => {
    const granted = await chrome.permissions.request({ origins: [`${cur.origin}/*`] });
    if (!granted) return show("需要授权访问该地址", false);
    await chrome.scripting.registerContentScripts([
      {
        id: `bridge:${cur.origin}`,
        matches: [`${cur.origin}/*`],
        js: ["bridge.js"],
        runAt: "document_start",
        persistAcrossSessions: true,
      },
    ]);
    // 你在扩展里亲手授权的地址，不再弹确认框
    const { approved = [] } = await chrome.storage.local.get("approved");
    if (!approved.includes(cur.origin)) await chrome.storage.local.set({ approved: [...approved, cur.origin] });
    await chrome.tabs.reload(cur.tabId);
    $("connect-box").hidden = true;
    show("已启用，页面已刷新，可以在管理台点「从当前浏览器一键获取」了");
  });
}

$("copy").addEventListener("click", async () => {
  const cookies = await readCookies();
  await navigator.clipboard.writeText(JSON.stringify({ cookies }));
  show("已复制，可在管理台「账号配置 → 导入 Cookie」粘贴");
});

$("sync").addEventListener("click", async () => {
  $("sync").disabled = true;
  await chrome.runtime.sendMessage({ type: "sync-now" });
  $("sync").disabled = false;
  await renderTargets();
  show("已检查");
});

renderStatus();
renderTargets();
renderConnect();
