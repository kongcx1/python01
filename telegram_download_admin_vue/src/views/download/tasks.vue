<template>
  <div class="tasks-page">
    <el-card class="page-card" shadow="never">
      <div slot="header" class="toolbar">
        <div>
          <div class="card-title">下载列表</div>
          <div class="muted small-text">共 {{ taskTotal }} 条任务</div>
        </div>
        <div class="header-actions">
          <el-select v-model="taskStatus" size="small" clearable placeholder="全部状态" class="status-filter" @change="handleTaskStatusChange">
            <el-option label="待处理" value="pending" />
            <el-option label="下载中" value="downloading" />
            <el-option label="运行中" value="running" />
            <el-option label="上传中" value="uploading" />
            <el-option label="已完成" value="done" />
            <el-option label="失败" value="failed" />
            <el-option label="已取消" value="cancelled" />
            <el-option label="取消中" value="cancel_requested" />
          </el-select>
          <router-link to="/download/preview">
            <el-button size="small" icon="el-icon-search">任务管理</el-button>
          </router-link>
          <el-button size="small" icon="el-icon-refresh" :loading="tasksLoading" @click="loadTasks">刷新</el-button>
          <el-button size="small" type="danger" plain icon="el-icon-delete-solid" :loading="cleaningLocalVideos" @click="cleanupLocalVideos">清理本地视频</el-button>
          <el-button size="small" plain icon="el-icon-close" :loading="batchCancelling" :disabled="!cancelableSelectedTasks().length" @click="cancelSelectedTasks">批量取消</el-button>
          <el-button size="small" type="warning" plain icon="el-icon-refresh-right" :loading="batchRetrying" :disabled="!retryableSelectedTasks().length" @click="retrySelectedTasks">批量重试</el-button>
          <el-button size="small" type="danger" plain icon="el-icon-delete" :disabled="!selectedTaskIds.length" @click="deleteSelectedTasks">删除所选</el-button>
        </div>
      </div>

      <el-table :data="tasks" border height="620" size="small" @selection-change="handleTaskSelection">
        <el-table-column type="selection" width="42" />
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="channel" label="频道" min-width="130" />
        <el-table-column label="进度" min-width="190">
          <template slot-scope="{ row }">
            <div>{{ progressText(row) }}</div>
            <div class="muted">{{ bytesText(row) }} · {{ speedText(row) }}</div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="130">
          <template slot-scope="{ row }">
            <el-tag :type="statusTag(row.status)" size="mini">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="更新时间" width="170">
          <template slot-scope="{ row }">{{ formatDateTime(row.updated_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="370" fixed="right">
          <template slot-scope="{ row }">
            <el-button size="mini" icon="el-icon-tickets" @click="openDetail(row)">详情</el-button>
            <el-button size="mini" icon="el-icon-document" @click="openLog(row)">日志</el-button>
            <el-button size="mini" icon="el-icon-close" :loading="cancelingIds.indexOf(row.id) >= 0" :disabled="!canCancel(row)" @click="cancel(row)">取消</el-button>
            <el-button size="mini" icon="el-icon-upload2" :loading="uploadingIds.indexOf(row.id) >= 0" :disabled="!canUpload(row)" @click="upload(row)">上传</el-button>
            <el-button size="mini" icon="el-icon-refresh-right" :disabled="!canRetry(row)" @click="retry(row)">重试</el-button>
            <el-button size="mini" type="danger" plain icon="el-icon-delete" :disabled="row.status === 'running'" @click="deleteOneTask(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div class="pagination-bar">
        <el-pagination
          background
          :current-page="taskPage"
          :page-size="taskPageSize"
          :page-sizes="taskPageSizes"
          :total="taskTotal"
          layout="total, sizes, prev, pager, next, jumper"
          @size-change="handleTaskPageSizeChange"
          @current-change="handleTaskPageChange"
        />
      </div>
    </el-card>

    <el-dialog title="任务日志" :visible.sync="logVisible" width="760px">
      <pre class="log-box">{{ logText }}</pre>
    </el-dialog>

    <el-dialog :title="detailTitle" :visible.sync="detailVisible" width="900px">
      <el-table :data="detailFiles" border size="small" max-height="520">
        <el-table-column prop="message_id" label="消息 ID" width="100" />
        <el-table-column label="文件名" min-width="260">
          <template slot-scope="{ row }">{{ row.file_name || row.name || '--' }}</template>
        </el-table-column>
        <el-table-column label="上传状态" width="120">
          <template slot-scope="{ row }">
            <el-tag :type="uploadTag(row.upload_status)" size="mini">{{ row.upload_status || '未上传' }}</el-tag>
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
      </el-table>
    </el-dialog>
  </div>
</template>

<script>
import { getTasks, getTaskLog, getTaskFiles, cancelTask, retryTask, uploadTask, deleteTask, cleanupLocalVideos } from '@/api/download'
import { formatBytes, formatSpeed, formatDateTime, parseProgress } from '@/utils/format'

const TaskStateKey = 'telegram_admin_task_state'

export default {
  name: 'DownloadTasks',
  data() {
    return {
      tasksLoading: false,
      tasks: [],
      taskTotal: 0,
      taskPage: 1,
      taskPageSize: 10,
      taskPageSizes: [10, 20, 50, 100],
      taskStatus: '',
      selectedTaskIds: [],
      logVisible: false,
      logText: '',
      detailVisible: false,
      detailTitle: '任务详情',
      detailFiles: [],
      cancelingIds: [],
      uploadingIds: [],
      cleaningLocalVideos: false,
      batchCancelling: false,
      batchRetrying: false
    }
  },
  created() {
    this.restoreTaskState()
    this.loadTasks()
  },
  methods: {
    formatBytes,
    formatSpeed,
    formatDateTime,
    restoreTaskState() {
      const raw = localStorage.getItem(TaskStateKey)
      if (!raw) return
      try {
        const state = JSON.parse(raw)
        this.tasks = state.tasks || []
        this.taskTotal = Number(state.taskTotal || this.tasks.length)
        this.taskPage = Math.max(1, Number(state.taskPage || 1))
        this.taskPageSize = Number(state.taskPageSize || 10)
        this.taskStatus = state.taskStatus || ''
      } catch (error) {
        localStorage.removeItem(TaskStateKey)
      }
    },
    saveTaskState() {
      localStorage.setItem(
        TaskStateKey,
        JSON.stringify({
          tasks: this.tasks,
          taskTotal: this.taskTotal,
          taskPage: this.taskPage,
          taskPageSize: this.taskPageSize,
          taskStatus: this.taskStatus
        })
      )
    },
    async loadTasks() {
      if (this.tasksLoading) return
      this.tasksLoading = true
      try {
        const limit = this.taskPageSize
        let offset = (this.taskPage - 1) * limit
        const params = {
          limit,
          offset,
          sort_by: 'updated_at',
          sort_order: 'desc'
        }
        if (this.taskStatus) params.status = this.taskStatus
        let data = await getTasks(params)
        const total = Number(data.total || 0)
        if (!(data.items || []).length && total > 0 && this.taskPage > 1) {
          this.taskPage = Math.max(1, Math.ceil(total / this.taskPageSize))
          offset = (this.taskPage - 1) * limit
          params.offset = offset
          data = await getTasks(params)
        }
        this.tasks = data.items || []
        this.taskTotal = Number(data.total || this.tasks.length)
        this.selectedTaskIds = []
        this.saveTaskState()
      } catch (error) {
        this.$message.error(error.message || '读取任务失败')
      } finally {
        this.tasksLoading = false
      }
    },
    handleTaskSelection(rows) {
      this.selectedTaskIds = rows.map(item => item.id)
    },
    handleTaskPageChange(page) {
      this.taskPage = page
      this.loadTasks()
    },
    handleTaskPageSizeChange(size) {
      this.taskPageSize = size
      this.taskPage = 1
      this.loadTasks()
    },
    handleTaskStatusChange() {
      this.taskPage = 1
      this.loadTasks()
    },
    progress(row) {
      return parseProgress(row.progress_json)
    },
    progressText(row) {
      const data = this.progress(row)
      const stage = data.stage || 'download'
      const count = stage === 'upload' ? data.upload_count : data.download_count
      if (count && Number.isFinite(count.done) && Number.isFinite(count.total)) {
        return `${stage === 'upload' ? '上传' : '下载'} ${count.done}/${count.total}`
      }
      return data.status || row.status || '--'
    },
    bytesText(row) {
      const data = this.progress(row)
      const stage = data.stage || 'download'
      const item = stage === 'upload' ? (data.upload_video || data.upload || {}) : (data.download || {})
      const done = item.task_bytes_downloaded == null ? item.sent : item.task_bytes_downloaded
      const total = item.task_bytes_total == null ? item.total : item.task_bytes_total
      return `${formatBytes(done)}/${formatBytes(total)}`
    },
    speedText(row) {
      const data = this.progress(row)
      const stage = data.stage || 'download'
      const item = stage === 'upload' ? (data.upload_video || data.upload || {}) : (data.download || {})
      return formatSpeed(item.speed_bps)
    },
    statusTag(status) {
      if (status === 'done') return 'success'
      if (status === 'failed') return 'danger'
      if (status === 'downloading') return 'warning'
      if (status === 'running') return 'warning'
      if (status === 'cancelled') return 'info'
      if (status === 'uploading') return 'warning'
      return ''
    },
    uploadTag(status) {
      if (status === 'done') return 'success'
      if (status === 'uploading') return 'warning'
      if (status === 'failed') return 'danger'
      return 'info'
    },
    canCancel(row) {
      return ['pending', 'downloading', 'running', 'cancel_requested'].indexOf(row.status) >= 0
    },
    canRetry(row) {
      return ['failed', 'cancelled'].indexOf(row.status) >= 0
    },
    cancelableSelectedTasks() {
      return this.tasks.filter(row => this.selectedTaskIds.indexOf(row.id) >= 0 && this.canCancel(row))
    },
    retryableSelectedTasks() {
      return this.tasks.filter(row => this.selectedTaskIds.indexOf(row.id) >= 0 && this.canRetry(row))
    },
    canUpload(row) {
      return ['done', 'failed', 'cancelled'].indexOf(row.status) >= 0
    },
    async openLog(row) {
      const data = await getTaskLog(row.id, { limit: 500, offset: 0 })
      this.logText = (data.items || []).map(item => item.message).join('\n')
      this.logVisible = true
    },
    async openDetail(row) {
      this.detailTitle = `任务 ${row.id} · ${row.channel}`
      const data = await getTaskFiles(row.id)
      this.detailFiles = data.items || []
      this.detailVisible = true
    },
    async cancel(row) {
      this.cancelingIds.push(row.id)
      try {
        const data = await cancelTask(row.id)
        const status = data.status || 'cancel_requested'
        this.tasks = this.tasks.map(item => item.id === row.id ? { ...item, status } : item)
        this.$message.success(status === 'cancelled' ? '任务已取消' : '已请求取消')
        this.saveTaskState()
        await this.loadTasks()
      } finally {
        this.cancelingIds = this.cancelingIds.filter(id => id !== row.id)
      }
    },
    async retry(row) {
      await retryTask(row.id)
      this.$message.success('已重新排队')
      this.loadTasks()
    },
    async cancelSelectedTasks() {
      const rows = this.cancelableSelectedTasks()
      if (!rows.length) return
      await this.$confirm(`确认取消 ${rows.length} 个待处理或运行中的任务？`, '批量取消', { type: 'warning' })
      this.batchCancelling = true
      try {
        const results = await Promise.allSettled(rows.map(row => cancelTask(row.id)))
        const successCount = results.filter(result => result.status === 'fulfilled').length
        const failedCount = results.length - successCount
        if (failedCount) {
          this.$message.warning(`已提交 ${successCount} 个任务取消，${failedCount} 个任务取消失败`)
        } else {
          this.$message.success(`已提交 ${successCount} 个任务取消`)
        }
        this.selectedTaskIds = []
        await this.loadTasks()
      } finally {
        this.batchCancelling = false
      }
    },
    async retrySelectedTasks() {
      const rows = this.retryableSelectedTasks()
      if (!rows.length) return
      await this.$confirm(`确认重试 ${rows.length} 个失败或已取消任务？`, '批量重试', { type: 'warning' })
      this.batchRetrying = true
      try {
        const results = await Promise.allSettled(rows.map(row => retryTask(row.id)))
        const successCount = results.filter(result => result.status === 'fulfilled').length
        const failedCount = results.length - successCount
        if (failedCount) {
          this.$message.warning(`已提交 ${successCount} 个任务，${failedCount} 个任务重试失败`)
        } else {
          this.$message.success(`已提交 ${successCount} 个任务重试`)
        }
        this.selectedTaskIds = []
        await this.loadTasks()
      } finally {
        this.batchRetrying = false
      }
    },
    async upload(row) {
      this.uploadingIds.push(row.id)
      try {
        const data = await uploadTask(row.id)
        const status = data.status || 'uploading'
        this.tasks = this.tasks.map(item => item.id === row.id ? { ...item, status } : item)
        this.$message.success('已开始上传')
        this.saveTaskState()
        await this.loadTasks()
      } finally {
        this.uploadingIds = this.uploadingIds.filter(id => id !== row.id)
      }
    },
    async cleanupLocalVideos() {
      await this.$confirm('确认删除下载目录下所有本地视频文件？任务记录、日志、封面和预览不会删除，此操作不可恢复。', '清理本地视频', { type: 'warning' })
      this.cleaningLocalVideos = true
      try {
        const result = await cleanupLocalVideos()
        const deletedFiles = Number(result.deleted_files || 0)
        const deletedBytes = formatBytes(Number(result.deleted_bytes || 0))
        if ((result.errors || []).length) {
          this.$message.warning(`已删除 ${deletedFiles} 个视频，释放 ${deletedBytes}；部分文件删除失败`)
        } else {
          this.$message.success(`已删除 ${deletedFiles} 个本地视频，释放 ${deletedBytes}`)
        }
      } finally {
        this.cleaningLocalVideos = false
      }
    },
    async deleteOneTask(row) {
      await this.$confirm(`确认删除任务 ${row.id}？`, '提示', { type: 'warning' })
      await deleteTask(row.id)
      this.$message.success('已删除')
      this.loadTasks()
    },
    async deleteSelectedTasks() {
      await this.$confirm(`确认删除 ${this.selectedTaskIds.length} 个任务？`, '提示', { type: 'warning' })
      await Promise.all(this.selectedTaskIds.map(id => deleteTask(id)))
      this.$message.success('已删除所选任务')
      this.selectedTaskIds = []
      this.loadTasks()
    }
  }
}
</script>

<style lang="scss" scoped>
.tasks-page {
  .card-title {
    font-weight: 700;
  }

  .small-text {
    margin-top: 4px;
    font-size: 12px;
  }

  .header-actions {
    display: inline-flex;
    align-items: center;
    gap: 8px;
  }

  .status-filter {
    width: 118px;
  }

  .pagination-bar {
    display: flex;
    justify-content: flex-end;
    padding-top: 16px;
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
