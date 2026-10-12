// 后台：读取闲鱼登录态；按管理台的授权，账号掉线时自动把浏览器里的登录态同步回去
const REQUIRED = ["unb", "cookie2", "_m_h5_tk"];
const SYNC_EVERY_MINUTES = 30;

async function readCookies() {
  const cookies = await chrome.cookies.getAll({ domain: "goofish.com" });
  return cookies.map((c) => ({ name: c.name, value: c.value, domain: c.domain }));
}

function decodeNick(raw) {
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw;
  }
}

async function loginState() {
  const cookies = await readCookies();
  const byName = Object.fromEntries(cookies.map((c) => [c.name, c.value]));
  return {
    cookies,
    loggedIn: REQUIRED.every((n) => byName[n]),
    unb: byName.unb || "",
    nick: byName.tracknick ? decodeNick(byName.tracknick) : "",
  };
}

async function getStore() {
  const { approved = [], targets = {} } = await chrome.storage.local.get(["approved", "targets"]);
  return { approved, targets };
}

async function approve(origin) {
  const { approved } = await getStore();
  if (!approved.includes(origin)) await chrome.storage.local.set({ approved: [...approved, origin] });
}

// ---------------------------------------------------------------- 自动续期
async function syncOne(origin, target, state) {
  let result;
  try {
    const resp = await fetch(`${origin}/api/v1/accounts/cookie-sync`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${target.token}` },
      body: JSON.stringify({ cookies: JSON.stringify({ cookies: state.cookies }) }),
    });
    const data = await resp.json().catch(() => ({}));
    result = resp.ok ? data.result : resp.status === 401 ? "token_invalid" : `http_${resp.status}`;
  } catch {
    result = "unreachable";
  }
  return { ...target, lastAt: Date.now(), lastResult: result };
}

async function syncAll() {
  const { targets } = await getStore();
  const origins = Object.keys(targets);
  if (!origins.length) return;
  const state = await loginState();
  const next = { ...targets };
  for (const origin of origins) {
    next[origin] = state.loggedIn
      ? await syncOne(origin, targets[origin], state)
      : { ...targets[origin], lastAt: Date.now(), lastResult: "browser_logged_out" };
  }
  // 同步期间可能有人停用了某个地址：只回写仍然存在的
  const { targets: latest } = await getStore();
  for (const origin of Object.keys(next)) if (!latest[origin]) delete next[origin];
  await chrome.storage.local.set({ targets: next });
}

function ensureAlarm() {
  chrome.alarms.get("sync", (a) => {
    if (!a) chrome.alarms.create("sync", { periodInMinutes: SYNC_EVERY_MINUTES });
  });
}

chrome.runtime.onInstalled.addListener(ensureAlarm);
chrome.runtime.onStartup.addListener(ensureAlarm);
chrome.alarms.onAlarm.addListener((a) => {
  if (a.name === "sync" || a.name === "sync-soon") syncAll();
});
// 浏览器里重新登录了闲鱼：稍等片刻（登录态写完）再同步
chrome.cookies.onChanged.addListener(({ cookie, removed }) => {
  if (!removed && cookie.domain.endsWith("goofish.com") && REQUIRED.includes(cookie.name)) {
    chrome.alarms.create("sync-soon", { delayInMinutes: 1 });
  }
});

// ---------------------------------------------------------------- 消息
async function handle(msg, sender) {
  // 来自管理台页面（经 bridge.js 转发）：以发送方页面的源为准，页面自己说的不算
  if (sender.tab) {
    const origin = sender.origin || new URL(sender.url).origin;
    const { approved, targets } = await getStore();
    const ok = approved.includes(origin);
    switch (msg.type) {
      case "state": {
        const { loggedIn, nick, unb } = await loginState();
        return { approved: ok, loggedIn, nick, unb, sync: !!targets[origin] };
      }
      case "approve":
        await approve(origin);
        return { ok: true };
      case "get-cookies": {
        if (!ok) return { error: "not_approved" };
        const { cookies, loggedIn, nick, unb } = await loginState();
        return { loggedIn, nick, unb, cookies: loggedIn ? cookies : [] };
      }
      case "enable-sync": {
        if (!ok) return { error: "not_approved" };
        if (typeof msg.token !== "string" || !msg.token) return { error: "missing_token" };
        await chrome.storage.local.set({ targets: { ...targets, [origin]: { token: msg.token, since: Date.now() } } });
        ensureAlarm();
        return { ok: true };
      }
      case "disable-sync": {
        const next = { ...targets };
        delete next[origin];
        await chrome.storage.local.set({ targets: next });
        return { ok: true };
      }
      default:
        return { error: "unknown" };
    }
  }
  // 来自扩展自己的弹窗
  if (msg.type === "sync-now") {
    await syncAll();
    return { ok: true };
  }
  return { error: "unknown" };
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (sender.id !== chrome.runtime.id) return false;
  handle(msg || {}, sender).then(sendResponse, (e) => sendResponse({ error: String(e?.message || e) }));
  return true;
});
