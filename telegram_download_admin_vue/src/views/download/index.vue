<template>
  <div class="download-page">
    <el-row :gutter="16">
      <el-col :lg="12" :md="24">
        <el-card class="page-card" shadow="never">
          <div slot="header" class="card-title">任务配置</div>
          <el-form :model="form" label-width="118px" size="small">
            <el-form-item label="任务服务器">
              <el-input v-model="form.serverBase" placeholder="http://127.0.0.1:8787" @change="saveLocalForm" />
            </el-form-item>
            <el-form-item label="API Token">
              <el-input v-model="form.token" show-password placeholder="服务端 api_token，可为空" @change="saveTokenValue" />
            </el-form-item>
            <el-form-item label="API ID">
              <el-input v-model="form.apiId" placeholder="Telegram API ID" @change="saveLocalForm" />
            </el-form-item>
            <el-form-item label="API Hash">
              <el-input v-model="form.apiHash" show-password placeholder="Telegram API Hash" @change="saveLocalForm" />
            </el-form-item>
            <el-form-item label="频道">
              <el-input v-model="form.channel" placeholder="@channel 或 t.me/channel" @change="saveLocalForm" />
            </el-form-item>
            <el-form-item label="输出目录">
              <el-input v-model="form.outputDir" placeholder="downloads" @change="saveLocalForm" />
            </el-form-item>
            <el-form-item label="并发数">
              <el-input-number v-model="form.concurrency" :min="1" :max="20" controls-position="right" @change="saveLocalForm" />
            </el-form-item>
            <el-form-item label="上传账号">
              <el-input v-model="form.uploadAccount" placeholder="上传服务账号" @change="saveLocalForm" />
            </el-form-item>
            <el-form-item label="上传密码">
              <el-input v-model="form.uploadPassword" show-password placeholder="上传服务密码" @change="saveLocalForm" />
            </el-form-item>
            <el-form-item label="上传Token">
              <el-input v-model="form.uploadApiToken" show-password placeholder="可为空" @change="saveLocalForm" />
            </el-form-item>
            <el-form-item label="自动上传">
              <el-select v-model="form.autoUpload" clearable placeholder="默认" @change="saveLocalForm">
                <el-option label="默认" value="" />
                <el-option label="是" value="true" />
                <el-option label="否" value="false" />
              </el-select>
            </el-form-item>
            <el-form-item label="上传元数据">
              <el-select v-model="form.uploadMeta" clearable placeholder="默认" @change="saveLocalForm">
                <el-option label="默认" value="" />
                <el-option label="是" value="true" />
                <el-option label="否" value="false" />
              </el-select>
            </el-form-item>
            <el-form-item label="短视频阈值">
              <el-input-number v-model="form.shortThreshold" :min="0" controls-position="right" @change="saveLocalForm" />
              <span class="muted unit-text">秒</span>
            </el-form-item>
            <el-form-item label="过滤时长">
              <el-input-number v-model="form.minDuration" :min="0" controls-position="right" @change="saveLocalForm" />
              <span class="muted unit-text">秒以下不展示/不上传</span>
            </el-form-item>
            <el-form-item label="每页条数">
              <el-input-number v-model="form.previewLimit" :min="1" :max="50" controls-position="right" @change="saveLocalForm" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" icon="el-icon-check" :loading="saving" @click="saveServerConfig">保存配置</el-button>
              <el-button icon="el-icon-refresh" :loading="loading" @click="loadServerConfig">读取配置</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script>
import { getConfig, updateConfig } from '@/api/download'
import { loadDownloadForm, saveDownloadForm } from '@/utils/downloadForm'

export default {
  name: 'Download',
  data() {
    return {
      form: loadDownloadForm(),
      loading: false,
      saving: false
    }
  },
  created() {
    this.loadServerConfig()
  },
  methods: {
    saveLocalForm() {
      saveDownloadForm(this.form)
    },
    saveTokenValue() {
      this.$store.dispatch('user/setToken', this.form.token)
      this.saveLocalForm()
    },
    async loadServerConfig() {
      this.loading = true
      try {
        const data = await getConfig()
        if (data.telegram_api_id) this.form.apiId = data.telegram_api_id
        if (data.telegram_api_hash) this.form.apiHash = data.telegram_api_hash
        if (data.download_root) this.form.outputDir = data.download_root
        if (data.telegram_download_concurrency) {
          this.form.concurrency = Number(data.telegram_download_concurrency)
        }
        if (data.upload_account) this.form.uploadAccount = data.upload_account
        if (data.upload_password) this.form.uploadPassword = data.upload_password
        if (data.upload_api_token) this.form.uploadApiToken = data.upload_api_token
        if (data.video_type_threshold_seconds !== undefined && data.video_type_threshold_seconds !== null) {
          this.form.shortThreshold = Number(data.video_type_threshold_seconds)
        }
        if (data.min_video_duration_seconds !== undefined && data.min_video_duration_seconds !== null) {
          this.form.minDuration = Number(data.min_video_duration_seconds)
        }
        this.saveLocalForm()
      } catch (error) {
        // 后端未启动或未配置 token 时，保留本地表单可用。
      } finally {
        this.loading = false
      }
    },
    async saveServerConfig() {
      this.saving = true
      try {
        this.saveTokenValue()
        await updateConfig({
          telegram_api_id: this.form.apiId,
          telegram_api_hash: this.form.apiHash,
          download_root: this.form.outputDir,
          telegram_download_concurrency: Number(this.form.concurrency || 1),
          upload_account: this.form.uploadAccount,
          upload_password: this.form.uploadPassword,
          upload_api_token: this.form.uploadApiToken,
          video_type_threshold_seconds: Number(this.form.shortThreshold || 0),
          min_video_duration_seconds: Number(this.form.minDuration || 0)
        })
        this.saveLocalForm()
        this.$message.success('配置已保存')
      } finally {
        this.saving = false
      }
    }
  }
}
</script>

<style lang="scss" scoped>
.download-page {
  .page-card + .page-card {
    margin-top: 16px;
  }

  .card-title {
    font-weight: 700;
  }

  .unit-text {
    margin-left: 8px;
  }
}
</style>
