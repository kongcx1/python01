import request from '@/utils/request'

export function getConfig() {
  return request({ url: '/config', method: 'get' })
}

export function updateConfig(data) {
  return request({ url: '/config', method: 'post', data })
}

export function sendLoginCode(data) {
  return request({ url: '/auth/send_code', method: 'post', data, timeout: 120000 })
}

export function verifyLoginCode(data) {
  return request({ url: '/auth/verify_code', method: 'post', data, timeout: 120000 })
}

export function getLoginStatus(params) {
  return request({ url: '/auth/status', method: 'get', params, timeout: 12000 })
}

export function logout(params) {
  return request({ url: '/auth/logout', method: 'post', params })
}

export function previewVideos(data) {
  return request({ url: '/preview', method: 'post', data, timeout: 65000 })
}

export function createTask(data) {
  return request({ url: '/tasks', method: 'post', data })
}

export function getTasks(params) {
  return request({ url: '/tasks', method: 'get', params })
}

export function getTaskLog(taskId, params) {
  return request({ url: `/tasks/${taskId}/log`, method: 'get', params })
}

export function getTaskFiles(taskId) {
  return request({ url: `/tasks/${taskId}/files`, method: 'get' })
}

export function getCompletedDownloads(params) {
  return request({ url: '/downloads/completed', method: 'get', params })
}

export function deleteCompletedDownload(data) {
  return request({ url: '/downloads/completed/delete', method: 'post', data })
}

export function cancelTask(taskId) {
  return request({ url: `/tasks/${taskId}/cancel`, method: 'post' })
}

export function retryTask(taskId) {
  return request({ url: `/tasks/${taskId}/retry`, method: 'post' })
}

export function uploadTask(taskId) {
  return request({ url: `/tasks/${taskId}/upload`, method: 'post' })
}

export function deleteTask(taskId) {
  return request({ url: `/tasks/${taskId}`, method: 'delete' })
}

export function cleanupLocalVideos() {
  return request({ url: '/downloads/local-videos/cleanup', method: 'post' })
}

export function uploadExternalVideoLibrary(data) {
  return request({ url: '/external/video-library/upload', method: 'post', data, timeout: 0 })
}

export function getExternalVideoLibraryJob(jobId) {
  return request({ url: `/external/video-library/jobs/${jobId}`, method: 'get' })
}

export function removeTaskItems(taskId, data) {
  return request({ url: `/tasks/${taskId}/remove`, method: 'post', data })
}

export function pauseTaskItem(taskId, data) {
  return request({ url: `/tasks/${taskId}/pause`, method: 'post', data })
}
