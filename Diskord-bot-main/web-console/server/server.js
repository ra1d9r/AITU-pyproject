/**
 * Meme Server - Express.js + WebSocket
 * Handles meme uploads, voting, and real-time updates
 */

const express = require('express');
const cors = require('cors');
const multer = require('multer');
const path = require('path');
const fs = require('fs');
const http = require('http');
const WebSocket = require('ws');
const { initDatabase, memeDB, foldersDB, logsDB, botsDB } = require('./database');

const app = express();
const PORT = process.env.PORT || 3000;

// Create uploads directory if it doesn't exist
const uploadsDir = path.join(__dirname, '..', 'uploads');
if (!fs.existsSync(uploadsDir)) {
    fs.mkdirSync(uploadsDir, { recursive: true });
}

// Middleware
app.use(cors());
app.use(express.json());
app.use(express.static(path.join(__dirname, '..')));
app.use('/uploads', express.static(uploadsDir));

// File upload configuration
const storage = multer.diskStorage({
    destination: (req, file, cb) => {
        cb(null, uploadsDir);
    },
    filename: (req, file, cb) => {
        const uniqueSuffix = Date.now() + '-' + Math.round(Math.random() * 1E9);
        const ext = path.extname(file.originalname).toLowerCase();
        cb(null, 'meme-' + uniqueSuffix + ext);
    }
});

const fileFilter = (req, file, cb) => {
    const allowedTypes = ['image/jpeg', 'image/png', 'image/gif', 'image/webp'];
    if (allowedTypes.includes(file.mimetype)) {
        cb(null, true);
    } else {
        cb(new Error('Invalid file type. Only JPG, PNG, GIF, and WebP are allowed.'), false);
    }
};

const upload = multer({
    storage,
    fileFilter,
    limits: {
        fileSize: 10 * 1024 * 1024 // 10MB max
    }
});

// Create HTTP server and WebSocket server
const server = http.createServer(app);
const wss = new WebSocket.Server({ server });

// Track connected clients
const clients = new Set();

wss.on('connection', (ws) => {
    clients.add(ws);
    console.log('Client connected. Total clients:', clients.size);

    ws.on('close', () => {
        clients.delete(ws);
        console.log('Client disconnected. Total clients:', clients.size);
    });

    ws.on('error', (error) => {
        console.error('WebSocket error:', error);
        clients.delete(ws);
    });
});

// Broadcast to all connected clients
function broadcast(event, data) {
    const message = JSON.stringify({ event, data });
    clients.forEach(client => {
        if (client.readyState === WebSocket.OPEN) {
            client.send(message);
        }
    });
}

// Track current meme of day to detect changes
let currentMemeOfDayId = null;

function checkAndBroadcastLeaderChange(userId) {
    const newLeader = memeDB.getMemeOfDay(userId);
    const newLeaderId = newLeader ? newLeader.id : null;

    if (newLeaderId !== currentMemeOfDayId) {
        currentMemeOfDayId = newLeaderId;
        memeDB.updateMemeOfDayLeader();
        broadcast('leader_change', { memeOfDay: newLeader });
    }
}

// API Routes

// Get all memes
app.get('/api/memes', (req, res) => {
    try {
        const userId = req.query.userId || '';
        const sortBy = req.query.sort || 'new'; // 'new' or 'popular'
        const memes = memeDB.getAllMemes(userId, sortBy);
        res.json({ success: true, memes });
    } catch (error) {
        console.error('Error fetching memes:', error);
        res.status(500).json({ success: false, error: 'Failed to fetch memes' });
    }
});

// Upload new meme
app.post('/api/memes', upload.single('image'), (req, res) => {
    try {
        if (!req.file) {
            return res.status(400).json({ success: false, error: 'No image uploaded' });
        }

        const userId = req.body.userId;
        if (!userId) {
            return res.status(400).json({ success: false, error: 'User ID required' });
        }

        const caption = req.body.caption || '';
        const imagePath = '/uploads/' + req.file.filename;

        const meme = memeDB.createMeme(imagePath, caption, userId);

        // Broadcast new meme to all clients
        broadcast('new_meme', { meme });

        res.json({ success: true, meme });
    } catch (error) {
        console.error('Error uploading meme:', error);
        res.status(500).json({ success: false, error: 'Failed to upload meme' });
    }
});

