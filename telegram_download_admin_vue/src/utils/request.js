import axios from 'axios'
import { Message } from 'element-ui'
import store from '@/store'

const service = axios.create({
  baseURL: process.env.VUE_APP_BASE_API || '',
  timeout: 20000
})

const RuntimeBaseKey = 'telegram_admin_base_url'

export function getRuntimeBaseUrl() {
  return localStorage.getItem(RuntimeBaseKey) || process.env.VUE_APP_BASE_API || 'http://127.0.0.1:8787'
}

export function setRuntimeBaseUrl(url) {
  const value = (url || '').replace(/\/+$/, '')
  localStorage.setItem(RuntimeBaseKey, value)
  service.defaults.baseURL = value
}

service.defaults.baseURL = getRuntimeBaseUrl()

service.interceptors.request.use(
  config => {
    const token = store.getters.token
    config.baseURL = getRuntimeBaseUrl()
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  error => Promise.reject(error)
)

service.interceptors.response.use(
  response => {
    const res = response.data
    if (res && Object.prototype.hasOwnProperty.call(res, 'ret') && res.ret !== 'OK') {
      Message({
        message: res.msg || res.message || '请求失败',
        type: 'error',
        duration: 4000
      })
      return Promise.reject(new Error(res.msg || res.message || '请求失败'))
    }
    return res
  },
  error => {
    const detail = error.response && error.response.data && error.response.data.detail
    const isTimeout = error.code === 'ECONNABORTED' || (error.message || '').indexOf('timeout') >= 0
    const message = detail || (isTimeout
      ? '请求超时，请稍后重试或降低加载条数'
      : error.response && error.response.data
        ? JSON.stringify(error.response.data)
        : error.message)
    Message({
      message,
      type: 'error',
      duration: 5000
    })
    return Promise.reject(error)
  }
)

export default service
