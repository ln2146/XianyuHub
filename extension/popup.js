// 读取 goofish.com 的 Cookie，复制或发送到自建的鱼塘管家
const $ = (id) => document.getElementById(id);

async function readCookies() {
  const cookies = await chrome.cookies.getAll({ domain: "goofish.com" });
  return cookies.map((c) => ({ name: c.name, value: c.value, domain: c.domain }));
}

function show(text, ok = true) {
  $("msg").textContent = text;
  $("msg").className = ok ? "ok" : "bad";
}

async function init() {
  const cookies = await readCookies();
  const names = new Set(cookies.map((c) => c.name));
  const loggedIn = ["unb", "cookie2", "_m_h5_tk"].every((n) => names.has(n));
  const nick = cookies.find((c) => c.name === "tracknick");
  // 用 DOM 节点拼装，不把 Cookie 里的昵称交给 HTML 解析
  const status = $("status");
  const tag = document.createElement("span");
  tag.className = loggedIn ? "ok" : "bad";
  tag.textContent = loggedIn ? "已检测到登录态" : "未检测到完整登录态";
  let tail = loggedIn ? "" : "，请先登录 goofish.com";
  if (loggedIn && nick) {
    try {
      tail = "（" + decodeURIComponent(nick.value) + "）";
    } catch {
      tail = "（" + nick.value + "）";
    }
  }
  status.replaceChildren(tag, document.createTextNode(tail));
  const saved = await chrome.storage.local.get(["server", "token"]);
  $("server").value = saved.server || "";
  $("token").value = saved.token || "";
}

$("copy").addEventListener("click", async () => {
  const cookies = await readCookies();
  await navigator.clipboard.writeText(JSON.stringify({ cookies }));
  show("已复制，可在管理台「账号中心 → 导入 Cookie」粘贴");
});

$("send").addEventListener("click", async () => {
  const server = $("server").value.trim().replace(/\/+$/, "");
  const token = $("token").value.trim();
  if (!/^https?:\/\//.test(server) || !token) return show("请填写正确的地址和令牌", false);
  const origin = new URL(server).origin + "/*";
  const granted = await chrome.permissions.request({ origins: [origin] });
  if (!granted) return show("需要授权访问该地址", false);
  await chrome.storage.local.set({ server, token });
  const cookies = await readCookies();
  try {
    const resp = await fetch(`${server}/api/v1/accounts/import`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ cookies: JSON.stringify({ cookies }), verify: true }),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) return show(`导入失败：${data.detail || resp.status}`, false);
    show(`导入成功：${data.nickname || data.unb}`);
  } catch (e) {
    show(`网络错误：${e.message}`, false);
  }
});

init();
