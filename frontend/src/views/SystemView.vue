<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { Plus, Refresh, Search } from '@element-plus/icons-vue'
import {
  changePassword,
  createUser,
  listAuditLogs,
  listUsers,
  updateUser,
  type AuditOut,
  type Role,
  type UserOut,
} from '@/api/system'
import JsonBlock from '@/components/JsonBlock.vue'
import { useAuthStore } from '@/stores/auth'
import { useAccountsStore } from '@/stores/accounts'
import { useMobile } from '@/composables/useMobile'
import { fmtTime, roleMap } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const accounts = useAccountsStore()
const isMobile = useMobile()

const tab = ref(typeof route.query.tab === 'string' ? route.query.tab : auth.isAdmin ? 'users' : 'password')
watch(
  () => route.query.tab,
  (t) => {
    if (typeof t === 'string') tab.value = t
  },
)
watch(tab, (t) => {
  router.replace({ query: { ...route.query, tab: t } })
  if (t === 'users' && !users.value.length) loadUsers()
  if (t === 'audit' && !logs.value.length) loadLogs()
})

// ================================================================ 用户管理
const users = ref<UserOut[]>([])
const usersLoading = ref(false)

async function loadUsers() {
  if (!auth.isAdmin) return
  usersLoading.value = true
  try {
    users.value = await listUsers()
  } finally {
    usersLoading.value = false
  }
}

const roleHelp: Record<Role, string> = {
  admin: '管理员：可见全部账号，管理用户与审计日志',
  operator: '运营：管理自己添加或被授权的账号',
  member: '成员：管理自己添加或被授权的账号',
}

const uEdit = reactive({
  open: false,
  saving: false,
  id: null as number | null,
  username: '',
  password: '',
  role: 'member' as Role,
  is_active: true,
})

function openUserCreate() {
  Object.assign(uEdit, { open: true, id: null, username: '', password: '', role: 'member', is_active: true })
}
function openUserEdit(u: UserOut) {
  Object.assign(uEdit, { open: true, id: u.id, username: u.username, password: '', role: u.role, is_active: u.is_active })
}

async function saveUser() {
  if (!uEdit.id) {
    if (uEdit.username.trim().length < 3) return ElMessage.warning('用户名至少 3 个字符')
    if (uEdit.password.length < 8) return ElMessage.warning('密码至少 8 位')
  } else if (uEdit.password && uEdit.password.length < 8) {
    return ElMessage.warning('新密码至少 8 位')
  }
  uEdit.saving = true
  try {
    if (uEdit.id) {
      await updateUser(uEdit.id, { role: uEdit.role, is_active: uEdit.is_active, password: uEdit.password || undefined })
    } else {
      await createUser({ username: uEdit.username.trim(), password: uEdit.password, role: uEdit.role })
    }
    ElMessage.success('已保存')
    uEdit.open = false
    await loadUsers()
  } catch {
    /* 拦截器已提示 */
  } finally {
    uEdit.saving = false
  }
}

async function toggleActive(u: UserOut, v: boolean) {
  try {
    await updateUser(u.id, { is_active: v })
    u.is_active = v
    ElMessage.success(v ? '已启用' : '已停用')
  } catch {
    /* 拦截器已提示 */
  }
}

// ================================================================ 审计日志
const PAGE = 50
const logs = ref<AuditOut[]>([])
const logsLoading = ref(false)
const logPage = ref(1)
const logHasMore = ref(false)
const logFilter = reactive({ action: '', account_id: undefined as number | undefined })

const actorMap: Record<string, { label: string; type: 'primary' | 'warning' | 'success' | 'info' }> = {
  human: { label: '人工', type: 'primary' },
  rule: { label: '规则', type: 'warning' },
  ai: { label: 'AI', type: 'success' },
  system: { label: '系统', type: 'info' },
}

async function loadLogs(p = 1) {
  if (!auth.isAdmin) return
  logsLoading.value = true
  try {
    const rows = await listAuditLogs({
      action: logFilter.action.trim() || undefined,
      account_id: logFilter.account_id,
      limit: PAGE,
      offset: (p - 1) * PAGE,
    })
    logs.value = rows
    logPage.value = p
    logHasMore.value = rows.length === PAGE
  } finally {
    logsLoading.value = false
  }
}