// Vote on a meme
app.post('/api/memes/:id/vote', (req, res) => {
    try {
        const memeId = parseInt(req.params.id);
        const { userId, voteType } = req.body;

        if (!userId) {
            return res.status(400).json({ success: false, error: 'User ID required' });
        }

        if (!['like', 'dislike'].includes(voteType)) {
            return res.status(400).json({ success: false, error: 'Invalid vote type' });
        }

        const result = memeDB.vote(memeId, userId, voteType);
        const updatedMeme = memeDB.getMemeById(memeId, userId);

        // Broadcast vote update to all clients
        broadcast('vote_update', {
            memeId,
            likeCount: updatedMeme.like_count,
            dislikeCount: updatedMeme.dislike_count
        });

        // Check if meme of day changed
        checkAndBroadcastLeaderChange(userId);

        res.json({ success: true, result, meme: updatedMeme });
    } catch (error) {
        console.error('Error voting:', error);
        res.status(500).json({ success: false, error: 'Failed to vote' });
    }
});

// Get meme of the day
app.get('/api/meme-of-day', (req, res) => {
    try {
        const userId = req.query.userId || '';
        const memeOfDay = memeDB.getMemeOfDay(userId);
        const topMemes = memeDB.getTopMemes(userId, 5);

        res.json({ success: true, memeOfDay, topMemes });
    } catch (error) {
        console.error('Error fetching meme of day:', error);
        res.status(500).json({ success: false, error: 'Failed to fetch meme of day' });
    }
});

// Delete a meme (only by owner)
app.delete('/api/memes/:id', (req, res) => {
    try {
        const memeId = parseInt(req.params.id);
        const userId = req.body.userId || req.query.userId;

        if (!userId) {
            return res.status(400).json({ success: false, error: 'User ID required' });
        }

        const result = memeDB.deleteMeme(memeId, userId);

        if (!result.success) {
            return res.status(403).json(result);
        }

        // Try to delete the image file
        if (result.imagePath) {
            const filePath = path.join(__dirname, '..', result.imagePath);
            fs.unlink(filePath, (err) => {
                if (err) console.error('Failed to delete image file:', err);
            });
        }

        // Broadcast meme deletion to all clients
        broadcast('meme_deleted', { memeId });

        // Check if meme of day changed
        checkAndBroadcastLeaderChange(userId);

        res.json({ success: true });
    } catch (error) {
        console.error('Error deleting meme:', error);
        res.status(500).json({ success: false, error: 'Failed to delete meme' });
    }
});

// ===========================
// FOLDERS API
// ===========================

// Get all folders
app.get('/api/folders', (req, res) => {
    try {
        const folders = foldersDB.getAllFolders();
        res.json(folders);
    } catch (error) {
        console.error('Error getting folders:', error);
        res.status(500).json({ error: 'Failed to get folders' });
    }
});

// Create folder
app.post('/api/folders', (req, res) => {
    try {
        const { name, color, ownerId } = req.body;
        if (!name || !ownerId) {
            return res.status(400).json({ error: 'Name and ownerId are required' });
        }
        const folder = foldersDB.createFolder(name, ownerId, color);
        broadcast('folder_created', folder);
        res.json(folder);
    } catch (error) {
        console.error('Error creating folder:', error);
        res.status(500).json({ error: 'Failed to create folder' });
    }
});

// Update folder
app.put('/api/folders/:id', (req, res) => {
    try {
        const folderId = parseInt(req.params.id);
        const { name, color, ownerId } = req.body;
        const success = foldersDB.updateFolder(folderId, name, color, ownerId);
        if (success) {
            const folder = foldersDB.getFolderById(folderId);
            broadcast('folder_updated', folder);
            res.json(folder);
        } else {
            res.status(404).json({ error: 'Folder not found or not authorized' });
        }
    } catch (error) {
        console.error('Error updating folder:', error);
        res.status(500).json({ error: 'Failed to update folder' });
    }
});

