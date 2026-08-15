# Xun web

Vue 3 and TypeScript frontend for `xun.WebDisplay`.

```bash
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. This one command starts a local `xuns` backend for the repository root and Vite with Vue DevTools. Vite proxies `/api` and `/ws` to FastAPI at `http://127.0.0.1:18960` and authenticates them with a development-only token.

To use a backend you manage separately, run only the UI and configure its proxy:

```bash
VITE_XUN_BACKEND=http://127.0.0.1:18960 \
VITE_XUN_TOKEN=your-token \
npm run dev:ui
```

Set `VITE_XUN_BASE_PATH=/agents/research` when the display is mounted below the backend root.

```bash
npm run build
```

The production build is written to `../src/xun/assets/web`, where `WebDisplay` serves it and the Python wheel includes it as package data.
