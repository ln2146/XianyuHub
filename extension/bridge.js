// 管理台页面 ⇄ 扩展的桥：页面通过 window.postMessage 请求，这里转给后台并把结果发回
// 第一次被某个网址调用时要你确认，避免同一台电脑上别的网页读取你的闲鱼登录态
(() => {
  const VERSION = chrome.runtime.getManifest().version;
  const PAGE = "xh-page";
  const HELPER = "xh-helper";
  document.documentElement.dataset.xhHelper = VERSION;

  const toBackground = (msg) => chrome.runtime.sendMessage(msg);

  async function ensureApproved() {
    const st = await toBackground({ type: "state" });
    if (st.approved) return true;
    const ok = window.confirm(
      `允许「${location.origin}」读取这个浏览器里的闲鱼登录态吗？\n\n` +
        "只有这是你自己的鱼塘管家管理台时才点「确定」。登录态等同账号密码。",
    );
    if (ok) await toBackground({ type: "approve" });
    return ok;
  }

  window.addEventListener("message", async (ev) => {
    if (ev.source !== window || ev.origin !== location.origin) return;
    const m = ev.data;
    if (!m || m.source !== PAGE || typeof m.id !== "string") return;
    const reply = (data) => window.postMessage({ ...data, source: HELPER, id: m.id }, location.origin);
    try {
      switch (m.type) {
        case "ping":
          return reply({ ok: true, version: VERSION });
        case "state":
          return reply(await toBackground({ type: "state" }));
        case "get-cookies":
          if (!(await ensureApproved())) return reply({ error: "denied" });
          return reply(await toBackground({ type: "get-cookies" }));
        case "enable-sync":
          if (!(await ensureApproved())) return reply({ error: "denied" });
          return reply(await toBackground({ type: "enable-sync", token: String(m.token || "") }));
        case "disable-sync":
          return reply(await toBackground({ type: "disable-sync" }));
        default:
          return reply({ error: "unknown" });
      }
    } catch (e) {
      reply({ error: String(e?.message || e) });
    }
  });
})();
