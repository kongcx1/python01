import defaultSettings from '@/settings'

const state = {
  title: defaultSettings.title,
  fixedHeader: defaultSettings.fixedHeader,
  sidebarLogo: defaultSettings.sidebarLogo
}

export default {
  namespaced: true,
  state
}
