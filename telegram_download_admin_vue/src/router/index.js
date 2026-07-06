import Vue from 'vue'
import Router from 'vue-router'
import Layout from '@/layout'

Vue.use(Router)

export const constantRoutes = [
  {
    path: '/',
    redirect: '/download'
  },
  {
    path: '/download',
    component: Layout,
    children: [
      {
        path: '',
        name: 'DownloadLogin',
        component: () => import('@/views/download/login'),
        meta: { title: '账号登录', icon: 'user' }
      },
      {
        path: 'config',
        name: 'Download',
        component: () => import('@/views/download/index'),
        meta: { title: '任务配置', icon: 'download' }
      },
      {
        path: 'detect',
        name: 'DownloadDetect',
        component: () => import('@/views/download/detect'),
        meta: { title: '检测结果', icon: 'search', hidden: true }
      },
      {
        path: 'preview',
        name: 'DownloadPreview',
        component: () => import('@/views/download/preview'),
        meta: { title: '任务管理', icon: 'search' }
      },
      {
        path: 'task-list',
        name: 'DownloadTaskList',
        component: () => import('@/views/download/task-list'),
        meta: { title: '任务列表', icon: 'list' }
      },
      {
        path: 'tasks',
        name: 'DownloadTasks',
        component: () => import('@/views/download/tasks'),
        meta: { title: '下载列表', icon: 'list' }
      },
      {
        path: 'completed',
        name: 'DownloadCompleted',
        component: () => import('@/views/download/completed'),
        meta: { title: '完成列表', icon: 'finished' }
      }
    ]
  }
]

const createRouter = () => new Router({
  scrollBehavior: () => ({ y: 0 }),
  routes: constantRoutes
})

const router = createRouter()

export default router
