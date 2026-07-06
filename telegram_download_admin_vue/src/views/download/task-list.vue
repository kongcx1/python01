<template>
  <div class="task-list-page">
    <el-card class="page-card" shadow="never">
      <div slot="header" class="page-title">任务列表</div>

      <div class="filter-row">
        <div class="filter-item">
          <span class="filter-label">所属频道</span>
          <el-input v-model="filters.channel" size="small" placeholder="输入频道" clearable @keyup.enter.native="searchTasks" />
        </div>
        <div class="filter-item">
          <span class="filter-label">消息ID</span>
          <el-input v-model="filters.messageId" size="small" placeholder="输入消息ID" clearable @keyup.enter.native="searchTasks" />
        </div>
        <div class="filter-item">
          <span class="filter-label">文件名</span>
          <el-input v-model="filters.fileName" size="small" placeholder="输入文件名" clearable @keyup.enter.native="searchTasks" />
        </div>
        <div class="filter-item">
          <span class="filter-label">上传状态</span>
          <el-select v-model="filters.uploadStatus" size="small" placeholder="全部">
            <el-option label="全部" value="all" />
            <el-option label="未上传" value="none" />
            <el-option label="上传中" value="uploading" />
            <el-option label="已上传" value="done" />
            <el-option label="上传失败" value="failed" />
          </el-select>
        </div>
        <el-button type="primary" icon="el-icon-search" :loading="tasksLoading" @click="searchTasks">搜索</el-button>
        <el-button icon="el-icon-refresh-left" @click="resetFilters">重置</el-button>
        <el-button icon="el-icon-refresh" :loading="tasksLoading" @click="refreshTasks">刷新</el-button>
        <el-button :disabled="!selectedRows.length" @click="retrySelectedTasks">批量重试</el-button>
        <el-button :disabled="!selectedTaskIds.length" @click="deleteSelectedTasks">批量删除</el-button>
      </div>

      <el-table
        v-loading="tasksLoading"
        :data="pagedRows"
        border
        size="small"
        class="task-table"
        @selection-change="handleTaskSelection"
      >
        <el-table-column type="selection" width="54" />
        <el-table-column prop="channel" label="所属频道" min-width="150" />
        <el-table-column prop="message_id" label="消息ID" width="110" />
        <el-table-column label="" width="260">
          <template slot-scope="{ row }">
            <div class="media-cell">
              <div class="cover-wrap">
                <el-image v-if="mainImage(row)" class="cover" :src="imageUrl(row, mainImage(row))" fit="cover" />
                <div v-else class="cover empty-cover">无封面</div>
                <span class="play-mark"><i class="el-icon-video-play" /></span>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="名称/简介" min-width="280">
          <template slot-scope="{ row }">
            <div class="resource-title">{{ titleText(row) }}</div>
            <div class="resource-desc">{{ descText(row) }}</div>
          </template>
        </el-table-column>
        <el-table-column label="上传状态" width="120">
          <template slot-scope="{ row }">
            <el-tag :type="uploadTag(row.upload_status)" size="mini">{{ uploadStatusText(row.upload_status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="上传进度" width="180">
          <template slot-scope="{ row }">
            {{ formatBytes(row.upload_sent) }}/{{ formatBytes(row.upload_total) }}
          </template>
        </el-table-column>
        <el-table-column label="上传速度" width="110">
          <template slot-scope="{ row }">{{ formatSpeed(row.upload_speed_bps) }}</template>
        </el-table-column>
        <el-table-column label="创建时间" width="170">
          <template slot-scope="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="320" fixed="right">
          <template slot-scope="{ row }">
            <el-button size="mini" icon="el-icon-document" @click="openLog(row)">日志</el-button>
            <el-button size="mini" icon="el-icon-refresh-right" :disabled="!canRetry(row)" @click="retry(row)">重试</el-button>
            <el-button size="mini" type="primary" icon="el-icon-upload2" :disabled="!canReupload(row)" @click="reupload(row)">重新上传</el-button>
            <el-button size="mini" type="danger" @click="deleteOneTask(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination-row">
        <el-pagination
          background
          layout="total, sizes, prev, pager, next, jumper"
          :current-page="page"
          :page-size="pageSize"
          :page-sizes="[10, 20, 50, 100]"
          :total="filteredRows.length"
          @current-change="handlePageChange"
          @size-change="handleSizeChange"
        />
      </div>
    </el-card>

    <el-dialog title="任务日志" :visible.sync="logVisible" width="760px">
      <pre class="log-box">{{ logText }}</pre>
    </el-dialog>
  </div>
</template>

<script>
import { getTasks, getTaskLog, getTaskFiles, createTask, deleteTask } from '@/api/download'
import { formatBytes, formatSpeed, formatDateTime } from '@/utils/format'
import { getRuntimeBaseUrl } from '@/utils/request'
import { loadDownloadForm } from '@/utils/downloadForm'

export default {
  name: 'DownloadTaskList',
  data() {
    return {
      tasksLoading: false,
      form: loadDownloadForm(),
      tasks: [],
      fileRows: [],
      selectedRows: [],
      selectedTaskIds: [],
      page: 1,
      pageSize: 10,
      filters: {
        fileName: '',
        channel: '',
        messageId: '',
        uploadStatus: 'all'
      },
      logVisible: false,
      logText: ''
    }
  },
  computed: {
    filteredRows() {
      const fileName = this.filters.fileName.trim().toLowerCase()
      const channel = this.filters.channel.trim().toLowerCase()
      const messageId = this.filters.messageId.trim()
      return this.fileRows.filter(row => {
        if (fileName) {
          const name = String(row.file_name || row.name || '').toLowerCase()
          if (name.indexOf(fileName) < 0) return false
        }
        if (channel) {
          const rowChannel = String(row.channel || '').toLowerCase()
          if (rowChannel.indexOf(channel) < 0) return false
        }
        if (messageId) {
          const rowMessageId = String(row.message_id || '')
          if (rowMessageId.indexOf(messageId) < 0) return false
        }
        if (this.filters.uploadStatus !== 'all') {
          const status = row.upload_status || 'none'
          if (this.filters.uploadStatus === 'none') return !row.upload_status
          return status === this.filters.uploadStatus
        }
        return true
      })
    },
    pagedRows() {
      const start = (this.page - 1) * this.pageSize
      return this.filteredRows.slice(start, start + this.pageSize)
    }
  },
  created() {
    this.loadTasks()
  },
  methods: {
    formatBytes,
    formatSpeed,
    formatDateTime,
    async loadTasks() {
      if (this.tasksLoading) return
      this.tasksLoading = true
      try {
        this.tasks = await this.fetchAllTasks()
        await this.loadTaskFiles()
        this.ensureValidPage()
      } catch (error) {
        this.$message.error(error.message || '读取任务失败')
      } finally {
        this.tasksLoading = false
      }
    },
    async fetchAllTasks() {
      const limit = 200
      let offset = 0
      let total = 0
      const items = []
      do {
        const data = await getTasks({
          limit,
          offset,
          sort_by: 'updated_at',
          sort_order: 'desc'
        })
        const chunk = data.items || []
        total = Number(data.total || chunk.length)
        items.push(...chunk)
        offset += limit
        if (!chunk.length) break
      } while (offset < total)
      return items
    },
    async loadTaskFiles() {
      const result = []
      for (const task of this.tasks) {
        try {
          const data = await getTaskFiles(task.id)
          const files = data.items && data.items.length ? data.items : [this.taskFallbackFile(task)]
          files.forEach(file => {
            result.push({
              ...file,
              task_id: task.id,
              channel: task.channel,
              output_dir: task.output_dir || this.form.outputDir,
              task_status: task.status,
              created_at: task.created_at,
              error: task.error
            })
          })
        } catch (error) {
          result.push(this.taskFallbackFile(task))
        }
      }
      this.fileRows = result
    },
    taskFallbackFile(task) {
      return {
        task_id: task.id,
        channel: task.channel,
        output_dir: task.output_dir || this.form.outputDir,
        message_id: this.messageIds(task).join(',') || '--',
        file_name: task.error || '--',
        description: task.error || '',
        upload_status: task.status === 'uploading' ? 'uploading' : '',
        task_status: task.status,
        created_at: task.created_at,
        error: task.error
      }
    },
    messageIds(row) {
      try {
        const ids = JSON.parse(row.message_ids || '[]')
        return Array.isArray(ids) ? ids : []
      } catch (error) {
        return []
      }
    },
    mainImage(row) {
      return row.preview_image || row.cover_image || (row.cover_files && row.cover_files[0]) || (row.extra_images && row.extra_images[0])
    },
    imageUrl(row, path) {
      const outputDir = row.output_dir || this.form.outputDir
      const token = this.form.token ? `&token=${encodeURIComponent(this.form.token)}` : ''
      return `${getRuntimeBaseUrl()}/preview/image?output_dir=${encodeURIComponent(outputDir)}&path=${encodeURIComponent(path)}${token}`
    },
    titleText(row) {
      return row.title || row.file_name || row.name || '未命名资源'
    },
    descText(row) {
      return row.caption || row.description || row.error || '--'
    },
    searchTasks() {
      this.page = 1
      this.ensureValidPage()
    },
    resetFilters() {
      this.filters = {
        fileName: '',
        channel: '',
        messageId: '',
        uploadStatus: 'all'
      }
      this.page = 1
      this.ensureValidPage()
    },
    refreshTasks() {
      this.loadTasks()
    },
    ensureValidPage() {
      const maxPage = Math.max(1, Math.ceil(this.filteredRows.length / this.pageSize))
      if (this.page > maxPage) this.page = maxPage
    },
    handlePageChange(page) {
      this.page = page
    },
    handleSizeChange(size) {
      this.pageSize = size
      this.page = 1
    },
    handleTaskSelection(rows) {
      this.selectedRows = rows
      this.selectedTaskIds = Array.from(new Set(rows.map(item => item.task_id)))
    },
    uploadStatusText(status) {
      const map = {
        uploading: '上传中',
        done: '已上传',
        failed: '上传失败'
      }
      return map[status] || '未上传'
    },
    uploadTag(status) {
      if (status === 'done') return 'success'
      if (status === 'uploading') return 'warning'
      if (status === 'failed') return 'danger'
      return 'info'
    },
    messageIdValue(row) {
      const value = row.message_id
      if (value === null || value === undefined) return null
      const text = String(value).trim()
      if (!/^\d+$/.test(text)) return null
      return Number(text)
    },
    canRetry(row) {
      return this.messageIdValue(row) !== null && Boolean(row.channel) && row.upload_status !== 'done'
    },
    canReupload(row) {
      return this.messageIdValue(row) !== null && Boolean(row.channel)
    },
    retryableRows(rows) {
      return rows.filter(row => this.canRetry(row))
    },
    reuploadableRows(rows) {
      return rows.filter(row => this.canReupload(row))
    },
    async createRetryTasks(rows) {
      const grouped = new Map()
      this.retryableRows(rows).forEach(row => {
        const messageId = this.messageIdValue(row)
        if (messageId === null) return
        if (!grouped.has(row.channel)) grouped.set(row.channel, new Set())
        grouped.get(row.channel).add(messageId)
      })
      if (!grouped.size) {
        this.$message.warning('所选数据中没有可重试的消息 ID')
        return
      }
      const requests = []
      grouped.forEach((ids, channel) => {
        requests.push(createTask({
          channel,
          api_id: this.form.apiId,
          api_hash: this.form.apiHash,
          upload_account: this.form.uploadAccount,
          upload_password: this.form.uploadPassword,
          upload_api_token: this.form.uploadApiToken,
          message_ids: Array.from(ids),
          output_dir: this.form.outputDir,
          auto_upload: true,
          upload_meta: this.form.uploadMeta === '' ? undefined : this.form.uploadMeta === 'true',
          video_type_threshold_seconds: Number(this.form.shortThreshold || 0)
        }))
      })
      await Promise.all(requests)
    },
    async createReuploadTasks(rows) {
      const grouped = new Map()
      this.reuploadableRows(rows).forEach(row => {
        const messageId = this.messageIdValue(row)
        if (messageId === null) return
        if (!grouped.has(row.channel)) grouped.set(row.channel, new Set())
        grouped.get(row.channel).add(messageId)
      })
      if (!grouped.size) {
        this.$message.warning('所选数据中没有可重新上传的消息 ID')
        return
      }
      const requests = []
      grouped.forEach((ids, channel) => {
        requests.push(createTask({
          channel,
          api_id: this.form.apiId,
          api_hash: this.form.apiHash,
          upload_account: this.form.uploadAccount,
          upload_password: this.form.uploadPassword,
          upload_api_token: this.form.uploadApiToken,
          message_ids: Array.from(ids),
          output_dir: this.form.outputDir,
          auto_upload: true,
          upload_meta: this.form.uploadMeta === '' ? undefined : this.form.uploadMeta === 'true',
          video_type_threshold_seconds: Number(this.form.shortThreshold || 0),
          force_upload: true
        }))
      })
      await Promise.all(requests)
    },
    async openLog(row) {
      const data = await getTaskLog(row.task_id, { limit: 500, offset: 0 })
      this.logText = (data.items || []).map(item => item.message).join('\n')
      this.logVisible = true
    },
    async retry(row) {
      await this.createRetryTasks([row])
      this.$message.success('已按消息 ID 重新创建上传任务')
      this.loadTasks()
    },
    async reupload(row) {
      await this.$confirm(`确认重新上传消息 ${row.message_id}？`, '提示', { type: 'warning' })
      await this.createReuploadTasks([row])
      this.$message.success('已创建重新上传任务')
      this.loadTasks()
    },
    async retrySelectedTasks() {
      const rows = this.retryableRows(this.selectedRows)
      if (!rows.length) {
        this.$message.warning('所选数据中没有可重试的消息 ID')
        return
      }
      await this.$confirm(`确认按消息 ID 重试 ${rows.length} 条数据？`, '提示', { type: 'warning' })
      await this.createRetryTasks(rows)
      this.selectedRows = []
      this.selectedTaskIds = []
      this.$message.success('已批量创建上传任务')
      this.loadTasks()
    },
    async deleteOneTask(row) {
      await this.$confirm(`确认删除任务 ${row.task_id}？`, '提示', { type: 'warning' })
      await deleteTask(row.task_id)
      this.$message.success('已删除')
      this.loadTasks()
    },
    async deleteSelectedTasks() {
      await this.$confirm(`确认删除 ${this.selectedTaskIds.length} 个任务？`, '提示', { type: 'warning' })
      await Promise.all(this.selectedTaskIds.map(id => deleteTask(id)))
      this.selectedTaskIds = []
      this.selectedRows = []
      this.$message.success('已删除所选任务')
      this.loadTasks()
    }
  }
}
</script>

<style lang="scss" scoped>
.task-list-page {
  .page-title {
    font-size: 16px;
    font-weight: 700;
  }

  .filter-row {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 12px;
    margin-bottom: 70px;
  }

  .filter-item {
    display: inline-flex;
    align-items: center;
    gap: 10px;
  }

  .filter-label {
    font-weight: 600;
    color: $textRegular;
    white-space: nowrap;
  }

  .filter-item .el-input,
  .filter-item .el-select {
    width: 168px;
  }

  .task-table {
    margin-top: 8px;
  }

  .media-cell {
    width: 210px;
    margin: 0 auto;
  }

  .cover-wrap {
    position: relative;
    width: 160px;
    height: 98px;
    margin: 0 auto;
  }

  .cover {
    width: 160px;
    height: 98px;
    border-radius: 4px;
    background: #f3f4f6;
  }

  .empty-cover {
    display: flex;
    align-items: center;
    justify-content: center;
    color: $textSecondary;
  }

  .play-mark {
    position: absolute;
    left: 50%;
    top: 50%;
    transform: translate(-50%, -50%);
    width: 26px;
    height: 26px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    background: rgba(255, 255, 255, 0.9);
    color: #606266;
    pointer-events: none;
  }

  .resource-title {
    margin-bottom: 12px;
    font-weight: 700;
    color: $textRegular;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .resource-desc {
    color: $textSecondary;
    line-height: 1.6;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .pagination-row {
    margin-top: 16px;
    display: flex;
    justify-content: flex-end;
  }

  .log-box {
    margin: 0;
    max-height: 60vh;
    overflow: auto;
    padding: 12px;
    background: #111827;
    color: #d1d5db;
    border-radius: 4px;
    font-size: 12px;
    line-height: 1.6;
  }
}
</style>
