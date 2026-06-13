# Frontend

React + Vite client for the RAG assistant, built with MongoDB's
[LeafyGreen](https://www.mongodb.design/) design system.

- **Dev server:** `npm run dev` — serves at http://localhost:5180 and proxies
  `/api` to the FastAPI backend on port 8180.
- **Build:** `npm run build` — outputs a production bundle to `dist/`.
- **Lint:** `npm run lint`.

See the [project README](../README.md) for the full setup, including the
backend and MongoDB Atlas configuration.

## Layout

- `src/App.jsx` — application state and orchestration
- `src/api.js` — config/status requests and the SSE chat stream
- `src/components/` — UI components (Sidebar, TopBar, KpiRow, ChatMessage, EngineStrip, Sources, ...)
- `src/index.css` — global styles and design tokens
- `src/theme.js` — color palette
