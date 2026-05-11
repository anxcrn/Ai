# Power Codex Studio (Advanced PWA)

Full-stack local web app with:
- Multi-agent orchestration UI
- Python backend API server
- PWA support (manifest + service worker)
- Model selection for mission dispatch
- Mobile bridge connectivity checks

## Run
```bash
cd unified_app
python server.py
```
Open: `http://127.0.0.1:8787`

## APIs
- `GET /api/agents`
- `GET /api/models`
- `GET /api/health`
- `GET /api/timeline`
- `POST /api/dispatch` `{ "mission": "...", "model": "gpt-5.3-codex" }`
- `GET /api/mobile/ping?endpoint=http://...`
