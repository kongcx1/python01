import { getToken } from '@/utils/auth'
import { getRuntimeBaseUrl, setRuntimeBaseUrl } from '@/utils/request'

export const DownloadFormKey = 'telegram_admin_download_form'

export function defaultDownloadForm() {
  return {
    serverBase: getRuntimeBaseUrl(),
    token: getToken(),
    apiId: '',
    apiHash: '',
    channel: '@sosocw',
    chatId: '',
    outputDir: 'C:\\IdeaWork\\python01\\downloads',
    concurrency: 2,
    uploadAccount: '',
    uploadPassword: '',
    uploadApiToken: '',
    autoUpload: '',
    uploadMeta: '',
    shortThreshold: 600,
    trimHeadSeconds: 0,
    trimJsonVideoUpload: false,
    trimTelegramDirectUpload: false,
    trimLocalFileUpload: false,
    minDuration: 10,
    countryCode: '+86',
    phoneNumber: '',
    code: '',
    password: '',
    previewLimit: 30
  }
}

export function loadDownloadForm() {
  const form = defaultDownloadForm()
  const raw = localStorage.getItem(DownloadFormKey)
  if (!raw) return form
  try {
    const saved = JSON.parse(raw)
    const merged = { ...form, ...saved, token: getToken() }
    setRuntimeBaseUrl(merged.serverBase)
    return merged
  } catch (error) {
    localStorage.removeItem(DownloadFormKey)
    return form
  }
}

export function saveDownloadForm(form) {
  setRuntimeBaseUrl(form.serverBase)
  localStorage.setItem(
    DownloadFormKey,
    JSON.stringify({ ...form, token: undefined, password: undefined, code: undefined })
  )
}

export function hasLoginFields(form) {
  return Boolean(form.apiId && form.apiHash && form.outputDir)
}
