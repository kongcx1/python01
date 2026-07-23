<template>
  <div class="external-page">
    <el-card class="page-card" shadow="never">
      <div slot="header" class="toolbar">
        <strong>JSON视频上传</strong>
        <div class="actions">
          <el-upload
            action=""
            accept=".json,application/json"
            :auto-upload="false"
            :show-file-list="false"
            :on-change="handleFileChange"
          >
            <el-button icon="el-icon-folder-opened">选择JSON</el-button>
          </el-upload>
          <el-button icon="el-icon-refresh" @click="parseJson">解析</el-button>
          <el-button type="primary" icon="el-icon-upload2" :loading="uploading" :disabled="!items.length" @click="submitUpload">上传到服务器</el-button>
        </div>
      </div>

      <el-input
        v-model="jsonText"
        type="textarea"
        :rows="12"
        resize="vertical"
        placeholder="粘贴JSON内容"
        @blur="parseJson"
      />

      <div class="summary">
        <span>已解析：{{ items.length }}</span>
        <span v-if="result">状态：{{ result.status }}，成功：{{ result.success }}，失败：{{ result.failed }}</span>
        <span v-if="jobId">任务：{{ jobId }}</span>
        <el-button v-if="taskId" size="mini" type="text" @click="$router.push('/download/tasks')">查看下载列表 #{{ taskId }}</el-button>
      </div>

      <el-table v-if="items.length" :data="items" border size="small" class="preview-table">
        <el-table-column type="index" width="56" />
        <el-table-column label="标题/内容" min-width="260">
          <template slot-scope="{ row }">
            <div class="title-text">{{ row.title || '--' }}</div>
          </template>
        </el-table-column>
        <el-table-column label="标签" min-width="220">
          <template slot-scope="{ row }">
            <el-tag v-for="tag in row.tags" :key="tag" size="mini" class="tag">{{ tag }}</el-tag>
            <span v-if="!row.tags.length">--</span>
          </template>
        </el-table-column>
        <el-table-column label="视频URL" min-width="320">
          <template slot-scope="{ row }">
            <span class="url-text">{{ row.videoUrl || '--' }}</span>
          </template>
        </el-table-column>
      </el-table>

      <el-table v-if="resultItems.length" :data="resultItems" border size="small" class="preview-table">
        <el-table-column prop="index" label="#" width="56" />
        <el-table-column prop="status" label="状态" width="90">
          <template slot-scope="{ row }">
            <el-tag :type="row.status === 'done' ? 'success' : 'danger'" size="mini">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="video_id" label="video_id" width="120" />
        <el-table-column prop="thumbnail_id" label="封面ID" width="120" />
        <el-table-column prop="title" label="title/content" min-width="260" />
        <el-table-column prop="error" label="错误" min-width="240" />
      </el-table>
    </el-card>
  </div>
</template>

<script>
import { uploadExternalVideoLibrary, getExternalVideoLibraryJob } from '@/api/download'

export default {
  name: 'ExternalVideoLibrary',
  data() {
    return {
      jsonText: '',
      parsedPayload: null,
      items: [],
      uploading: false,
      jobId: '',
      taskId: '',
      pollTimer: null,
      result: null
    }
  },
  computed: {
    resultItems() {
      return (this.result && this.result.items) || []
    }
  },
  beforeDestroy() {
    this.stopPolling()
  },
  methods: {
    handleFileChange(file) {
      const raw = file.raw || file
      const reader = new FileReader()
      reader.onload = event => {
        this.jsonText = String(event.target.result || '')
        this.parseJson()
      }
      reader.readAsText(raw, 'utf-8')
    },
    parseJson() {
      const text = String(this.jsonText || '').trim()
      if (!text) {
        this.parsedPayload = null
        this.items = []
        return
      }
      try {
        const payload = JSON.parse(text)
        const tasks = Array.isArray(payload) ? payload : (Array.isArray(payload.tasks) ? payload.tasks : [payload])
        this.parsedPayload = payload
        this.items = tasks.map(item => {
          const tags = Array.isArray(item.tags)
            ? item.tags.map(tag => (tag && typeof tag === 'object') ? tag.text : tag).filter(Boolean)
            : []
          const captured = item.capturedDownload || {}
          const fallbackDownload = Array.isArray(item.downloads)
            ? item.downloads.find(entry => entry && entry.kind === 'download')
            : null
          return {
            title: item.title || '',
            tags,
            videoUrl: captured.url || (fallbackDownload && fallbackDownload.url) || ''
          }
        })
        this.result = null
        this.jobId = ''
        this.taskId = ''
        this.stopPolling()
      } catch (error) {
        this.parsedPayload = null
        this.items = []
        this.$message.error('JSON解析失败')
      }
    },
    async submitUpload() {
      if (!this.parsedPayload) this.parseJson()
      if (!this.parsedPayload || !this.items.length) {
        this.$message.warning('请先导入JSON')
        return
      }
      this.uploading = true
      try {
        const data = await uploadExternalVideoLibrary({
          payload: this.parsedPayload
        })
        this.jobId = data.job_id
        this.taskId = data.task_id
        this.result = data
        this.$message.success('上传任务已开始')
        this.pollJob()
      } catch (error) {
        this.$message.error(error.message || '上传失败')
        this.uploading = false
      }
    },
    async pollJob() {
      if (!this.jobId) return
      try {
        this.result = await getExternalVideoLibraryJob(this.jobId)
        this.taskId = this.result.task_id || this.taskId
        if (this.result.status === 'done' || this.result.status === 'failed') {
          this.uploading = false
          this.stopPolling()
          if (this.result.status === 'done') {
            this.$message.success(`上传完成：成功 ${this.result.success}，失败 ${this.result.failed}`)
          }
          return
        }
      } catch (error) {
        this.uploading = false
        this.stopPolling()
        this.$message.error(error.message || '查询上传任务失败')
        return
      }
      this.stopPolling()
      this.pollTimer = window.setTimeout(() => this.pollJob(), 2000)
    },
    stopPolling() {
      if (this.pollTimer) {
        window.clearTimeout(this.pollTimer)
        this.pollTimer = null
      }
    }
  }
}
</script>

<style scoped>
.external-page {
  padding: 16px;
}

.page-card {
  border-radius: 4px;
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.summary {
  display: flex;
  gap: 24px;
  margin: 14px 0;
  color: #606266;
}

.preview-table {
  margin-top: 12px;
}

.title-text {
  color: #1f2d3d;
  font-weight: 600;
  line-height: 1.45;
}

.url-text {
  display: block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tag {
  margin: 2px 4px 2px 0;
}
</style>
