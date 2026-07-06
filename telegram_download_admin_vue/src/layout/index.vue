<template>
  <div class="app-wrapper">
    <aside class="sidebar">
      <div class="sidebar-title">WebIM Admin</div>
      <router-link class="sidebar-link" exact to="/download">账号登录</router-link>
      <router-link class="sidebar-link" to="/download/config">任务配置</router-link>
      <router-link class="sidebar-link" to="/download/preview">任务管理</router-link>
      <router-link class="sidebar-link" to="/download/task-list">任务列表</router-link>
      <router-link class="sidebar-link" to="/download/tasks">下载列表</router-link>
      <router-link class="sidebar-link" to="/download/completed">完成列表</router-link>
    </aside>
    <section class="main-container">
      <header class="navbar">
        <div>
          <div class="navbar-title">Telegram 下载管理</div>
          <div class="navbar-subtitle">账号登录、任务配置、任务管理、任务列表、下载列表和完成列表</div>
        </div>
      </header>
      <main class="app-main">
        <router-view />
      </main>
    </section>
  </div>
</template>

<script>
export default {
  name: 'Layout'
}
</script>
