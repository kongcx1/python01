<template>
  <div class="completed-page">
    <el-card class="page-card" shadow="never">
      <div slot="header" class="page-title">完成列表</div>

      <div class="filter-row">
        <div class="filter-item">
          <span class="filter-label">关键词</span>
          <el-input v-model="filters.keyword" size="small" placeholder="输入关键词" clearable @keyup.enter.native="searchItems" />
        </div>
        <div class="filter-item">
          <span class="filter-label">类型</span>
          <el-select v-model="filters.type" size="small" placeholder="全部">
            <el-option label="全部" value="all" />
            <el-option label="短视频" value="short" />
            <el-option label="长视频" value="long" />
          </el-select>
        </div>
        <el-button type="primary" icon="el-icon-search" :loading="loading" @click="searchItems">搜索</el-button>
        <el-button icon="el-icon-refresh-left" @click="resetFilters">重置</el-button>
        <el-button :disabled="!selectedRows.length" @click="deleteSelected">批量管理</el-button>
      </div>

      <el-table
        v-loading="loading"
        class="completed-table"
        :data="visibleItems"
        border
        size="small"
        @selection-change="handleSelection"
      >
        <el-table-column type="selection" width="54" />
        <el-table-column label="" width="390">
          <template slot-scope="{ row }">
            <div class="media-cell">
              <div class="cover-wrap">
                <el-image v-if="mainImage(row)" class="cover" :src="imageUrl(row, mainImage(row))" fit="cover" />
                <div v-else class="cover empty-cover">无封面</div>
                <span class="play-mark"><i class="el-icon-video-play" /></span>
              </div>
              <div class="thumb-row">
                <div
                  v-for="(image, index) in imageList(row)"
                  :key="`${row.output_dir}-${row.message_id}-${index}`"
                  class="mini-thumb"
                  :class="{ active: image === mainImage(row) }"
                >
                  <el-image v-if="image" :src="imageUrl(row, image)" fit="cover" />
                </div>
              </div>
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
        <el-table-column label="完成时间" width="170">
          <template slot-scope="{ row }">{{ formatDateTime(row.completed_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="120" fixed="right">
          <template slot-scope="{ row }">
            <el-button size="mini" type="danger" @click="deleteOne(row)">删除</el-button>
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
          :total="total"
          @current-change="handlePageChange"
          @size-change="handleSizeChange"
        />
      </div>
    </el-card>
  </div>
</template>

<script>
import { getCompletedDownloads, deleteCompletedDownload } from '@/api/download'
import { getRuntimeBaseUrl } from '@/utils/request'
import { formatBytes, formatDateTime } from '@/utils/format'
import { loadDownloadForm } from '@/utils/downloadForm'

export default {
  name: 'DownloadCompleted',
  data() {
    return {
      form: loadDownloadForm(),
      loading: false,
      items: [],
      total: 0,
      page: 1,
      pageSize: 10,
      selectedRows: [],
      filters: {
        keyword: '',
        type: 'all'
      }
    }
  },
  computed: {
    visibleItems() {
      if (this.filters.type === 'all') return this.items
      return this.items.filter(item => this.itemType(item) === this.filters.type)
    }
  },
  created() {
    this.loadItems()
  },
  methods: {
    formatBytes,
    formatDateTime,
    async loadItems() {
      this.loading = true
      try {
        const data = await getCompletedDownloads({
          limit: this.pageSize,
          offset: (this.page - 1) * this.pageSize,
          q: this.filters.keyword.trim()
        })
        this.items = data.items || []
        this.total = Number(data.total || 0)
      } catch (error) {
        this.$message.error(error.message || '读取完成列表失败')
      } finally {
        this.loading = false
      }
    },
    searchItems() {
      this.page = 1
      this.loadItems()
    },
    resetFilters() {
      this.filters = {
        keyword: '',
        type: 'all'
      }
      this.page = 1
      this.loadItems()
    },
    handlePageChange(page) {
      this.page = page
      this.loadItems()
    },
    handleSizeChange(size) {
      this.pageSize = size
      this.page = 1
      this.loadItems()
    },
    handleSelection(rows) {
      this.selectedRows = rows
    },
    allImages(row) {
      return (row.cover_files || []).concat(row.extra_images || []).filter(Boolean)
    },
    mainImage(row) {
      const images = this.allImages(row)
      return images[2] || images[0]
    },
    imageList(row) {
      return this.allImages(row).slice(0, 4)
    },
    imageUrl(row, path) {
      return `${getRuntimeBaseUrl()}/preview/image?output_dir=${encodeURIComponent(row.output_dir)}&path=${encodeURIComponent(path)}`
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
      const duration = Number(row.duration || 0)
      return duration > threshold ? 'long' : 'short'
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
    },
    async deleteOne(row) {
      await this.$confirm('确认删除这条已下载数据？本地视频和封面也会删除。', '提示', { type: 'warning' })
      await deleteCompletedDownload({
        output_dir: row.output_dir,
        message_id: row.message_id
      })
      this.$message.success('已删除')
      this.loadItems()
    },
    async deleteSelected() {
      await this.$confirm(`确认删除 ${this.selectedRows.length} 条已下载数据？`, '提示', { type: 'warning' })
      await Promise.all(this.selectedRows.map(row => deleteCompletedDownload({
        output_dir: row.output_dir,
        message_id: row.message_id
      })))
      this.selectedRows = []
      this.$message.success('已删除所选数据')
      this.loadItems()
    }
  }
}
</script>

<style lang="scss" scoped>
.completed-page {
  .page-title {
    font-size: 16px;
    font-weight: 700;
  }

  .filter-row {
    display: flex;
    align-items: center;
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

  .completed-table {
    margin-top: 8px;
  }

  .media-cell {
    width: 210px;
    margin: 0 auto;
  }

  .cover-wrap {
    position: relative;
    width: 220px;
    height: 132px;
    margin: 0 auto 8px;
  }

  .cover {
    width: 220px;
    height: 132px;
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
    width: 28px;
    height: 28px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    background: rgba(255, 255, 255, 0.9);
    color: #606266;
  }

  .thumb-row {
    display: flex;
    justify-content: center;
    gap: 7px;
  }

  .mini-thumb {
    width: 64px;
    height: 42px;
    border-radius: 4px;
    overflow: hidden;
    border: 1px solid transparent;
    background: #f3f4f6;
  }

  .mini-thumb.active {
    border-color: #409eff;
  }

  .mini-thumb .el-image {
    width: 100%;
    height: 100%;
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
    -webkit-line-clamp: 4;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .pagination-row {
    margin-top: 16px;
    display: flex;
    justify-content: flex-end;
  }
}
</style>
