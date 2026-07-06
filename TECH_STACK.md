# WebIM 后台管理系统 · 技术栈与规范文档

> 本项目是 **WebIM 的后台管理系统（Admin / CMS）**，基于 PanJiaChen `vue-admin-template` 改造的内容审核与运营后台。

---

## 一、核心框架与构建

| 维度 | 实际情况 |
|---|---|
| **前端框架** | **Vue 2.6.10**（Options API，**非 Vue 3**，无 `<script setup>`） |
| **构建工具** | **Vue CLI 4.4.4 + Webpack 4**（**不是 Vite**） |
| **语言** | **纯 JavaScript**（**无 TypeScript**，使用 `jsconfig.json` 而非 `tsconfig.json`） |
| **转译** | Babel（`@vue/cli-plugin-babel/preset`），开发态用 `dynamic-import-node` 加速热更新 |
| **Node 要求** | `node >= 8.9`，`npm >= 3.0.0` |
| **浏览器目标** | `> 1%`，`last 2 versions` |

### 启动 / 构建命令

```bash
npm run dev          # 开发服务器，端口 9528，自动打开浏览器
npm run build:prod   # 生产构建
npm run build:stage  # staging 构建（--mode staging）
npm run lint         # ESLint 检查 src
npm run test:unit    # Jest 单元测试
```

---

## 二、UI / 状态 / 路由

- **UI 框架：Element UI 2.13.2**
  - 注意是 Element **UI**（Vue 2 版），**不是** Vue 3 的 Element Plus。
  - `main.js` 中默认设为英文 locale，可切换中文。
- **状态管理：Vuex 3.1.0**
  - 模块化：`app` / `settings` / `user` / `tagsView`。
  - 统一通过 `store/getters.js` 暴露 `token` / `name` / `avatar` / `sidebar` / `device`。
- **路由：Vue Router 3.0.6**
  - **hash 模式**（`history` 模式被注释掉）。
  - 全部走 `constantRoutes` 静态路由，**未启用动态权限路由**（`meta.roles` 字段保留但未实际使用）。
- **样式：SCSS**（sass 1.26.8 + sass-loader 8）+ `normalize.css`
  - **无 Tailwind / UnoCSS / Less**。
- **图标：svg-sprite-loader** 自定义 SVG symbol（`src/icons`，`symbolId: icon-[name]`）。

---

## 三、关键第三方依赖（业务重点）

| 库 | 版本 | 用途 |
|---|---|---|
| **axios** | 0.18.1 | HTTP 封装（版本较老，注意安全/兼容性） |
| **video.js** | ^8.23 | 视频播放 |
| **hls.js** | ^1.6 | HLS 流播放/审核（`HlsPlayer.vue`、`YouTubeHlsPlayer.vue`） |
| **crypto-js** | ^4.2 | **AES-CBC 解密 S3 加密图片/视频**，兼容 Python 后端加密格式（零 IV） |
| **echarts / vue-echarts** | 5 / 6 | 图表 |
| js-cookie | 2.2.0 | Token 存储 |
| nprogress | 0.2.0 | 路由切换进度条 |
| path-to-regexp | 2.4.0 | 路由路径匹配 |
| mockjs | 1.0.1-beta3 | Mock 数据（`mock/` 目录，devServer 注入） |

---

## 四、目录结构

```
src/
├── api/          # 按业务拆分的接口模块
│                 #   account / video / movie / short / publish /
│                 #   cert / feedback / picture / category / table / user
├── views/        # 页面，按业务域分目录（列表 + detail + reviewList 模式）
│                 #   account / cert / category / short / movie / publish /
│                 #   download / feedback / image / video / detail / dashboard / login
├── components/   # 通用组件（SvgIcon / Breadcrumb / Hamburger / Video / Publish）
├── layout/       # 后台骨架（Navbar / Sidebar / TagsView / AppMain / ScrollPane）
├── store/        # Vuex 模块（app / settings / user / tagsView） + getters
├── router/       # 单一 index.js 集中式路由
├── utils/        # request.js(axios) / auth.js / 加解密 / 下载工具 / validate
├── icons/        # SVG sprite 图标
├── styles/       # 全局 SCSS
├── settings.js   # 全局配置（title / fixedHeader / sidebarLogo）
├── permission.js # 全局路由守卫（登录态拦截）
└── main.js       # 入口
```