const userName = (id: number | null) => (id === null ? '-' : users.value.find((u) => u.id === id)?.username || `#${id}`)

// ================================================================ 修改密码
const pwdRef = ref<FormInstance>()
const pwd = reactive({ old: '', next: '', confirm: '', saving: false })
const pwdRules: FormRules = {
  old: [{ required: true, message: '请输入原密码', trigger: 'blur' }],
  next: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 8, message: '新密码至少 8 位', trigger: 'blur' },
  ],
  confirm: [
    { required: true, message: '请再次输入新密码', trigger: 'blur' },
    {
      validator: (_r: unknown, v: string, cb: (e?: Error) => void) => (v === pwd.next ? cb() : cb(new Error('两次输入不一致'))),
      trigger: 'blur',
    },
  ],
}

async function submitPwd() {
  if (!(await pwdRef.value?.validate().catch(() => false))) return
  pwd.saving = true
  try {
    await changePassword(pwd.old, pwd.next)
    ElMessage.success('密码已修改')
    pwdRef.value?.resetFields()
  } catch {
    /* 拦截器已提示 */
  } finally {
    pwd.saving = false
  }
}

onMounted(() => {
  accounts.load().catch(() => undefined)
  if (auth.isAdmin) {
    loadUsers()
    if (tab.value === 'audit') loadLogs()
  }
})
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>系统</h2>
        <div class="sub">当前用户：{{ auth.user?.username }}（{{ roleMap[auth.user?.role || ''] || auth.user?.role }}）</div>
      </div>
    </div>

    <el-card shadow="never">
      <el-tabs v-model="tab">
        <el-tab-pane v-if="auth.isAdmin" label="用户管理" name="users">
          <div class="bar">
            <el-button type="primary" :icon="Plus" @click="openUserCreate">添加用户</el-button>
            <el-button :icon="Refresh" :loading="usersLoading" @click="loadUsers">刷新</el-button>
          </div>
          <div class="table-wrap">
            <el-table v-loading="usersLoading" :data="users">
              <el-table-column label="ID" prop="id" width="70" />
              <el-table-column label="用户名" prop="username" min-width="140" />
              <el-table-column label="角色" width="110">
                <template #default="{ row }">
                  <el-tag size="small" :type="row.role === 'admin' ? 'danger' : 'info'">{{ roleMap[row.role] || row.role }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="状态" width="90">
                <template #default="{ row }">
                  <el-switch
                    :model-value="row.is_active"
                    size="small"
                    :disabled="row.id === auth.user?.id"
                    @change="(v: string | number | boolean) => toggleActive(row as UserOut, !!v)"
                  />
                </template>
              </el-table-column>
              <el-table-column label="最近登录" width="160">
                <template #default="{ row }">{{ fmtTime(row.last_login_at) }}</template>
              </el-table-column>
              <el-table-column label="操作" width="90">
                <template #default="{ row }">
                  <el-button size="small" link type="primary" @click="openUserEdit(row as UserOut)">编辑</el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-tab-pane>

        <el-tab-pane v-if="auth.isAdmin" label="审计日志" name="audit">
          <div class="bar">
            <el-input v-model="logFilter.action" placeholder="操作，如 account.update" clearable class="w220" :prefix-icon="Search" @keyup.enter="loadLogs()" @clear="loadLogs()" />
            <el-select v-model="logFilter.account_id" clearable placeholder="全部账号" class="w180" @change="loadLogs()">
              <el-option v-for="a in accounts.list" :key="a.id" :value="a.id" :label="a.remark || a.nickname || a.unb" />
            </el-select>
            <el-button :icon="Refresh" :loading="logsLoading" @click="loadLogs(logPage)">刷新</el-button>
          </div>
          <div class="table-wrap">
            <el-table v-loading="logsLoading" :data="logs" size="small" empty-text="暂无审计记录">
              <el-table-column type="expand">
                <template #default="{ row }">
                  <div class="expand">
                    <div v-if="row.error" class="err small">错误：{{ row.error }}</div>
                    <JsonBlock :value="row.detail" />
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="时间" width="160">
                <template #default="{ row }">{{ fmtTime(row.created_at, true) }}</template>
              </el-table-column>
              <el-table-column label="执行者" width="120">
                <template #default="{ row }">
                  <el-tag size="small" :type="actorMap[row.actor_type]?.type || 'info'">{{ actorMap[row.actor_type]?.label || row.actor_type }}</el-tag>
                  <span v-if="row.user_id" class="small muted"> {{ userName(row.user_id) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="操作" prop="action" min-width="150">
                <template #default="{ row }"><span class="mono small">{{ row.action }}</span></template>
              </el-table-column>
              <el-table-column label="账号" width="120">
                <template #default="{ row }">{{ row.account_id ? accounts.nameOf(row.account_id) : '-' }}</template>
              </el-table-column>
              <el-table-column label="对象" min-width="140">
                <template #default="{ row }">
                  <span v-if="row.target_type" class="small">{{ row.target_type }} <span class="mono">{{ row.target_id }}</span></span>
                  <span v-else class="muted">-</span>
                </template>
              </el-table-column>
              <el-table-column label="结果" width="80">
                <template #default="{ row }">
                  <el-tag size="small" :type="row.success ? 'success' : 'danger'">{{ row.success ? '成功' : '失败' }}</el-tag>
                </template>
              </el-table-column>
            </el-table>
          </div>
          <div class="pager">
            <el-button size="small" :disabled="logPage <= 1 || logsLoading" @click="loadLogs(logPage - 1)">上一页</el-button>
            <span class="muted small">第 {{ logPage }} 页</span>
            <el-button size="small" :disabled="!logHasMore || logsLoading" @click="loadLogs(logPage + 1)">下一页</el-button>
          </div>
        </el-tab-pane>

        <el-tab-pane label="修改密码" name="password">
          <el-form ref="pwdRef" :model="pwd" :rules="pwdRules" label-width="100px" :label-position="isMobile ? 'top' : 'right'" class="pwd-form">
            <el-form-item label="原密码" prop="old">
              <el-input v-model="pwd.old" type="password" show-password autocomplete="current-password" />
            </el-form-item>
            <el-form-item label="新密码" prop="next">
              <el-input v-model="pwd.next" type="password" show-password autocomplete="new-password" />
            </el-form-item>
            <el-form-item label="确认新密码" prop="confirm">
              <el-input v-model="pwd.confirm" type="password" show-password autocomplete="new-password" @keyup.enter="submitPwd" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="pwd.saving" @click="submitPwd">修改密码</el-button>
            </el-form-item>
          </el-form>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <el-dialog v-model="uEdit.open" :title="uEdit.id ? `编辑用户 · ${uEdit.username}` : '添加用户'" width="480px">
      <el-form label-width="90px" :label-position="isMobile ? 'top' : 'right'">
        <el-form-item label="用户名" required>
          <el-input v-model="uEdit.username" :disabled="!!uEdit.id" maxlength="64" autocomplete="off" />
        </el-form-item>
        <el-form-item :label="uEdit.id ? '重置密码' : '密码'" :required="!uEdit.id">
          <el-input v-model="uEdit.password" type="password" show-password :placeholder="uEdit.id ? '留空表示不修改' : '至少 8 位'" autocomplete="new-password" />
        </el-form-item>
        <el-form-item label="角色">
          <el-radio-group v-model="uEdit.role" :disabled="uEdit.id === auth.user?.id">
            <el-radio-button value="admin">管理员</el-radio-button>
            <el-radio-button value="operator">运营</el-radio-button>
            <el-radio-button value="member">成员</el-radio-button>
          </el-radio-group>
          <div class="form-tip">{{ roleHelp[uEdit.role] }}</div>
        </el-form-item>
        <el-form-item v-if="uEdit.id" label="启用">
          <el-switch v-model="uEdit.is_active" :disabled="uEdit.id === auth.user?.id" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="uEdit.open = false">取消</el-button>
        <el-button type="primary" :loading="uEdit.saving" @click="saveUser">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.bar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}
.bar .el-button + .el-button {
  margin-left: 0;
}
.w180 {
  width: 180px;
}
.w220 {
  width: 220px;
}
.expand {
  padding: 4px 16px;
}
.err {
  color: var(--el-color-danger);
  margin-bottom: 6px;
}
.pager {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 10px;
  margin-top: 12px;
}
.pwd-form {
  max-width: 440px;
}
</style>
