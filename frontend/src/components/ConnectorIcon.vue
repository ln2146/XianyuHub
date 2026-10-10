<script setup lang="ts">
withDefaults(
  defineProps<{
    type: string
    size?: number
  }>(),
  {
    size: 48,
  },
)
</script>

<template>
  <div class="connector-real-icon" :style="{ width: `${size}px`, height: `${size}px` }">
    <!-- 1. 企业微信 WeCom -->
    <svg v-if="type === 'wecom'" viewBox="0 0 48 48" width="100%" height="100%" fill="none">
      <rect width="48" height="48" rx="12" fill="url(#wecom-bg-grad)" />
      <defs>
        <linearGradient id="wecom-bg-grad" x1="0" y1="0" x2="48" y2="48" gradientUnits="userSpaceOnUse">
          <stop stop-color="#2D7FF9" />
          <stop offset="1" stop-color="#1257E3" />
        </linearGradient>
      </defs>
      <!-- 大对话气泡（白色） -->
      <path
        d="M19 12.5C13.2 12.5 8.5 16.5 8.5 21.5c0 2.9 1.6 5.5 4.2 7.1L11.5 32l4.2-1.9c1.05.2 2.15.3 3.3.3 5.8 0 10.5-4 10.5-8.9s-4.7-9-10.5-9z"
        fill="#FFFFFF"
      />
      <!-- 小对话气泡（企微特征绿色） -->
      <path
        d="M28.5 20c-4.14 0-7.5 2.91-7.5 6.5 0 2.13 1.22 4.02 3.11 5.22l-.66 2.48a.35.35 0 0 0 .5.39l3.15-1.57c.46.06.92.1 1.4.1 4.14 0 7.5-2.91 7.5-6.5s-3.36-6.62-7.5-6.62z"
        fill="#00D287"
      />
      <!-- 气泡微笑弧线 -->
      <path d="M16 20.5a3 3 0 0 1 6 0" stroke="#1D6FEB" stroke-width="2.2" stroke-linecap="round" />
      <path d="M26.2 25.8a2.2 2.2 0 0 1 4.4 0" stroke="#FFFFFF" stroke-width="1.8" stroke-linecap="round" />
    </svg>

    <!-- 2. 飞书 Feishu / Lark (千纸鹤四色折纸) -->
    <svg v-else-if="type === 'feishu'" viewBox="0 0 48 48" width="100%" height="100%" fill="none">
      <rect width="48" height="48" rx="12" fill="#FFFFFF" stroke="#EAECEF" stroke-width="1.2" />
      <g transform="translate(4, 4)">
        <!-- 上羽翼：飞书主蓝 -->
        <path d="M18.8 8.2L32 15.3l-10.2 4.2-3-11.3z" fill="#3370FF" />
        <!-- 前喙与胸羽：薄荷青绿 -->
        <path d="M8.2 21.8l10.6-6.5 3 11.3L8.2 21.8z" fill="#00D6B9" />
        <!-- 后翅：深宝蓝 -->
        <path d="M21.8 26.6l-3-11.3 13.2-0.0-10.2 11.3z" fill="#1F5AFF" />
        <!-- 尾羽与立体折角 -->
        <path d="M21.8 26.6l-13.6-4.8L22 34l-.2-7.4z" fill="#0052D9" />
      </g>
    </svg>

    <!-- 3. 钉钉 DingTalk (闪电飞羽) -->
    <svg v-else-if="type === 'dingtalk'" viewBox="0 0 48 48" width="100%" height="100%" fill="none">
      <rect width="48" height="48" rx="12" fill="url(#ding-bg-grad)" />
      <defs>
        <linearGradient id="ding-bg-grad" x1="0" y1="0" x2="48" y2="48" gradientUnits="userSpaceOnUse">
          <stop stop-color="#0A89FF" />
          <stop offset="1" stop-color="#0066E8" />
        </linearGradient>
      </defs>
      <path
        d="M37 13.5L13.8 21.8c-1.3.5-1.5 2.2-.4 3l5.8 4.2-1.6 6.8c-.3 1.2 1.2 2.1 2.2 1.3l5.6-4.5 6.4 4.3c1 .7 2.4.1 2.6-1.1L38 15.2c.2-1.3-1-2.1-2-1.7z"
        fill="#FFFFFF"
      />
      <path d="M19.2 29l4.8-6.2 8.5-7.8-11.7 10.4-1.6 3.6z" fill="#0066E8" fill-opacity="0.3" />
    </svg>

    <!-- 4. QQ邮箱 / 常用邮箱 (经典信封与红印章) -->
    <svg v-else-if="type === 'email'" viewBox="0 0 48 48" width="100%" height="100%" fill="none">
      <rect width="48" height="48" rx="12" fill="url(#qqmail-bg-grad)" />
      <defs>
        <linearGradient id="qqmail-bg-grad" x1="0" y1="0" x2="48" y2="48" gradientUnits="userSpaceOnUse">
          <stop stop-color="#FFBE1A" />
          <stop offset="1" stop-color="#F59E0B" />
        </linearGradient>
      </defs>
      <!-- 白色信封主体 -->
      <rect x="9" y="14" width="30" height="20" rx="3" fill="#FFFFFF" />
      <path d="M9 16l15 10 15-10" stroke="#E2E8F0" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
      <path d="M9 32l10-8M39 32l-10-8" stroke="#EDF2F7" stroke-width="1.5" stroke-linecap="round" />
      <!-- 右上角红色 QQ 邮戳印章 -->
      <circle cx="31" cy="18" r="5" fill="#E53935" />
      <text x="31" y="20" font-size="5" font-weight="900" font-family="Arial, sans-serif" fill="#FFFFFF" text-anchor="middle">QQ</text>
    </svg>

    <!-- 5. 微信服务号 (Server酱) - 官方微信绿 + 服务星标 -->
    <svg v-else-if="type === 'serverchan'" viewBox="0 0 48 48" width="100%" height="100%" fill="none">
      <rect width="48" height="48" rx="12" fill="url(#wx-serv-grad)" />
      <defs>
        <linearGradient id="wx-serv-grad" x1="0" y1="0" x2="48" y2="48" gradientUnits="userSpaceOnUse">
          <stop stop-color="#09D168" />
          <stop offset="1" stop-color="#05A34F" />
        </linearGradient>
      </defs>
      <!-- 微信官方双气泡 -->
      <path
        d="M19.5 12C13.7 12 9 16.03 9 21c0 2.9 1.6 5.48 4.1 7.13L12 32l4.2-1.7c1.05.2 2.15.3 3.3.3 5.8 0 10.5-4.03 10.5-9s-4.7-9-10.5-9z"
        fill="#FFFFFF"
      />
      <circle cx="16" cy="19.5" r="1.4" fill="#07C160" />
      <circle cx="23" cy="19.5" r="1.4" fill="#07C160" />
      <path
        d="M28.5 20c-4.42 0-8 3.13-8 7 0 2.27 1.25 4.29 3.2 5.57l-.8 2.63 3.3-1.35c.73.15 1.5.25 2.3.25 4.42 0 8-3.13 8-7s-3.58-7.1-8-7.1z"
        fill="#FFFFFF"
      />
      <circle cx="26" cy="26" r="1.2" fill="#07C160" />
      <circle cx="31.5" cy="26" r="1.2" fill="#07C160" />
      <!-- 右上角服务号金色星标 -->
      <circle cx="36" cy="12" r="5" fill="#F59E0B" />
      <path d="M36 9.2l.9 1.8 2 .3-1.4 1.4.3 2-1.8-.9-1.8.9.3-2-1.4-1.4 2-.3.9-1.8z" fill="#FFFFFF" />
    </svg>

    <!-- 6. 微信公众号 (PushPlus) - 官方微信绿 + 消息通知角标 -->
    <svg v-else-if="type === 'pushplus'" viewBox="0 0 48 48" width="100%" height="100%" fill="none">
      <rect width="48" height="48" rx="12" fill="url(#wx-pub-grad)" />
      <defs>
        <linearGradient id="wx-pub-grad" x1="0" y1="0" x2="48" y2="48" gradientUnits="userSpaceOnUse">
          <stop stop-color="#10B981" />
          <stop offset="1" stop-color="#059669" />
        </linearGradient>
      </defs>
      <!-- 微信官方双气泡 -->
      <path
        d="M19.5 12C13.7 12 9 16.03 9 21c0 2.9 1.6 5.48 4.1 7.13L12 32l4.2-1.7c1.05.2 2.15.3 3.3.3 5.8 0 10.5-4.03 10.5-9s-4.7-9-10.5-9z"
        fill="#FFFFFF"
      />
      <circle cx="16" cy="19.5" r="1.4" fill="#059669" />
      <circle cx="23" cy="19.5" r="1.4" fill="#059669" />
      <path
        d="M28.5 20c-4.42 0-8 3.13-8 7 0 2.27 1.25 4.29 3.2 5.57l-.8 2.63 3.3-1.35c.73.15 1.5.25 2.3.25 4.42 0 8-3.13 8-7s-3.58-7.1-8-7.1z"
        fill="#FFFFFF"
      />
      <circle cx="26" cy="26" r="1.2" fill="#059669" />
      <circle cx="31.5" cy="26" r="1.2" fill="#059669" />
      <!-- 右上角推送加通知红点 -->
      <circle cx="36" cy="12" r="5" fill="#EF4444" />
      <path d="M36 9.5v5M33.5 12h5" stroke="#FFFFFF" stroke-width="1.6" stroke-linecap="round" />
    </svg>

    <!-- 7. Bark iOS (官方小狗与铃铛) -->
    <svg v-else-if="type === 'bark'" viewBox="0 0 48 48" width="100%" height="100%" fill="none">
      <rect width="48" height="48" rx="12" fill="url(#bark-bg-grad)" />
      <defs>
        <linearGradient id="bark-bg-grad" x1="0" y1="0" x2="48" y2="48" gradientUnits="userSpaceOnUse">
          <stop stop-color="#38BDF8" />
          <stop offset="1" stop-color="#0284C7" />
        </linearGradient>
      </defs>
      <!-- 小狗头部 -->
      <path
        d="M15 14c-2.5 0-4.5 3-4.5 6.5 0 2.5 1.2 4.6 3 5.7V29c0 4 4.5 7 10.5 7s10.5-3 10.5-7v-2.8c1.8-1.1 3-3.2 3-5.7 0-3.5-2-6.5-4.5-6.5-2 0-3.6 1.8-4.2 4.3C27.8 17.5 25.9 17 24 17s-3.8.5-4.8 1.3C18.6 15.8 17 14 15 14z"
        fill="#FFFFFF"
      />
      <!-- 耳朵轮廓 -->
      <path d="M12 19c-.5 1.5-.5 3 0 4.5M36 19c.5 1.5.5 3 0 4.5" stroke="#BAE6FD" stroke-width="1.5" stroke-linecap="round" />
      <!-- 眼睛 -->
      <circle cx="19" cy="24" r="1.5" fill="#0369A1" />
      <circle cx="29" cy="24" r="1.5" fill="#0369A1" />
      <!-- 鼻子与嘴巴 -->
      <ellipse cx="24" cy="27" rx="2" ry="1.4" fill="#0369A1" />
      <path d="M22 29.5c.8.8 1.4.8 2 0 .6.8 1.2.8 2 0" stroke="#0369A1" stroke-width="1.2" stroke-linecap="round" />
      <!-- 红色项圈与金色铃铛 -->
      <rect x="18" y="34.5" width="12" height="2.5" rx="1.2" fill="#EF4444" />
      <circle cx="24" cy="37.5" r="2.2" fill="#F59E0B" />
      <circle cx="24" cy="38" r="0.6" fill="#78350F" />
    </svg>

    <!-- 8. Telegram (纸飞机) -->
    <svg v-else-if="type === 'telegram'" viewBox="0 0 48 48" width="100%" height="100%" fill="none">
      <rect width="48" height="48" rx="12" fill="url(#tg-bg-grad)" />
      <defs>
        <linearGradient id="tg-bg-grad" x1="0" y1="0" x2="48" y2="48" gradientUnits="userSpaceOnUse">
          <stop stop-color="#2AABEE" />
          <stop offset="1" stop-color="#1E96D8" />
        </linearGradient>
      </defs>
      <path
        d="M11 23.5l23.5-9.5c1.1-.4 2 .3 1.7 1.6l-4 18.8c-.3 1.3-1.1 1.6-2.2 1l-6.2-4.6-3 2.9c-.3.3-.6.6-1.3.6l.4-6.3 11.5-10.4c.5-.4-.1-.7-.7-.3l-14.2 8.9-6.1-1.9c-1.3-.4-1.3-1.3.4-1.9z"
        fill="#FFFFFF"
      />
      <path d="M20.9 28l-.4 5.9c.6 0 .9-.3 1.2-.6l3.1-3-3.9-2.3z" fill="#D2E5F2" />
    </svg>

    <!-- 9. ntfy (开源手机即时通知) -->
    <svg v-else-if="type === 'ntfy'" viewBox="0 0 48 48" width="100%" height="100%" fill="none">
      <rect width="48" height="48" rx="12" fill="url(#ntfy-bg-grad)" />
      <defs>
        <linearGradient id="ntfy-bg-grad" x1="0" y1="0" x2="48" y2="48" gradientUnits="userSpaceOnUse">
          <stop stop-color="#FB923C" />
          <stop offset="1" stop-color="#EA580C" />
        </linearGradient>
      </defs>
      <!-- 喇叭机身 -->
      <path d="M23 15l-9 5H10c-1.1 0-2 .9-2 2v4c0 1.1.9 2 2 2h4l9 5V15z" fill="#FFFFFF" />
      <path d="M12 28v5c0 .6.4 1 1 1h2c.6 0 1-.4 1-1v-5" fill="#FED7AA" />
      <!-- 广播声波 -->
      <path d="M28 19c2.2 1.4 3.5 3.3 3.5 5s-1.3 3.6-3.5 5" stroke="#FFFFFF" stroke-width="2.4" stroke-linecap="round" />
      <path d="M33 15.5c3.5 2.5 5.5 5.5 5.5 8.5s-2 6-5.5 8.5" stroke="#FFFFFF" stroke-width="2.4" stroke-linecap="round" />
    </svg>

    <!-- 10. 自定义 Webhook / 通用连接器 -->
    <svg v-else viewBox="0 0 48 48" width="100%" height="100%" fill="none">
      <rect width="48" height="48" rx="12" fill="url(#hook-bg-grad)" />
      <defs>
        <linearGradient id="hook-bg-grad" x1="0" y1="0" x2="48" y2="48" gradientUnits="userSpaceOnUse">
          <stop stop-color="#818CF8" />
          <stop offset="1" stop-color="#4F46E5" />
        </linearGradient>
      </defs>
      <!-- 节点与连线 -->
      <circle cx="16" cy="24" r="5" fill="#FFFFFF" />
      <circle cx="16" cy="24" r="2.5" fill="#4F46E5" />
      <circle cx="32" cy="16" r="4.5" fill="#FFFFFF" />
      <circle cx="32" cy="32" r="4.5" fill="#FFFFFF" />
      <path d="M20 22c3.5-3 6.5-4.5 8-5.2M20 26c3.5 3 6.5 4.5 8 5.2" stroke="#FFFFFF" stroke-width="2.2" stroke-linecap="round" />
    </svg>
  </div>
</template>

<style scoped>
.connector-real-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.08);
}
</style>
