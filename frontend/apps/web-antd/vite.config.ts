import { defineConfig } from '@vben/vite-config';

export default defineConfig(async () => {
  return {
    application: {},
    vite: {
      server: {
        proxy: {
          // 同源代理：页面只依赖 5666 一个源，/api 由 Vite 转发到后端，
          // 避免外部浏览器代理拦截 127.0.0.1:8000 造成的跨域访问失败
          '/api': {
            changeOrigin: true,
            rewrite: (path) => path.replace(/^\/api/, '/api/v1'),
            target: 'http://127.0.0.1:8000',
            ws: true,
          },
        },
      },
    },
  };
});
