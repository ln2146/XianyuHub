<script setup lang="ts">
// 统一的闲鱼商品卡片：智能搜索、实时搜货共用。
// 卡片只放“要不要点进去”的信息；点击打开详情抽屉，次要操作在「⋯」菜单（不依赖悬停）。
import { MoreFilled, Picture, Star, StarFilled } from '@element-plus/icons-vue'

export interface CardIcon {
  name: string
  url: string
  width: number | null
  height: number | null
}

export interface CardItem {
  title: string
  image: string
  price: number | null
  origPrice?: number | null
  /** 价格旁说明（如“累计降价168元”），优先于想要人数 */
  priceNote?: string
  wantCnt?: number | null
  attrs?: string[]
  titleIcons?: CardIcon[]
  serviceIcons?: CardIcon[]
  /** 没有闲鱼图标时的文字标签（如“包邮”） */
  textBadges?: string[]
  area?: string
  sellerNick?: string
  avatar?: string
  sellerTag?: string
  /** 图片左上角的状态（如 AI 判定） */
  badge?: { label: string; type: 'success' | 'warning' | 'danger' | 'info' } | null
  /** 底部一行补充信息（如所属搜索 · 发现时间） */
  subline?: string
  /** 一句话说明（如 AI 判定理由），最多两行 */
  note?: string
}

export interface CardMenuItem {
  key: string
  label: string
  divided?: boolean
  danger?: boolean
}

defineProps<{
  item: CardItem
  /** 不传则不显示收藏按钮 */
  starred?: boolean
  menu?: CardMenuItem[]
}>()

const emit = defineEmits<{
  (e: 'open'): void
  (e: 'star'): void
  (e: 'action', key: string): void
}>()

function iconStyle(ic: CardIcon, height: number) {
  const ratio = ic.width && ic.height ? ic.width / ic.height : 2
  return { height: `${height}px`, width: `${Math.round(height * ratio)}px` }
}
</script>

<template>
  <article class="item-card" tabindex="0" @click="emit('open')" @keyup.enter="emit('open')">
    <div class="cover">
      <el-image :src="item.image" fit="cover" class="cover-img" lazy referrerpolicy="no-referrer">
        <template #error>
          <div class="cover-err"><el-icon><Picture /></el-icon></div>
        </template>
      </el-image>
      <el-tag v-if="item.badge" class="badge" :type="item.badge.type" effect="dark" size="small" disable-transitions>
        {{ item.badge.label }}
      </el-tag>
    </div>

    <div class="info">
      <h3 class="title" :title="item.title">
        <img
          v-for="ic in item.titleIcons || []"
          :key="ic.name"
          :src="ic.url"
          :style="iconStyle(ic, 18)"
          class="title-icon"
          referrerpolicy="no-referrer"
          alt=""
        />
        <span v-for="b in item.textBadges || []" :key="b" class="text-badge">{{ b }}</span>
        {{ item.title }}
      </h3>

      <div v-if="item.attrs?.length" class="attrs">
        <span v-for="a in item.attrs" :key="a" class="attr">{{ a }}</span>
      </div>
      <div v-if="item.serviceIcons?.length" class="service">
        <img
          v-for="ic in item.serviceIcons"
          :key="ic.name"
          :src="ic.url"
          :style="iconStyle(ic, 16)"
          referrerpolicy="no-referrer"
          alt=""
        />
      </div>
      <p v-if="item.note" class="note">{{ item.note }}</p>

      <div class="price-line">
        <span class="price"><span class="yen">¥</span>{{ item.price ?? '—' }}</span>
        <span v-if="item.priceNote" class="price-note">{{ item.priceNote }}</span>
        <span v-else-if="item.wantCnt" class="want">{{ item.wantCnt }}人想要</span>
        <span v-else-if="item.origPrice" class="orig">¥{{ item.origPrice }}</span>
      </div>

      <div class="foot">
        <div class="seller">
          <img v-if="item.avatar" :src="item.avatar" class="avatar" referrerpolicy="no-referrer" alt="" />
          <span v-else class="avatar fallback">{{ (item.sellerNick || item.area || '闲')[0] }}</span>
          <span class="ellipsis">{{ item.area || item.sellerNick || '闲鱼卖家' }}</span>
          <span v-if="item.sellerTag" class="seller-tag">{{ item.sellerTag }}</span>
        </div>
        <div class="ops" @click.stop @keyup.stop>
          <button
            v-if="starred !== undefined"
            type="button"
            class="op"
            :class="{ on: starred }"
            :title="starred ? '取消收藏' : '收藏'"
            :aria-pressed="starred"
            @click="emit('star')"
          >
            <el-icon><StarFilled v-if="starred" /><Star v-else /></el-icon>
          </button>
          <el-dropdown v-if="menu?.length" trigger="click" @command="(k: string) => emit('action', k)">
            <button type="button" class="op" title="更多操作"><el-icon><MoreFilled /></el-icon></button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item v-for="m in menu" :key="m.key" :command="m.key" :divided="m.divided">
                  <span :class="{ danger: m.danger }">{{ m.label }}</span>
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </div>
      <div v-if="item.subline" class="subline ellipsis">{{ item.subline }}</div>
    </div>
  </article>
