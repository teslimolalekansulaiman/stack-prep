import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// The API runs separately (make api). Proxying in development keeps the client on one
// origin, so cookie-based sessions behave as they will in production. Set API_PROXY when
// the API is not on its default port.
const api = process.env.API_PROXY ?? 'http://127.0.0.1:8000';

export default defineConfig({
  plugins: [react()],
  server: {
    port: Number(process.env.PORT ?? 5173),
    proxy: {
      '/health': api,
      '/v1': api,
    },
  },
  build: {
    target: 'es2020',
    sourcemap: true,
  },
});
