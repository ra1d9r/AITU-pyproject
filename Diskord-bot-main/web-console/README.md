# Bot Administration Web Console

This is the single-page application (SPA) web console for the Telegram Bot Administrator.

## Features
- **Landing Page**: Stylish entry point with "Login via Telegram" simulation.
- **Dashboard**: Main control panel with server statistics and bot settings.
- **Server Folders**: Visual grid for managing multiple server contexts.
- **Logs**: Detailed log viewer with status highlighting.
- **🎭 Мемы**: Real-time meme feed with upload, likes/dislikes, and sorting.
- **⭐ Мем дня**: Automatic "Meme of the Day" based on like count.
- **Responsive Design**: Adapts from mobile to desktop screens.

## How to Run

### Option 1: Static (without backend)
Simply open `index.html` in any modern web browser.
> Note: Meme features require the backend server.

### Option 2: With Backend (full features)

1. **Install dependencies:**
   ```bash
   cd server
   npm install
   ```

2. **Start the server:**
   ```bash
   npm start
   ```

3. **Open in browser:**
   ```
   http://localhost:3000
   ```

## Project Structure
```
web-console/
├── index.html        # Main entry point and layout
├── styles.css        # All visual styles (Dark Theme + Neon Yellow)
├── app.js            # Logic for navigation, memes, WebSocket
├── server/           # Backend server
│   ├── server.js     # Express + WebSocket server
│   ├── database.js   # SQLite database logic
│   ├── package.json  # Node.js dependencies
│   └── memes.db      # SQLite database (auto-created)
└── uploads/          # Uploaded meme images (auto-created)
```

## Meme Features

### Meme Feed (Развлечение → Мемы)
- Upload images (JPG, PNG, GIF, WebP up to 10MB)
- Add optional caption
- Like/Dislike voting (1 vote per user)
- Sort by: New or Popular
- Real-time updates via WebSocket

### Meme of the Day (Развлечение → Мем дня)
- Shows meme with most likes
- Auto-updates when leader changes
- Top-5 memes leaderboard

### How to test "Meme of the Day" switching:
1. Upload 2+ memes
2. Like one meme to make it leader
3. Like another meme more times
4. Observe automatic leader change notification

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/memes` | Get all memes (query: `sort=new\|popular`) |
| POST | `/api/memes` | Upload new meme (multipart form) |
| POST | `/api/memes/:id/vote` | Vote on meme (body: `{userId, voteType}`) |
| GET | `/api/meme-of-day` | Get current meme of day + top 5 |

## WebSocket Events

| Event | Direction | Description |
|-------|-----------|-------------|
| `new_meme` | Server → Client | New meme was uploaded |
| `vote_update` | Server → Client | Vote count changed |
| `leader_change` | Server → Client | Meme of the day changed |

## Browser Support
Works in all modern browsers (Chrome, Firefox, Edge, Safari). No build step required.

