import assert from 'node:assert/strict'
import { test } from 'node:test'
import { buildQuickSearch } from '../src/utils/quickSearch.ts'

test('AI解析失败原样抛出，不以关键词猜测代替需求', async () => {
  const error = new Error('模型服务暂不可用')
  const input = '2000以内的iPhone13，不要维修过的，最好深圳同城'
  await assert.rejects(buildQuickSearch(input, async (description) => {
    assert.equal(description, input)
    throw error
  }), (caught) => caught === error)
})

test('解析成功保留价格、地区和核验条件，默认只搜一次', async () => {
  const task = await buildQuickSearch('2000以内的iPhone13，不要维修过的', async () => ({
    name: 'iPhone13', keywords: ['iPhone13'], min_price: 500, max_price: 2000,
    province: '广东', city: '深圳', publish_days: 3, personal_only: true,
    rules: { include_all: ['128G'], exclude: ['维修'] }, criteria: '电池健康85%以上，维修史必须核验',
  }))
  assert.equal(task.enabled, false)
  assert.equal(task.max_price, 2000)
  assert.equal(task.min_price, 500)
  assert.equal(task.city, '深圳')
  assert.equal(task.personal_only, true)
  assert.deepEqual(task.rules.exclude, ['维修'])
  assert.match(task.criteria, /必须核验/)
})

test('普通关键词不调用AI，空输入不生成任务', async () => {
  const generate = async () => { throw new Error('不应调用模型') }
  assert.deepEqual((await buildQuickSearch('iPhone13', generate)).keywords, ['iPhone13'])
  await assert.rejects(buildQuickSearch(' ', generate), /请输入/)
})

test('AI缺少关键词时明确失败', async () => {
  await assert.rejects(buildQuickSearch('2000以内的iPhone13，不要维修过的', async () => ({
    name: 'iPhone13', keywords: [], min_price: null, max_price: 2000, province: null,
    city: null, publish_days: null, personal_only: false,
    rules: { include_all: [], exclude: [] }, criteria: '无拆修',
  })), /有效的搜索关键词/)
})
