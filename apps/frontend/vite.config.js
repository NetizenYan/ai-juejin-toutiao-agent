import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd())
  return {
    plugins: [vue()],
    server: {
      // VITE_API_BASE_URL 设为空时前端走同源 /api，由开发服务器转发给后端；
      // 远程打开页面（端口转发、其他设备）时只需暴露前端这一个端口。
      proxy: {
        '/api': {
          target: env.VITE_DEV_PROXY_TARGET || 'http://127.0.0.1:8030',
          changeOrigin: true,
        },
      },
    },
  }
})
