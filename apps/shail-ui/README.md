# Shail Dashboard UI

React dashboard interface for the Shail AI Operating System.

## Setup

1. Install dependencies:
```bash
npm install
```

2. Set environment variables (optional):
Create a `.env` file with:
```
VITE_API_URL=http://localhost:8000
```

## Development

Start the development server:
```bash
npm run dev
```

The UI will be available at `http://localhost:3000`

## Production Build

Build for production:
```bash
npm run build
```

Preview production build:
```bash
npm run preview
```

## Features

- **Chat Interface**: Submit tasks to Shail via text input
- **Task Queue**: Real-time view of all tasks with live status updates
- **Permission Modal**: Auto-appears when tasks require approval
- **Status Badges**: Color-coded task status indicators
- **Responsive Design**: Works on desktop and mobile devices

## Prerequisites

- Node.js 18+ and npm
- Shail backend API running on `http://localhost:8000`
- Redis server running (for task queue)
- Task worker process running (`python -m shail.workers.task_worker`)