// Delete folder
app.delete('/api/folders/:id', (req, res) => {
    try {
        const folderId = parseInt(req.params.id);
        const { ownerId } = req.body;
        const success = foldersDB.deleteFolder(folderId, ownerId);
        if (success) {
            broadcast('folder_deleted', { folderId });
            res.json({ success: true });
        } else {
            res.status(404).json({ error: 'Folder not found or not authorized' });
        }
    } catch (error) {
        console.error('Error deleting folder:', error);
        res.status(500).json({ error: 'Failed to delete folder' });
    }
});

// Get servers in folder
app.get('/api/folders/:id/servers', (req, res) => {
    try {
        const folderId = parseInt(req.params.id);
        const servers = foldersDB.getServersInFolder(folderId);
        res.json(servers);
    } catch (error) {
        console.error('Error getting servers:', error);
        res.status(500).json({ error: 'Failed to get servers' });
    }
});

// Add server to folder
app.post('/api/folders/:id/servers', (req, res) => {
    try {
        const folderId = parseInt(req.params.id);
        const { serverId, serverName, serverIcon } = req.body;
        if (!serverId || !serverName) {
            return res.status(400).json({ error: 'serverId and serverName are required' });
        }
        foldersDB.addServerToFolder(folderId, serverId, serverName, serverIcon);
        const servers = foldersDB.getServersInFolder(folderId);
        broadcast('server_added', { folderId, servers });
        res.json({ success: true, servers });
    } catch (error) {
        console.error('Error adding server:', error);
        res.status(500).json({ error: 'Failed to add server' });
    }
});

// Remove server from folder
app.delete('/api/folders/:folderId/servers/:serverId', (req, res) => {
    try {
        const folderId = parseInt(req.params.folderId);
        const serverId = req.params.serverId;
        const success = foldersDB.removeServerFromFolder(folderId, serverId);
        if (success) {
            broadcast('server_removed', { folderId, serverId });
            res.json({ success: true });
        } else {
            res.status(404).json({ error: 'Server not found in folder' });
        }
    } catch (error) {
        console.error('Error removing server:', error);
        res.status(500).json({ error: 'Failed to remove server' });
    }
});

// ===========================
// MESSAGE LOGS API
// ===========================

// Get message logs with pagination
app.get('/api/logs/messages', (req, res) => {
    try {
        const limit = parseInt(req.query.limit) || 50;
        const cursor = req.query.cursor ? parseInt(req.query.cursor) : null;
        const serverId = req.query.serverId || null;

        const result = logsDB.getMessageLogs(limit, cursor, serverId);
        const total = logsDB.getMessageLogsCount(serverId);

        res.json({ success: true, ...result, total });
    } catch (error) {
        console.error('Error getting message logs:', error);
        res.status(500).json({ success: false, error: 'Failed to get message logs' });
    }
});

// Add message log (for testing or bot integration)
app.post('/api/logs/messages', (req, res) => {
    try {
        const { serverId, serverName, userId, username, content, channelName } = req.body;
        if (!userId || !username || !content) {
            return res.status(400).json({ error: 'userId, username, and content are required' });
        }
        const logId = logsDB.addMessageLog(serverId, serverName, userId, username, content, channelName);
        broadcast('message_logged', { id: logId, ...req.body, created_at: new Date().toISOString() });
        res.json({ success: true, id: logId });
    } catch (error) {
        console.error('Error adding message log:', error);
        res.status(500).json({ error: 'Failed to add message log' });
    }
});

// Get action logs with pagination
app.get('/api/logs/actions', (req, res) => {
    try {
        const limit = parseInt(req.query.limit) || 50;
        const cursor = req.query.cursor ? parseInt(req.query.cursor) : null;
        const serverId = req.query.serverId || null;
        const actionType = req.query.actionType || null;

        const result = logsDB.getActionLogs(limit, cursor, serverId, actionType);
        const total = logsDB.getActionLogsCount(serverId, actionType);

        res.json({ success: true, ...result, total });
    } catch (error) {
        console.error('Error getting action logs:', error);
        res.status(500).json({ success: false, error: 'Failed to get action logs' });
    }
});

// Add action log
app.post('/api/logs/actions', (req, res) => {
    try {
        const { actionType, actorId, actorName, targetType, targetId, targetName, details, serverId, serverName } = req.body;
        if (!actionType || !actorId || !actorName) {
            return res.status(400).json({ error: 'actionType, actorId, and actorName are required' });
        }
        const logId = logsDB.addActionLog(actionType, actorId, actorName, targetType, targetId, targetName, details, serverId, serverName);
        broadcast('action_logged', { id: logId, ...req.body, created_at: new Date().toISOString() });
        res.json({ success: true, id: logId });
    } catch (error) {
        console.error('Error adding action log:', error);
        res.status(500).json({ error: 'Failed to add action log' });
    }
});

