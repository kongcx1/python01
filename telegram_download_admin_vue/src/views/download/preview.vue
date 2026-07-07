<template>
  <div class="task-manage-page">
    <el-card class="page-card" shadow="never">
      <div slot="header" class="page-title">任务管理</div>

      <div class="filter-row">
        <div class="filter-item">
          <span class="filter-label">关键词</span>
          <el-input v-model="filters.keyword" size="small" placeholder="输入关键词" clearable />
        </div>
        <div class="filter-item">
          <span class="filter-label">类型</span>
          <el-select v-model="filters.type" size="small" placeholder="全部">
            <el-option label="全部" value="all" />
            <el-option label="短视频" value="short" />
            <el-option label="长视频" value="long" />
          </el-select>
        </div>
        <el-button type="primary" icon="el-icon-search" :loading="previewLoading" @click="applySearch">搜索</el-button>
        <el-button icon="el-icon-refresh-left" @click="resetFilters">重置</el-button>
        <el-button type="primary" :loading="creatingTask" @click="submitTask">批量下载</el-button>
      </div>

      <div class="filter-row secondary">
        <div class="filter-item compact">
          <span class="filter-label">资源去重：</span>
          <el-select v-model="filters.dedupe" size="small">
            <el-option label="是" value="yes" />
            <el-option label="否" value="no" />
          </el-select>
        </div>
        <div class="filter-item">
          <span class="filter-label">频道：</span>
          <el-input v-model="form.channel" size="small" placeholder="输入关键词" @change="handleChannelChange" />
        </div>
        <div class="filter-item">
          <span class="filter-label">加载条数：</span>
          <el-input-number v-model="loadCount" size="small" :min="1" :max="50" controls-position="right" />
        </div>
        <el-button :loading="previewLoading" @click="loadData">加载数据</el-button>
      </div>

      <el-alert v-if="!ready" title="请先在任务配置页填写 API ID、API Hash、频道和输出目录。" type="warning" :closable="false" show-icon />

      <el-table
        ref="previewTable"
        class="resource-table"
        :data="visibleItems"
        border
        size="small"
        @selection-change="handlePreviewSelection"
      >
        <el-table-column type="selection" width="54" />
        <el-table-column label="预览" width="320">
          <template slot-scope="{ row }">
            <div class="media-cell">
              <button class="preview-tile" type="button" @click="openMedia(row)">
                <el-image
                  v-if="mainImage(row)"
                  class="preview-image"
                  :src="previewImageUrl(mainImage(row))"
                  fit="cover"
                  lazy
                  @error="handleImageError(row, mainImage(row))"
                >
                  <div slot="placeholder" class="preview-state">
                    <i class="el-icon-loading" />
                  </div>
                  <div slot="error" class="preview-state">
                    <i class="el-icon-picture-outline" />
                  </div>
                </el-image>
                <div v-else class="preview-state no-image">
                  <i class="el-icon-video-camera" />
                  <span>无封面</span>
                </div>
                <span class="play-mark" title="预览视频"><i class="el-icon-video-play" /></span>
                <span v-if="imageCount(row) > 1" class="image-count">{{ imageCount(row) }}</span>
              </button>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="名称/简介" min-width="260">
          <template slot-scope="{ row }">
            <div class="resource-title">{{ titleText(row) }}</div>
            <div class="resource-desc">{{ descText(row) }}</div>
          </template>
        </el-table-column>
        <el-table-column label="标签" min-width="180">
          <template slot-scope="{ row }">
            <span class="tag-text">{{ tagText(row) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="120">
          <template slot-scope="{ row }">{{ typeText(row) }}</template>
        </el-table-column>
        <el-table-column label="时长/大小" width="130">
          <template slot-scope="{ row }">
            <div>{{ durationText(row) }}</div>
            <div>{{ formatBytes(row.file_size) }}</div>
          </template>
        </el-table-column>
        <el-table-column label="发布时间" width="160">
          <template slot-scope="{ row }">{{ formatDateTime(row.date_utc) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="190" fixed="right">
          <template slot-scope="{ row }">
            <el-button size="mini" type="primary" :loading="creatingTask" @click="queueOne(row)">开始下载</el-button>
            <el-button size="mini" type="danger" @click="removeRow(row)">移除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination-row">
        <el-button size="small" :disabled="previewLoading || previewPage <= 1" @click="loadPreview(previewPage - 1)">上一页</el-button>
        <span class="muted">第 {{ previewPage }} 页</span>
        <el-button size="small" :disabled="previewLoading || !previewHasMore" @click="loadPreview(previewPage + 1)">下一页</el-button>
        <span class="muted">前往</span>
        <el-input-number v-model="jumpPage" size="small" :min="1" :max="9999" controls-position="right" class="jump-input" />
        <span class="muted">页</span>
        <el-button size="small" :loading="jumpingPage" :disabled="previewLoading || jumpingPage" @click="jumpToPage">跳转</el-button>
      </div>
    </el-card>

    <el-dialog title="视频预览" :visible.sync="mediaVisible" width="760px" @closed="activeMedia = null">
      <video v-if="activeMedia" class="media-preview" :src="activeMedia.url" controls autoplay />
    </el-dialog>
  </div>
</template>

<script>
import { previewVideos, createTask } from '@/api/download'
import { getRuntimeBaseUrl } from '@/utils/request'
import { formatBytes, formatDateTime } from '@/utils/format'
import { loadDownloadForm, saveDownloadForm, hasLoginFields } from '@/utils/downloadForm'

const PreviewStateKey = 'telegram_admin_preview_state'

export default {
  name: 'DownloadPreview',
  data() {
    return {
      form: loadDownloadForm(),
      filters: {
        keyword: '',
        type: 'all',
        dedupe: 'yes'
      },
      loadCount: 30,
      previewLoading: false,
      creatingTask: false,
      previewPage: 1,
      previewHasMore: false,
      previewCursors: { 1: null },
      previewItems: [],
      selectedIds: [],
      failedPreviewImages: {},
      jumpPage: 1,
      jumpingPage: false,
      mediaVisible: false,
      activeMedia: null
    }
  },
  computed: {
    ready() {
      return hasLoginFields(this.form) && Boolean(this.form.channel)
    },
    visibleItems() {
      let items = this.previewItems.slice()
      const keyword = this.filters.keyword.trim().toLowerCase()
      if (keyword) {
        items = items.filter(item => {
          const text = [
            item.file_name,
            item.title,
            item.caption,
            item.description,
            (item.tags || []).join(' ')
          ].join(' ').toLowerCase()
          return text.indexOf(keyword) >= 0
        })
      }
      if (this.filters.type !== 'all') {
        items = items.filter(item => this.itemType(item) === this.filters.type)
      }
      if (this.filters.dedupe === 'yes') {
        const seen = new Set()
        items = items.filter(item => {
          const key = item.message_id || item.file_name
          if (seen.has(key)) return false
          seen.add(key)
          return true
        })
      }
      return items
    }
  },
  created() {
    this.loadCount = Number(this.form.previewLimit || 30)
    this.restorePreviewState()
  },
  mounted() {
    this.syncSelectedRows()
  },
  methods: {
    formatBytes,
    formatDateTime,
    restorePreviewState() {
      const raw = localStorage.getItem(PreviewStateKey)
      if (!raw) return
      try {
        const state = JSON.parse(raw)
        if (state.channel !== this.form.channel || state.outputDir !== this.form.outputDir) return
        this.previewPage = Number(state.previewPage || 1)
        this.jumpPage = this.previewPage
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
    saveLocalForm() {
      saveDownloadForm(this.form)
    },
    resetPreviewPaging() {
      this.previewPage = 1
      this.jumpPage = 1
      this.previewHasMore = false
      this.previewCursors = { 1: null }
      this.previewItems = []
      this.selectedIds = []
      localStorage.removeItem(PreviewStateKey)
    },
    handleChannelChange() {
      this.resetPreviewPaging()
      this.saveLocalForm()
      this.syncSelectedRows()
    },
    syncSelectedRows() {
      this.$nextTick(() => {
        if (!this.$refs.previewTable) return
        const selectedSet = new Set(this.selectedIds)
        this.$refs.previewTable.clearSelection()
        this.visibleItems.forEach(item => {
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
          limit: Number(this.loadCount || this.form.previewLimit || 30),
          offset: 0,
          offset_id: this.previewCursors[page] || null
        })
        this.previewItems = data.items || []
        this.failedPreviewImages = {}
        this.previewPage = page
        this.jumpPage = page
        this.previewHasMore = Boolean(data.has_more)
        this.form.previewLimit = Number(this.loadCount || 30)
        if (data.next_offset_id) this.$set(this.previewCursors, page + 1, data.next_offset_id)
        this.saveLocalForm()
        this.savePreviewState()
        this.syncSelectedRows()
        if (data.partial_timeout) {
          this.$message.warning(data.detail || '预览加载超时，请降低加载条数后重试')
        } else {
          this.$message.success(`加载完成，本页 ${this.previewItems.length} 条${this.previewHasMore ? '，还有下一页' : ''}`)
        }
      } catch (error) {
        const detail = error.response && error.response.data && error.response.data.detail
        const isTimeout = error.code === 'ECONNABORTED' || (error.message || '').indexOf('timeout') >= 0
        this.$message.error(detail || (isTimeout ? '预览加载超时，请把加载条数调小后重试' : '加载视频失败'))
      } finally {
        this.previewLoading = false
      }
    },
    loadData() {
      this.loadPreview(this.previewPage || 1)
    },
    async jumpToPage() {
      const target = Number(this.jumpPage || 1)
      if (!Number.isFinite(target) || target < 1) {
        this.$message.warning('请输入正确的页码')
        return
      }
      if (target === this.previewPage) return
      if (target < this.previewPage || this.previewCursors[target]) {
        await this.loadPreview(target)
        return
      }
      this.jumpingPage = true
      try {
        let page = this.previewPage
        while (page < target) {
          if (!this.previewHasMore && !this.previewCursors[page + 1]) {
            this.$message.warning('没有更多数据')
            break
          }
          await this.loadPreview(page + 1)
          page = this.previewPage
        }
      } finally {
        this.jumpingPage = false
      }
    },
    applySearch() {
      this.syncSelectedRows()
    },
    resetFilters() {
      this.filters = {
        keyword: '',
        type: 'all',
        dedupe: 'yes'
      }
      this.syncSelectedRows()
    },
    handlePreviewSelection(rows) {
      this.selectedIds = rows.map(item => item.message_id)
      this.savePreviewState()
    },
    async queueOne(row) {
      await this.createQueue([row.message_id])
    },
    async submitTask() {
      if (!this.selectedIds.length) {
        this.$message.warning('请先选择视频')
        return
      }
      await this.createQueue(this.selectedIds)
    },
    async createQueue(messageIds) {
      this.creatingTask = true
      try {
        await createTask({
          channel: this.form.channel,
          api_id: this.form.apiId,
          api_hash: this.form.apiHash,
          upload_account: this.form.uploadAccount,
          upload_password: this.form.uploadPassword,
          upload_api_token: this.form.uploadApiToken,
          message_ids: messageIds,
          output_dir: this.form.outputDir,
          auto_upload: true,
          upload_meta: this.boolValue(this.form.uploadMeta),
          video_type_threshold_seconds: Number(this.form.shortThreshold || 0)
        })
        this.$message.success('下载任务已创建')
      } finally {
        this.creatingTask = false
      }
    },
    removeRow(row) {
      this.previewItems = this.previewItems.filter(item => item.message_id !== row.message_id)
      this.selectedIds = this.selectedIds.filter(id => id !== row.message_id)
      this.savePreviewState()
      this.syncSelectedRows()
    },
    mainImage(row) {
      const failed = this.failedPreviewImages[row.message_id] || []
      const images = this.imageCandidates(row)
      return images.find(item => failed.indexOf(item) < 0)
    },
    imageCandidates(row) {
      return [row.cover_image, row.preview_image].concat(row.extra_images || []).filter(Boolean)
    },
    imageCount(row) {
      return this.imageCandidates(row).length
    },
    handleImageError(row, path) {
      if (!path) return
      const key = row.message_id
      const failed = this.failedPreviewImages[key] || []
      if (failed.indexOf(path) >= 0) return
      this.$set(this.failedPreviewImages, key, failed.concat(path))
    },
    previewImageUrl(path) {
      const token = this.form.token ? `&token=${encodeURIComponent(this.form.token)}` : ''
      return `${getRuntimeBaseUrl()}/preview/image?output_dir=${encodeURIComponent(this.form.outputDir)}&path=${encodeURIComponent(path)}${token}`
    },
    streamUrl(row) {
      const token = this.form.token ? `&token=${encodeURIComponent(this.form.token)}` : ''
      return `${getRuntimeBaseUrl()}/preview/stream?api_id=${encodeURIComponent(this.form.apiId)}&api_hash=${encodeURIComponent(this.form.apiHash)}&output_dir=${encodeURIComponent(this.form.outputDir)}&channel=${encodeURIComponent(this.form.channel)}&message_id=${encodeURIComponent(row.message_id)}${token}`
    },
    openMedia(row) {
      this.activeMedia = { url: this.streamUrl(row) }
      this.mediaVisible = true
    },
    titleText(row) {
      return row.title || row.file_name || '未命名资源'
    },
    descText(row) {
      return row.caption || row.description || '--'
    },
    tagText(row) {
      const tags = row.tags || []
      if (!tags.length) return '--'
      return tags.map(item => String(item).startsWith('#') ? item : `#${item}`).join(' ')
    },
    itemType(row) {
      const threshold = Number(this.form.shortThreshold || 600)
      return Number(row.duration || 0) <= threshold ? 'short' : 'long'
    },
    typeText(row) {
      return this.itemType(row) === 'short' ? '短视频' : '长视频'
    },
    durationText(row) {
      const value = Number(row.duration)
      if (!Number.isFinite(value) || value <= 0) return '--'
      const hours = Math.floor(value / 3600)
      const minutes = Math.floor((value % 3600) / 60)
      const seconds = Math.floor(value % 60)
      return [hours, minutes, seconds].map(item => String(item).padStart(2, '0')).join(':')
    }
  }
}
</script>

<style lang="scss" scoped>
.task-manage-page {
  .page-title {
    font-size: 16px;
    font-weight: 700;
  }

  .filter-row {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 26px;
  }

  .filter-row.secondary {
    justify-content: flex-end;
    margin-bottom: 16px;
  }

  .filter-item {
    display: inline-flex;
    align-items: center;
    gap: 10px;
  }

  .filter-item .el-input,
  .filter-item .el-select,
  .filter-item .el-input-number {
    width: 168px;
  }

  .filter-item.compact .el-select {
    width: 80px;
  }

  .filter-label {
    font-weight: 600;
    color: $textRegular;
    white-space: nowrap;
  }

  .resource-table {
    margin-top: 8px;
  }

  .media-cell {
    width: 224px;
    margin: 0 auto;
  }

  .preview-tile {
    appearance: none;
    border: 0;
    padding: 0;
    overflow: hidden;
    position: relative;
    display: block;
    width: 224px;
    height: 126px;
    margin: 0 auto;
    cursor: pointer;
    border-radius: 4px;
    background: #f3f4f6;
    box-shadow: inset 0 0 0 1px #ebeef5;
  }

  .preview-tile:hover .play-mark {
    background: #409eff;
    color: #fff;
  }

  .preview-image,
  .preview-state {
    width: 224px;
    height: 126px;
  }

  .preview-state {
    display: flex;
    align-items: center;
    justify-content: center;
    flex-direction: column;
    gap: 8px;
    color: $textSecondary;
    background: linear-gradient(135deg, #f7f9fc, #eef2f7);
    font-size: 13px;
  }

  .preview-state i {
    font-size: 22px;
  }

  .no-image {
    color: #909399;
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
    transition: background 0.15s ease, color 0.15s ease;
  }

  .image-count {
    position: absolute;
    right: 6px;
    bottom: 6px;
    min-width: 20px;
    height: 18px;
    padding: 0 6px;
    border-radius: 9px;
    background: rgba(17, 24, 39, 0.72);
    color: #fff;
    font-size: 12px;
    line-height: 18px;
    text-align: center;
  }

  .resource-title {
    margin-bottom: 12px;
    font-weight: 700;
    color: $textRegular;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .resource-desc,
  .tag-text {
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
    align-items: center;
    justify-content: center;
    gap: 12px;
  }

  .jump-input {
    width: 118px;
  }

  .media-preview {
    width: 100%;
    max-height: 70vh;
    background: #000;
  }
}
</style>