> **注意本项目没有**：`composables/` 目录、国际化（i18n）方案、TypeScript 类型层 —— 这些是 Vue 3 项目的产物，本项目均无。

---

## 五、业务域（路由模块）

后台管理的核心业务模块：

| 模块 | 路由 | 说明 |
|---|---|---|
| 首页 | `/dashboard` | 仪表盘 |
| 认证管理 | `/cert` | 认证列表 / 认证详情 |
| 会员管理 | `/account` | 会员列表 / 评论列表 / 相册列表 |
| 类型标签 | `/category` | 分类管理 / 标签管理 |
| 短视频管理 | `/short` | 列表 / 审核 |
| 影视管理 | `/movie` | 列表 / 审核 |
| 帖子管理 | `/publish` | 列表 / 审核 |
| 图片管理 | `/image` | 列表 / 审核 |
| 视频管理 | `/video` | 列表 / 审核 / HLS 播放器 |
| 下载管理 | `/download` | 配置 / Telegram 登录 / 视频预览 / 任务列表 |
| 反馈管理 | `/feedback` | 反馈列表 / 分类管理 |

整体是一个**内容审核 + 运营后台**，核心场景为：会员/认证管理、UGC 内容（视频/短视频/影视/帖子/图片）审核、Telegram 资源下载任务管理。

---

## 六、必须遵守的规范

### 1. API 封装（新增模块照抄）

`api/*.js` 统一模式：

```js
import request from '@/utils/request'

export function getAccountList(data) {
  return request({ url: '/api/account/getList', method: 'post', data })
}
```

后端协议约定（见 `utils/request.js`）：

- 成功判定为 **`res.ret === 'OK'`**（**非** HTTP status，**非** `code === 20000`）；否则弹 Element `Message` 报错并 reject。
- 请求头携带 **`Authorization: Bearer <token>`**，token 由 `@/utils/auth` 管理。
- `baseURL` 走 `VUE_APP_BASE_API`，超时 5000ms。
- 接口基本统一用 **`POST`**。

### 2. 路由规范

- 每个业务域一个 `Layout` 包裹块。
- `name` **必填**（`<keep-alive>` 依赖）。
- `meta.title` 中文、`meta.icon` 指定侧边栏图标。
- 子页用 `hidden: true` 从侧边栏隐藏。

### 3. 代码风格（ESLint，开发态 `lintOnSave`，提交前须过）

继承 `plugin:vue/recommended` + `eslint:recommended`，关键自定义规则：

- **无分号**（`semi: never`）
- **单引号**（`quotes: single`）
- **2 空格缩进**，`SwitchCase: 1`
- 组件 `name` 用 **PascalCase**
- 函数名与括号间**无空格**（`space-before-function-paren: never`）
- `prefer-const`、`eqeqeq`（`null` 例外）
- 对象大括号内留空格（`object-curly-spacing: always`），数组方括号内不留空格

### 4. 路径别名

`@` → `src`（webpack `configureWebpack.resolve.alias` + `jsconfig.json` `paths` 双配，IDE 与构建均生效）。

---

## 七、环境配置

| 文件 | `VUE_APP_BASE_API` |
|---|---|
| `.env.development` | `https://adminapi.sfthyf.cn` |
| `.env.production` | `https://adminapi.sfthyf.cn` |
| `.env.staging` | （staging 模式） |

---

## 八、一句话总结

> **Vue 2.6 + Vue CLI(Webpack) + Element UI + Vuex + Vue Router 3 + axios** 构建的内容审核运营后台，
> 纯 JavaScript、无 TS、无 Vite、无 i18n；接口以 `res.ret === 'OK'` 判成功、`POST` + Bearer Token，
> 特色能力是 HLS 视频审核与 S3 AES 加密媒体解密。