// ===========================
// BOTS API
// ===========================

// Get bot settings
app.get('/api/bots/:id', (req, res) => {
    try {
        const botId = parseInt(req.params.id) || 1;
        const bot = botsDB.getOrCreateBot(botId);

        if (!bot) {
            return res.status(404).json({ success: false, error: 'Bot not found' });
        }

        // Convert snake_case to camelCase for frontend
        res.json({
            success: true,
            bot: {
                id: bot.id,
                name: bot.name,
                commandPrefix: bot.command_prefix,
                serverLogs: !!bot.server_logs,
                bigActions: !!bot.big_actions,
                autoModeration: !!bot.auto_moderation,
                activityLogging: !!bot.activity_logging,
                welcomeMessages: !!bot.welcome_messages,
                updatedAt: bot.updated_at,
                createdAt: bot.created_at
            }
        });
    } catch (error) {
        console.error('Error getting bot:', error);
        res.status(500).json({ success: false, error: 'Failed to get bot settings' });
    }
});

// Update bot settings (PATCH)
app.patch('/api/bots/:id', (req, res) => {
    try {
        const botId = parseInt(req.params.id) || 1;
        const updates = req.body;
        const actorName = req.body.actorName || 'System';

        // Remove actorName from updates
        delete updates.actorName;

        if (Object.keys(updates).length === 0) {
            return res.status(400).json({ success: false, error: 'No fields to update' });
        }

        const updatedBot = botsDB.updateBot(botId, updates);

        if (!updatedBot) {
            return res.status(404).json({ success: false, error: 'Bot not found or no valid fields' });
        }

        // Log the action
        const changedFields = Object.keys(updates).join(', ');
        logsDB.addActionLog(
            'bot_updated',
            'admin',
            actorName,
            'bot',
            String(botId),
            updatedBot.name,
            `Changed: ${changedFields}`,
            null,
            null
        );

        // Broadcast update
        broadcast('bot_updated', { botId, updates });

        res.json({
            success: true,
            bot: {
                id: updatedBot.id,
                name: updatedBot.name,
                commandPrefix: updatedBot.command_prefix,
                serverLogs: !!updatedBot.server_logs,
                bigActions: !!updatedBot.big_actions,
                autoModeration: !!updatedBot.auto_moderation,
                activityLogging: !!updatedBot.activity_logging,
                welcomeMessages: !!updatedBot.welcome_messages,
                updatedAt: updatedBot.updated_at
            }
        });
    } catch (error) {
        console.error('Error updating bot:', error);
        res.status(500).json({ success: false, error: 'Failed to update bot settings' });
    }
});

// Serve index.html for root
app.get('/', (req, res) => {
    res.sendFile(path.join(__dirname, '..', 'index.html'));
});

// Error handling middleware
app.use((error, req, res, next) => {
    if (error instanceof multer.MulterError) {
        if (error.code === 'LIMIT_FILE_SIZE') {
            return res.status(400).json({ success: false, error: 'File too large. Maximum size is 10MB.' });
        }
    }
    console.error('Server error:', error);
    res.status(500).json({ success: false, error: error.message || 'Server error' });
});

// Start server
async function startServer() {
    try {
        // Initialize database first
        await initDatabase();
        console.log('Database initialized');

        server.listen(PORT, () => {
            console.log(`
╔════════════════════════════════════════╗
║       MEME SERVER STARTED              ║
╠════════════════════════════════════════╣
║  HTTP: http://localhost:${PORT}          ║
║  WebSocket: ws://localhost:${PORT}       ║
╚════════════════════════════════════════╝
            `);

            // Initialize current meme of day
            const initialLeader = memeDB.getMemeOfDay('');
            currentMemeOfDayId = initialLeader ? initialLeader.id : null;
        });
    } catch (error) {
        console.error('Failed to start server:', error);
        process.exit(1);
    }
}

startServer();

module.exports = { app, server, wss };

