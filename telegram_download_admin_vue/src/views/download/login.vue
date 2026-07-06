<template>
  <div class="login-page">
    <el-card class="page-card login-card" shadow="never">
      <div slot="header" class="card-title">
        <span>Telegram 账号登录</span>
        <el-tag :type="loginAuthorized ? 'success' : 'info'" size="mini">{{ loginAuthorized ? '已登录' : '未确认' }}</el-tag>
      </div>

      <div v-if="loginAuthorized" class="account-panel">
        <div class="account-row"><strong>昵称：</strong><span>{{ account.nickname || '-' }}</span></div>
        <div class="account-row"><strong>手机号：</strong><span>{{ maskedPhone }}</span></div>
        <div class="account-row"><strong>用户ID：</strong><span>{{ account.id || '-' }}</span></div>
        <div class="account-row"><strong>状态：</strong><span>已登录</span></div>
        <div class="account-row"><strong>最后登录时间：</strong><span>{{ formatDateTime(account.checked_at) }}</span></div>
        <div class="account-row"><strong>Session状态：</strong><span>{{ account.session_status || '有效' }}</span></div>
        <div class="account-actions">
          <el-button type="warning" :loading="loggingOut" @click="logoutAccount">注销账号</el-button>
          <el-button plain @click="relogin">重新登录</el-button>
        </div>
      </div>

      <el-form v-else :model="form" label-width="118px" size="small">
        <el-form-item label="API ID">
          <el-input v-model="form.apiId" placeholder="Telegram API ID" @change="saveLocalForm" />
        </el-form-item>
        <el-form-item label="API Hash">
          <el-input v-model="form.apiHash" show-password placeholder="Telegram API Hash" @change="saveLocalForm" />
        </el-form-item>
        <el-form-item label="国家/区号">
          <el-input v-model="form.countryCode" placeholder="+86" @change="saveLocalForm" />
        </el-form-item>
        <el-form-item label="手机号">
          <el-input v-model="form.phoneNumber" placeholder="请输入手机号" @change="saveLocalForm" />
        </el-form-item>
        <el-form-item label="验证码">
          <el-input v-model="form.code" placeholder="验证码" />
        </el-form-item>
        <el-form-item label="两步密码">
          <el-input v-model="form.password" show-password placeholder="如有则填写" />
        </el-form-item>
        <el-form-item>
          <el-button icon="el-icon-message" :loading="sendingCode" @click="sendCode">发送验证码</el-button>
          <el-button type="primary" icon="el-icon-unlock" :loading="loggingIn" @click="verifyCode">登录</el-button>
          <el-button icon="el-icon-view" :loading="checkingLogin" @click="checkLogin">检测</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script>
import { sendLoginCode, verifyLoginCode, getLoginStatus, logout } from '@/api/download'
import { loadDownloadForm, saveDownloadForm } from '@/utils/downloadForm'
import { formatDateTime } from '@/utils/format'

export default {
  name: 'DownloadLogin',
  data() {
    return {
      form: loadDownloadForm(),
      loginAuthorized: false,
      account: {},
      sendingCode: false,
      loggingIn: false,
      checkingLogin: false,
      loggingOut: false
    }
  },
  computed: {
    maskedPhone() {
      const phone = String(this.account.phone || this.phone() || '')
      if (!phone) return '-'
      if (phone.length <= 6) return phone
      return `${phone.slice(0, 3)}****${phone.slice(-4)}`
    }
  },
  created() {
    this.checkLoginOnStartup()
  },
  methods: {
    formatDateTime,
    saveLocalForm() {
      saveDownloadForm(this.form)
    },
    phone() {
      return `${String(this.form.countryCode || '').trim()}${String(this.form.phoneNumber || '').trim()}`
    },
    ensureOutputDir() {
      if (!this.form.outputDir) {
        this.form.outputDir = 'downloads'
      }
      return this.form.outputDir
    },
    requireLoginFields() {
      if (!this.form.apiId || !this.form.apiHash) {
        this.$message.warning('请填写 API ID 和 API Hash')
        return false
      }
      return true
    },
    async checkLoginOnStartup() {
      if (!this.form.apiId || !this.form.apiHash) return
      await this.checkLogin({ silent: true })
    },
    async sendCode() {
      if (!this.requireLoginFields()) return
      if (!this.form.phoneNumber) {
        this.$message.warning('请填写手机号')
        return
      }
      this.sendingCode = true
      try {
        await sendLoginCode({
          api_id: this.form.apiId,
          api_hash: this.form.apiHash,
          output_dir: this.ensureOutputDir(),
          phone: this.phone()
        })
        this.saveLocalForm()
        this.$message.success('验证码已发送')
      } catch (error) {
        this.$message.error(error.message || '发送验证码失败')
      } finally {
        this.sendingCode = false
      }
    },
    async verifyCode() {
      if (!this.requireLoginFields()) return
      this.loggingIn = true
      try {
        await verifyLoginCode({
          api_id: this.form.apiId,
          api_hash: this.form.apiHash,
          output_dir: this.ensureOutputDir(),
          phone: this.phone(),
          code: this.form.code,
          password: this.form.password || undefined
        })
        await this.checkLogin({ silent: true })
        this.saveLocalForm()
        this.$message.success('登录成功')
      } catch (error) {
        this.$message.error(error.message || '登录失败')
      } finally {
        this.loggingIn = false
      }
    },
    async checkLogin(options = {}) {
      if (!this.form.apiId || !this.form.apiHash) {
        if (!options.silent) this.$message.warning('请填写 API ID 和 API Hash')
        return
      }
      this.checkingLogin = true
      try {
        const data = await getLoginStatus({
          api_id: this.form.apiId,
          api_hash: this.form.apiHash,
          output_dir: this.ensureOutputDir()
        })
        this.loginAuthorized = Boolean(data.authorized)
        this.account = data.user || {}
        if (!options.silent) {
          this.$message({
            type: this.loginAuthorized ? 'success' : 'warning',
            message: this.loginAuthorized ? 'Telegram 已登录' : 'Telegram 未登录'
          })
        }
      } catch (error) {
        this.loginAuthorized = false
        this.account = {}
        if (!options.silent) this.$message.error(error.message || '检测登录状态失败')
      } finally {
        this.checkingLogin = false
      }
    },
    async logoutAccount() {
      if (!this.requireLoginFields()) return
      this.loggingOut = true
      try {
        await logout({
          api_id: this.form.apiId,
          api_hash: this.form.apiHash,
          output_dir: this.ensureOutputDir()
        })
        this.loginAuthorized = false
        this.account = {}
        this.form.code = ''
        this.form.password = ''
        this.$message.success('账号已注销')
      } finally {
        this.loggingOut = false
      }
    },
    relogin() {
      this.loginAuthorized = false
      this.account = {}
      this.form.code = ''
      this.form.password = ''
    }
  }
}
</script>

<style lang="scss" scoped>
.login-page {
  max-width: 720px;
}

.login-card {
  min-height: 520px;
}

.card-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 700;
}

.account-panel {
  min-height: 420px;
  padding: 16px 64px 20px;
  display: flex;
  flex-direction: column;
}

.account-row {
  margin: 12px 0;
  color: $textSecondary;
  font-size: 14px;
}

.account-row strong {
  color: $textRegular;
  margin-right: 8px;
}

.account-actions {
  margin-top: auto;
  display: flex;
  justify-content: flex-end;
  gap: 28px;
}
</style>
