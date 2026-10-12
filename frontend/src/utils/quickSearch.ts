import type { TaskDraft, TaskIn } from '@/api/buyer'
import { emptyTask } from './taskDefaults.ts'

/** 完整需求先解析成功，再构造一次搜索；失败直接交给调用方，不猜测替代条件。 */
export async function buildQuickSearch(text: string, generate: (description: string) => Promise<TaskDraft>): Promise<TaskIn> {
  const input = text.trim()
  if (!input) throw new Error('请输入搜索需求')
  const sentence = input.length >= 20 || (input.length >= 8 && /[，。,；;！!？?]|想买|想要|求|预算|以内|以下|左右|不要|最好|电池|成色/.test(input))
  if (!sentence) {
    const keywords = input.split(/[,，、;；]+/).map((keyword) => keyword.trim()).filter(Boolean)
    if (keywords.length > 8) throw new Error('搜索关键词最多 8 个，请减少后重试')
    return { ...emptyTask(), name: input.slice(0, 32), keywords }
  }

  const draft = await generate(input)
  if (!draft.keywords?.length || draft.keywords.some((keyword) => !keyword.trim()) || draft.keywords.length > 8) {
    throw new Error('AI 未返回有效的搜索关键词，请修改需求或手动填写条件')
  }
  return {
    ...emptyTask(),
    name: draft.name.slice(0, 32),
    keywords: draft.keywords,
    min_price: draft.min_price,
    max_price: draft.max_price,
    province: draft.province,
    city: draft.city,
    publish_days: draft.publish_days,
    personal_only: draft.personal_only,
    rules: { ...emptyTask().rules, include_all: draft.rules.include_all, exclude: draft.rules.exclude },
    criteria: draft.criteria,
  }
}
