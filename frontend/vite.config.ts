import { webcrypto } from "node:crypto";
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

const globalScope = globalThis as typeof globalThis & {
  crypto?: Crypto;
};

if (!globalScope.crypto) {
  globalScope.crypto = webcrypto as unknown as Crypto;
}

export default defineConfig({
  plugins: [vue()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