</template>

<style scoped>
.item-card {
  display: flex;
  flex-direction: column;
  background: var(--xh-card);
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-md);
  overflow: hidden;
  cursor: pointer;
  transition:
    box-shadow 0.2s,
    border-color 0.2s;
}
.item-card:hover {
  box-shadow: var(--xh-shadow-2);
  border-color: transparent;
}
.item-card:focus-visible {
  outline: 2px solid var(--xh-primary);
  outline-offset: 2px;
}
.cover {
  position: relative;
  aspect-ratio: 1 / 1;
  background: var(--xh-fill);
}
.cover-img {
  width: 100%;
  height: 100%;
  display: block;
}
.cover-err {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  font-size: var(--xh-fs-xxl);
  color: var(--xh-disabled);
}
.badge {
  position: absolute;
  top: var(--xh-space-2);
  left: var(--xh-space-2);
}
.info {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px var(--xh-space-3) var(--xh-space-3);
  flex: 1;
}
.title {
  margin: 0;
  font-size: var(--xh-fs-md);
  font-weight: 500;
  line-height: 21px;
  color: var(--xh-text);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 42px;
}
.title-icon {
  vertical-align: -4px;
  margin-right: var(--xh-space-1);
}
.text-badge {
  display: inline-block;
  margin-right: var(--xh-space-1);
  padding: 0 5px;
  border-radius: var(--xh-radius-sm);
  background: var(--xh-primary-soft);
  color: var(--xh-primary);
  font-size: var(--xh-fs-xs);
  font-weight: 600;
  line-height: 18px;
  vertical-align: 1px;
}
.attrs {
  display: flex;
  flex-wrap: wrap;
  max-height: 16px;
  overflow: hidden;
  font-size: var(--xh-fs-xs);
  line-height: 16px;
  color: var(--xh-muted);
}
.attr + .attr::before {
  content: '';
  display: inline-block;
  width: 1px;
  height: 10px;
  margin: 0 6px;
  background: var(--xh-border-strong);
  vertical-align: -1px;
}
.service {
  display: flex;
  flex-wrap: wrap;
  gap: var(--xh-space-1);
}
.note {
  margin: 0;
  font-size: var(--xh-fs-xs);
  line-height: 18px;
  color: var(--xh-text-2);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.price-line {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin-top: auto;
  min-width: 0;
}
.price {
  color: var(--xh-price);
  font-size: var(--xh-fs-xl);
  font-weight: 700;
  white-space: nowrap;
}
.yen {
  font-size: var(--xh-fs-xs);
  margin-right: 1px;
}
.price-note {
  font-size: var(--xh-fs-xs);
  color: var(--xh-price);
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.want,
.orig {
  font-size: var(--xh-fs-xs);
  color: var(--xh-muted);
  white-space: nowrap;
}
.orig {
  text-decoration: line-through;
}
.foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}
.seller {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  font-size: var(--xh-fs-xs);
  color: var(--xh-text-2);
}
.avatar {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  object-fit: cover;
  flex-shrink: 0;
}
.avatar.fallback {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: var(--xh-primary-soft);
  color: var(--xh-primary);
  font-size: 11px;
  font-weight: 600;
}
.seller-tag {
  flex-shrink: 0;
  padding: 0 6px;
  border-radius: var(--xh-radius-sm);
  background: var(--xh-primary-soft);
  color: var(--xh-primary);
  font-size: 11px;
  line-height: 16px;
  white-space: nowrap;
}
.ops {
  display: flex;
  align-items: center;
  gap: 2px;
  flex-shrink: 0;
}
.op {
  width: 26px;
  height: 26px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: var(--xh-radius-sm);
  background: transparent;
  color: var(--xh-muted);
  font-size: var(--xh-fs-md);
  cursor: pointer;
}
.op:hover {
  background: var(--xh-fill-strong);
  color: var(--xh-text);
}
.op.on {
  color: var(--xh-warning);
}
.subline {
  font-size: var(--xh-fs-xs);
  color: var(--xh-muted);
}
.danger {
  color: var(--xh-danger);
}
</style>
