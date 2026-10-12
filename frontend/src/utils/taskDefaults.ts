import type { ItemRules, TaskIn } from '@/api/buyer'

export const emptyRules = (): ItemRules => ({
  include_any: [],
  include_all: [],
  exclude: [],
  min_price: null,
  max_price: null,
  areas: [],
  max_age_hours: null,
  min_seller_zhima: null,
  min_seller_reg_days: null,
  blacklist_sellers: [],
})

export const emptyTask = (): TaskIn => ({
  name: '',
  keywords: [],
  min_price: null,
  max_price: null,
  province: null,
  city: null,
  publish_days: null,
  personal_only: false,
  free_shipping: false,
  sort: 'newest',
  max_pages: 1,
  rules: emptyRules(),
  criteria: '',
  decision_mode: 'ai',
  analyze_images: true,
  ai_prescreen: true,
  fetch_seller_profile: false,
  notify_conditional: false,
  price_drop_percent: 0,
  account_id: null,
  cron: '*/30 8-23 * * *',
  enabled: false,
})

