const state = {
  sidebar: {
    opened: true
  },
  device: 'desktop'
}

const mutations = {
  TOGGLE_SIDEBAR: state => {
    state.sidebar.opened = !state.sidebar.opened
  },
  SET_DEVICE: (state, device) => {
    state.device = device
  }
}

const actions = {
  toggleSideBar({ commit }) {
    commit('TOGGLE_SIDEBAR')
  },
  setDevice({ commit }, device) {
    commit('SET_DEVICE', device)
  }
}

export default {
  namespaced: true,
  state,
  mutations,
  actions
}
