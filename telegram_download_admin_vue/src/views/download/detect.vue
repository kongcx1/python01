<template>
  <div class="detect-page">
    <el-card class="page-card" shadow="never">
      <div slot="header" class="toolbar">
        <div>
          <div class="card-title">检测结果</div>
          <div class="muted small-text">{{ form.channel }} · 每页 {{ form.previewLimit }} 条 · 已选择 {{ selectedIds.length }} 个</div>
        </div>
        <div class="header-actions">
          <router-link to="/download/config">
            <el-button size="small" icon="el-icon-setting">任务配置</el-button>
          </router-link>
          <el-button size="small" icon="el-icon-search" :loading="previewLoading" @click="refreshCurrentPage">检测视频</el-button>
          <el-button size="small" icon="el-icon-finished" @click="selectCurrentPage">全选当前页</el-button>
          <el-button size="small" icon="el-icon-delete" @click="clearSelection">重置选择</el-button>
          <el-button size="small" type="primary" icon="el-icon-download" :loading="creatingTask" @click="submitTask">开始下载</el-button>
        </div>
      </div>

      <el-alert v-if="!ready" title="请先在任务配置页填写 API ID、API Hash、频道和输出目录。" type="warning" :closable="false" show-icon />

      <el-table ref="previewTable" :data="previewItems" border height="620" size="small" @selection-change="handlePreviewSelection">
        <el-table-column type="selection" width="42" />
        <el-table-column label="封面" width="96">
          <template slot-scope="{ row }">
            <el-image v-if="row.cover_image || row.preview_image" class="thumb" :src="previewImageUrl(row.cover_image || row.preview_image)" fit="cover" @click="openMedia(row)" />
            <div v-else class="empty-thumb">无</div>
          </template>
        </el-table-column>
        <el-table-column prop="message_id" label="消息 ID" width="96" />
        <el-table-column label="标题/说明" min-width="260">
          <template slot-scope="{ row }">
            <div class="title-cell">{{ row.file_name || row.title || '未命名视频' }}</div>
            <div class="muted clamp">{{ row.caption || row.description }}</div>
          </template>
        </el-table-column>
        <el-table-column label="时长" width="80">
          <template slot-scope="{ row }">{{ row.duration || '--' }}s</template>
        </el-table-column>
        <el-table-column label="大小" width="100">
          <template slot-scope="{ row }">{{ formatBytes(row.file_size) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="92">
          <template slot-scope="{ row }">
            <el-button size="mini" icon="el-icon-video-play" @click="openMedia(row)">预览</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination-row">
        <el-button size="small" :disabled="previewLoading || previewPage <= 1" @click="loadPreview(previewPage - 1)">上一页</el-button>
        <span class="muted">第 {{ previewPage }} 页</span>
        <el-button size="small" :disabled="previewLoading || !previewHasMore" @click="loadPreview(previewPage + 1)">下一页</el-button>
      </div>
    </el-card>

    <el-dialog title="媒体预览" :visible.sync="mediaVisible" width="860px" top="5vh">
      <video v-if="activeMedia" class="media-preview" :src="activeMedia.url" controls autoplay />
    </el-dialog>
  </div>
</template>

<script>
import { previewVideos, createTask } from '@/api/download'
import { getRuntimeBaseUrl } from '@/utils/request'
import { formatBytes } from '@/utils/format'
import { loadDownloadForm, hasLoginFields } from '@/utils/downloadForm'

const PreviewStateKey = 'telegram_admin_preview_state'

export default {
  name: 'DownloadDetect',
  data() {
    return {
      form: loadDownloadForm(),
      previewLoading: false,
      creatingTask: false,
      previewPage: 1,
      previewHasMore: false,
      previewCursors: { 1: null },
      previewItems: [],
      selectedIds: [],
      mediaVisible: false,
      activeMedia: null
    }
  },
  computed: {
    ready() {
      return hasLoginFields(this.form) && Boolean(this.form.channel)
    }
  },
  created() {
    this.restorePreviewState()
  },
  mounted() {
    this.syncSelectedRows()
  },
  methods: {
    formatBytes,
    restorePreviewState() {
      const raw = localStorage.getItem(PreviewStateKey)
      if (!raw) return
      try {
        const state = JSON.parse(raw)
        if (state.channel !== this.form.channel || state.outputDir !== this.form.outputDir) return
        this.previewPage = Number(state.previewPage || 1)
        this.previewHasMore = Boolean(state.previewHasMore)
        this.previewCursors = state.previewCursors || { 1: null }
        this.previewItems = state.previewItems || []
        this.selectedIds = state.selectedIds || []
      } catch (error) {
        localStorage.removeItem(PreviewStateKey)
      }
    },
    savePreviewState() {
      localStorage.setItem(
        PreviewStateKey,
        JSON.stringify({
          channel: this.form.channel,
          outputDir: this.form.outputDir,
          previewPage: this.previewPage,
          previewHasMore: this.previewHasMore,
          previewCursors: this.previewCursors,
          previewItems: this.previewItems,
          selectedIds: this.selectedIds
        })
      )
    },
    syncSelectedRows() {
      this.$nextTick(() => {
        if (!this.$refs.previewTable) return
        const selectedSet = new Set(this.selectedIds)
        this.$refs.previewTable.clearSelection()
        this.previewItems.forEach(item => {
          if (selectedSet.has(item.message_id)) {
            this.$refs.previewTable.toggleRowSelection(item, true)
          }
        })
      })
    },
    boolValue(value) {
      if (value === '') return undefined
      return value === 'true'
    },
    async loadPreview(page) {
      if (this.previewLoading) return
      if (!this.ready) {
        this.$message.warning('请先完成任务配置')
        return
      }
      this.previewLoading = true
      try {
        const data = await previewVideos({
          api_id: this.form.apiId,
          api_hash: this.form.apiHash,
          output_dir: this.form.outputDir,
          channel: this.form.channel,
          limit: Number(this.form.previewLimit || 30),
          offset: 0,
          offset_id: this.previewCursors[page] || null
        })
        this.previewItems = data.items || []
        this.previewPage = page
        this.previewHasMore = Boolean(data.has_more)
        if (data.next_offset_id) this.$set(this.previewCursors, page + 1, data.next_offset_id)
        this.savePreviewState()
        this.syncSelectedRows()
        this.$message.success(`检测完成，本页 ${this.previewItems.length} 条${this.previewHasMore ? '，还有下一页' : ''}`)
      } catch (error) {
        this.$message.error(error.message || '检测视频失败')
      } finally {
        this.previewLoading = false
      }
    },
    refreshCurrentPage() {
      this.loadPreview(this.previewPage || 1)
    },
    handlePreviewSelection(rows) {
      this.selectedIds = rows.map(item => item.message_id)
      this.savePreviewState()
    },
    selectCurrentPage() {
      this.selectedIds = this.previewItems.map(item => item.message_id)
      this.$nextTick(() => {
        if (!this.$refs.previewTable) return
        this.$refs.previewTable.clearSelection()
        this.previewItems.forEach(item => this.$refs.previewTable.toggleRowSelection(item, true))
      })
      this.savePreviewState()
    },
    clearSelection() {
      this.selectedIds = []
      if (this.$refs.previewTable) this.$refs.previewTable.clearSelection()
      this.savePreviewState()
    },
    async submitTask() {
      if (!this.selectedIds.length) {
        this.$message.warning('请先选择视频')
        return
      }
      this.creatingTask = true
      try {
        await createTask({
          channel: this.form.channel,
          api_id: this.form.apiId,
          api_hash: this.form.apiHash,
          upload_account: this.form.uploadAccount,
          upload_password: this.form.uploadPassword,
          upload_api_token: this.form.uploadApiToken,
          message_ids: this.selectedIds,
          output_dir: this.form.outputDir,
          auto_upload: true,
          upload_meta: this.boolValue(this.form.uploadMeta),
          video_type_threshold_seconds: Number(this.form.shortThreshold || 0)
        })
        this.$message.success('下载任务已创建')
        this.$router.push('/download/tasks')
      } finally {
        this.creatingTask = false
      }
    },
    previewImageUrl(path) {
      return `${getRuntimeBaseUrl()}/preview/image?output_dir=${encodeURIComponent(this.form.outputDir)}&path=${encodeURIComponent(path)}`
    },
    streamUrl(row) {
      const token = this.form.token ? `&token=${encodeURIComponent(this.form.token)}` : ''
      return `${getRuntimeBaseUrl()}/preview/stream?api_id=${encodeURIComponent(this.form.apiId)}&api_hash=${encodeURIComponent(this.form.apiHash)}&output_dir=${encodeURIComponent(this.form.outputDir)}&channel=${encodeURIComponent(this.form.channel)}&message_id=${encodeURIComponent(row.message_id)}${token}`
    },
    openMedia(row) {
      this.activeMedia = { url: this.streamUrl(row) }
      this.mediaVisible = true
    }
  }
}
</script>

<style lang="scss" scoped>
.detect-page {
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

  .thumb,
  .empty-thumb {
    width: 64px;
    height: 42px;
    border-radius: 4px;
    cursor: pointer;
  }

  .empty-thumb {
    display: flex;
    align-items: center;
    justify-content: center;
    background: #f3f4f6;
    color: $textSecondary;
  }

  .title-cell {
    font-weight: 600;
  }

  .clamp {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .pagination-row {
    margin-top: 12px;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 12px;
  }
}
</style>
