import { resolve } from 'path'
import { defineConfig, externalizeDepsPlugin } from 'electron-vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  main: {
    plugins: [externalizeDepsPlugin()],
  },
  preload: {
    plugins: [externalizeDepsPlugin()],
  },
  renderer: {
    resolve: {
      alias: {
        '@renderer': resolve('src/renderer/src'),
      },
    },
    plugins: [react(), tailwindcss()],
    // Multiple HTML entry points: mascot window + chat window
    build: {
      rollupOptions: {
        input: {
          chat:  resolve('src/renderer/chat.html'),
          notif: resolve('src/renderer/notif.html'),
        },
      },
    },
  },
})
