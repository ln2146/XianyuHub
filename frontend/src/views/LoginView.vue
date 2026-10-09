<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { Lock, User } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const formRef = ref<FormInstance>()
const form = reactive({ username: '', password: '' })
const loading = ref(false)
const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

async function submit() {
  if (!(await formRef.value?.validate().catch(() => false))) return
  loading.value = true
  try {
    await auth.login(form.username.trim(), form.password)
    ElMessage.success('登录成功')
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/dashboard'
    router.replace(redirect.startsWith('/') && !redirect.startsWith('/login') ? redirect : '/dashboard')
  } catch {
    /* 错误提示由拦截器处理 */
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <div class="logo">
        <img src="/icon.svg" alt="鱼塘管家" />
        <div>
          <h1>鱼塘管家</h1>
          <p>XianyuHub · 自托管闲鱼买卖助手</p>
        </div>
      </div>
      <el-form ref="formRef" :model="form" :rules="rules" size="large" @submit.prevent="submit">
        <el-form-item prop="username">
          <el-input v-model="form.username" placeholder="用户名" :prefix-icon="User" autocomplete="username" />
        </el-form-item>
        <el-form-item prop="password">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="密码"
            :prefix-icon="Lock"
            show-password
            autocomplete="current-password"
            @keyup.enter="submit"
          />
        </el-form-item>
        <el-button type="primary" :loading="loading" class="submit" native-type="submit">登录</el-button>
      </el-form>
      <p class="tip">首次部署的管理员账号见后端启动日志或 .env 配置</p>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  background:
    radial-gradient(circle at 20% 20%, rgba(30, 158, 106, 0.12), transparent 40%),
    radial-gradient(circle at 80% 80%, rgba(64, 158, 255, 0.1), transparent 40%),
    var(--xh-bg);
}
.login-card {
  width: 100%;
  max-width: 380px;
  background: #fff;
  border-radius: 14px;
  padding: 32px 28px 24px;
  box-shadow: 0 10px 40px rgba(31, 35, 41, 0.08);
}
.logo {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 28px;
}
.logo img {
  width: 52px;
  height: 52px;
}
.logo h1 {
  margin: 0;
  font-size: 22px;
  color: var(--xh-primary);
}
.logo p {
  margin: 4px 0 0;
  color: var(--xh-muted);
  font-size: 13px;
}
.submit {
  width: 100%;
  margin-top: 4px;
}
.tip {
  margin: 16px 0 0;
  text-align: center;
  font-size: 12px;
  color: var(--xh-muted);
}
</style>
