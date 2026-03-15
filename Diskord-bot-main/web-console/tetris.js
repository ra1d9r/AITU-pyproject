/**
 * Tetris Game Engine
 * Full-featured Tetris implementation with SRS rotation
 */

const TetrisGame = (function () {
    'use strict';

    // ===========================
    // CONSTANTS
    // ===========================
    const COLS = 10;
    const ROWS = 20;
    const BLOCK_SIZE = 30;

    // Tetromino shapes and colors
    const PIECES = {
        I: { shape: [[1, 1, 1, 1]], color: '#00f5ff' },
        O: { shape: [[1, 1], [1, 1]], color: '#ffeb3b' },
        T: { shape: [[0, 1, 0], [1, 1, 1]], color: '#e040fb' },
        S: { shape: [[0, 1, 1], [1, 1, 0]], color: '#76ff03' },
        Z: { shape: [[1, 1, 0], [0, 1, 1]], color: '#ff5252' },
        J: { shape: [[1, 0, 0], [1, 1, 1]], color: '#448aff' },
        L: { shape: [[0, 0, 1], [1, 1, 1]], color: '#ff9100' }
    };

    const PIECE_NAMES = ['I', 'O', 'T', 'S', 'Z', 'J', 'L'];

    // Scoring
    const POINTS = {
        1: 100,   // Single
        2: 300,   // Double
        3: 500,   // Triple
        4: 800    // Tetris
    };

    // Speed levels (ms per drop) - base speeds
    const SPEEDS = [800, 720, 630, 550, 470, 380, 300, 220, 130, 100, 80, 60, 50, 40, 30];

    // Difficulty settings
    const DIFFICULTIES = {
        easy: { name: 'Лёгкий', startLevel: 1, speedMultiplier: 1.3, icon: '🌱' },
        normal: { name: 'Нормальный', startLevel: 1, speedMultiplier: 1.0, icon: '🎮' },
        hard: { name: 'Сложный', startLevel: 5, speedMultiplier: 0.8, icon: '🔥' },
        extreme: { name: 'Экстрим', startLevel: 10, speedMultiplier: 0.5, icon: '💀' }
    };

    // ===========================
    // STATE
    // ===========================
    let canvas, ctx, nextCanvas, nextCtx;
    let board = [];
    let currentPiece = null;
    let nextPiece = null;
    let bag = [];
    let score = 0;
    let level = 1;
    let lines = 0;
    let gameState = 'idle'; // idle, playing, paused, gameover
    let dropInterval = null;
    let lastDropTime = 0;
    let animationId = null;
    let currentDifficulty = 'normal';
    let speedMultiplier = 1.0;

    // DOM Elements
    let scoreEl, levelEl, linesEl, overlayEl, overlayTitleEl, overlayMessageEl;
    let startBtn, pauseBtn, restartBtn, difficultyBtns;

    // ===========================
    // INITIALIZATION
    // ===========================
    function init() {
        canvas = document.getElementById('tetris-canvas');
        nextCanvas = document.getElementById('tetris-next');

        if (!canvas || !nextCanvas) return;

        ctx = canvas.getContext('2d');
        nextCtx = nextCanvas.getContext('2d');

        // Get DOM elements
        scoreEl = document.getElementById('tetris-score');
        levelEl = document.getElementById('tetris-level');
        linesEl = document.getElementById('tetris-lines');
        overlayEl = document.getElementById('tetris-overlay');
        overlayTitleEl = document.getElementById('overlay-title');
        overlayMessageEl = document.getElementById('overlay-message');
        startBtn = document.getElementById('tetris-start');
        pauseBtn = document.getElementById('tetris-pause');
        restartBtn = document.getElementById('tetris-restart');

        // Button events
        startBtn?.addEventListener('click', start);
        pauseBtn?.addEventListener('click', togglePause);
        restartBtn?.addEventListener('click', restart);

        // Difficulty buttons
        document.querySelectorAll('.difficulty-btn').forEach(btn => {
            btn.addEventListener('click', () => setDifficulty(btn.dataset.difficulty));
        });

        // Keyboard events
        document.addEventListener('keydown', handleKeydown);

        // Mobile controls
        document.querySelectorAll('.mobile-btn').forEach(btn => {
            btn.addEventListener('click', () => handleMobileAction(btn.dataset.action));
            btn.addEventListener('touchstart', (e) => {
                e.preventDefault();
                handleMobileAction(btn.dataset.action);
            });
        });

        // Initial render
        resetGame();
        render();
        showOverlay('TETRIS', 'Нажми Start');
    }

    // ===========================
    // GAME LOGIC
    // ===========================
    function resetGame() {
        board = Array(ROWS).fill(null).map(() => Array(COLS).fill(0));
        bag = [];
        currentPiece = null;
        nextPiece = null;
        score = 0;
        const diff = DIFFICULTIES[currentDifficulty];
        level = diff.startLevel;
        speedMultiplier = diff.speedMultiplier;
        lines = 0;
        updateStats();
    }

    function setDifficulty(diff) {
        if (gameState === 'playing') return;
        currentDifficulty = diff;

        // Update button states
        document.querySelectorAll('.difficulty-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.difficulty === diff);
        });

        resetGame();
        render();
        const diffInfo = DIFFICULTIES[diff];
        showOverlay('TETRIS', `${diffInfo.icon} ${diffInfo.name}`);
    }

    function start() {
        if (gameState === 'playing') return;

        if (gameState === 'gameover' || gameState === 'idle') {
            resetGame();
        }

        gameState = 'playing';
        hideOverlay();

        startBtn.disabled = true;
        pauseBtn.disabled = false;

        spawnPiece();
        lastDropTime = performance.now();
        gameLoop();
    }

    function togglePause() {
        if (gameState === 'playing') {
            gameState = 'paused';
            pauseBtn.textContent = '▶ Resume';
            showOverlay('ПАУЗА', 'Нажми Resume');
            cancelAnimationFrame(animationId);
        } else if (gameState === 'paused') {
            gameState = 'playing';
            pauseBtn.textContent = '⏸ Pause';
            hideOverlay();
            lastDropTime = performance.now();
            gameLoop();
        }
    }

    function restart() {
        cancelAnimationFrame(animationId);
        resetGame();
        gameState = 'idle';
        startBtn.disabled = false;
        pauseBtn.disabled = true;
        pauseBtn.textContent = '⏸ Pause';
        render();
        showOverlay('TETRIS', 'Нажми Start');
    }

    function gameOver() {
        gameState = 'gameover';
        cancelAnimationFrame(animationId);
        startBtn.disabled = false;
        pauseBtn.disabled = true;
        showOverlay('GAME OVER', `Score: ${score}`);
    }

    // ===========================
    // PIECE MANAGEMENT
    // ===========================
    function getBag() {
        if (bag.length === 0) {
            bag = [...PIECE_NAMES];
            // Fisher-Yates shuffle
            for (let i = bag.length - 1; i > 0; i--) {
                const j = Math.floor(Math.random() * (i + 1));
                [bag[i], bag[j]] = [bag[j], bag[i]];
            }
        }
        return bag.pop();
    }

    function createPiece(type) {
        const pieceData = PIECES[type];
        return {
            type,
            shape: pieceData.shape.map(row => [...row]),
            color: pieceData.color,
            x: Math.floor(COLS / 2) - Math.ceil(pieceData.shape[0].length / 2),
            y: 0
        };
    }

    function spawnPiece() {
        if (nextPiece) {
            currentPiece = nextPiece;
        } else {
            currentPiece = createPiece(getBag());
        }
        nextPiece = createPiece(getBag());

        // Reset position for current piece
        currentPiece.x = Math.floor(COLS / 2) - Math.ceil(currentPiece.shape[0].length / 2);
        currentPiece.y = 0;

        // Check if spawn position is valid
        if (!isValidPosition(currentPiece, currentPiece.x, currentPiece.y)) {
            gameOver();
        }

        renderNext();
    }

    // ===========================
    // COLLISION DETECTION
    // ===========================
    function isValidPosition(piece, newX, newY, newShape = piece.shape) {
        for (let row = 0; row < newShape.length; row++) {
            for (let col = 0; col < newShape[row].length; col++) {
                if (newShape[row][col]) {
                    const boardX = newX + col;
                    const boardY = newY + row;

                    if (boardX < 0 || boardX >= COLS || boardY >= ROWS) {
                        return false;
                    }

                    if (boardY >= 0 && board[boardY][boardX]) {
                        return false;
                    }
                }
            }
        }
        return true;
    }

    // ===========================
    // PIECE MOVEMENT
    // ===========================
    function movePiece(dx, dy) {
        if (gameState !== 'playing' || !currentPiece) return false;

        const newX = currentPiece.x + dx;
        const newY = currentPiece.y + dy;

        if (isValidPosition(currentPiece, newX, newY)) {
            currentPiece.x = newX;
            currentPiece.y = newY;
            return true;
        }
        return false;
    }

    function rotatePiece(direction = 1) {
        if (gameState !== 'playing' || !currentPiece) return;

        const shape = currentPiece.shape;
        const rows = shape.length;
        const cols = shape[0].length;

        // Create rotated shape
        const rotated = [];
        for (let col = 0; col < cols; col++) {
            const newRow = [];
            for (let row = rows - 1; row >= 0; row--) {
                newRow.push(shape[row][col]);
            }
            rotated.push(direction === 1 ? newRow : newRow.reverse());
        }

        if (direction === -1) {
            rotated.reverse();
        }

        // Try rotation with wall kicks
        const kicks = [0, -1, 1, -2, 2];
        for (const kick of kicks) {
            if (isValidPosition(currentPiece, currentPiece.x + kick, currentPiece.y, rotated)) {
                currentPiece.shape = rotated;
                currentPiece.x += kick;
                return;
            }
        }
    }

    function hardDrop() {
        if (gameState !== 'playing' || !currentPiece) return;

        while (movePiece(0, 1)) {
            score += 2;
        }
        lockPiece();
    }

    function lockPiece() {
        if (!currentPiece) return;

        // Place piece on board
        for (let row = 0; row < currentPiece.shape.length; row++) {
            for (let col = 0; col < currentPiece.shape[row].length; col++) {
                if (currentPiece.shape[row][col]) {
                    const boardY = currentPiece.y + row;
                    const boardX = currentPiece.x + col;
                    if (boardY >= 0) {
                        board[boardY][boardX] = currentPiece.color;
                    }
                }
            }
        }

        clearLines();
        spawnPiece();
    }

    // ===========================
    // LINE CLEARING
    // ===========================
    function clearLines() {
        let linesCleared = 0;

        for (let row = ROWS - 1; row >= 0; row--) {
            if (board[row].every(cell => cell !== 0)) {
                // Remove line
                board.splice(row, 1);
                // Add empty line at top
                board.unshift(Array(COLS).fill(0));
                linesCleared++;
                row++; // Check same row again
            }
        }

        if (linesCleared > 0) {
            lines += linesCleared;
            score += (POINTS[linesCleared] || 0) * level;

            // Level up every 10 lines
            const newLevel = Math.floor(lines / 10) + 1;
            if (newLevel > level) {
                level = Math.min(newLevel, SPEEDS.length);
            }

            updateStats();
        }
    }

    // ===========================
    // GAME LOOP
    // ===========================
    function gameLoop() {
        if (gameState !== 'playing') return;

        const now = performance.now();
        const baseSpeed = SPEEDS[Math.min(level - 1, SPEEDS.length - 1)];
        const dropSpeed = baseSpeed * speedMultiplier;

        if (now - lastDropTime > dropSpeed) {
            if (!movePiece(0, 1)) {
                lockPiece();
            }
            lastDropTime = now;
        }

        render();
        animationId = requestAnimationFrame(gameLoop);
    }

    // ===========================
    // RENDERING
    // ===========================
    function render() {
        if (!ctx) return;

        // Clear canvas
        ctx.fillStyle = '#0a0a0a';
        ctx.fillRect(0, 0, canvas.width, canvas.height);

        // Draw grid
        ctx.strokeStyle = '#1a1a1a';
        ctx.lineWidth = 1;
        for (let x = 0; x <= COLS; x++) {
            ctx.beginPath();
            ctx.moveTo(x * BLOCK_SIZE, 0);
            ctx.lineTo(x * BLOCK_SIZE, ROWS * BLOCK_SIZE);
            ctx.stroke();
        }
        for (let y = 0; y <= ROWS; y++) {
            ctx.beginPath();
            ctx.moveTo(0, y * BLOCK_SIZE);
            ctx.lineTo(COLS * BLOCK_SIZE, y * BLOCK_SIZE);
            ctx.stroke();
        }

        // Draw locked pieces
        for (let row = 0; row < ROWS; row++) {
            for (let col = 0; col < COLS; col++) {
                if (board[row][col]) {
                    drawBlock(ctx, col, row, board[row][col]);
                }
            }
        }

        // Draw ghost piece
        if (currentPiece && gameState === 'playing') {
            let ghostY = currentPiece.y;
            while (isValidPosition(currentPiece, currentPiece.x, ghostY + 1)) {
                ghostY++;
            }

            ctx.globalAlpha = 0.3;
            for (let row = 0; row < currentPiece.shape.length; row++) {
                for (let col = 0; col < currentPiece.shape[row].length; col++) {
                    if (currentPiece.shape[row][col]) {
                        drawBlock(ctx, currentPiece.x + col, ghostY + row, currentPiece.color);
                    }
                }
            }
            ctx.globalAlpha = 1;
        }

        // Draw current piece
        if (currentPiece) {
            for (let row = 0; row < currentPiece.shape.length; row++) {
                for (let col = 0; col < currentPiece.shape[row].length; col++) {
                    if (currentPiece.shape[row][col]) {
                        drawBlock(ctx, currentPiece.x + col, currentPiece.y + row, currentPiece.color);
                    }
                }
            }
        }
    }

    function drawBlock(context, x, y, color) {
        const padding = 2;
        context.fillStyle = color;
        context.fillRect(
            x * BLOCK_SIZE + padding,
            y * BLOCK_SIZE + padding,
            BLOCK_SIZE - padding * 2,
            BLOCK_SIZE - padding * 2
        );

        // Highlight
        context.fillStyle = 'rgba(255,255,255,0.3)';
        context.fillRect(
            x * BLOCK_SIZE + padding,
            y * BLOCK_SIZE + padding,
            BLOCK_SIZE - padding * 2,
            4
        );
    }

    function renderNext() {
        if (!nextCtx || !nextPiece) return;

        nextCtx.fillStyle = '#0a0a0a';
        nextCtx.fillRect(0, 0, nextCanvas.width, nextCanvas.height);

        const shape = nextPiece.shape;
        const blockSize = 25;
        const offsetX = (nextCanvas.width - shape[0].length * blockSize) / 2;
        const offsetY = (nextCanvas.height - shape.length * blockSize) / 2;

        for (let row = 0; row < shape.length; row++) {
            for (let col = 0; col < shape[row].length; col++) {
                if (shape[row][col]) {
                    nextCtx.fillStyle = nextPiece.color;
                    nextCtx.fillRect(
                        offsetX + col * blockSize + 2,
                        offsetY + row * blockSize + 2,
                        blockSize - 4,
                        blockSize - 4
                    );
                }
            }
        }
    }

    function updateStats() {
        if (scoreEl) scoreEl.textContent = score;
        if (levelEl) levelEl.textContent = level;
        if (linesEl) linesEl.textContent = lines;
    }

    function showOverlay(title, message) {
        if (overlayEl) {
            overlayEl.classList.remove('hidden');
            if (overlayTitleEl) overlayTitleEl.textContent = title;
            if (overlayMessageEl) overlayMessageEl.textContent = message;
        }
    }

    function hideOverlay() {
        if (overlayEl) overlayEl.classList.add('hidden');
    }

    // ===========================
    // INPUT HANDLING
    // ===========================
    function handleKeydown(e) {
        // Only handle if Tetris view is visible
        const tetrisView = document.getElementById('view-tetris');
        if (!tetrisView || tetrisView.classList.contains('hidden')) return;

        switch (e.code) {
            case 'ArrowLeft':
                e.preventDefault();
                movePiece(-1, 0);
                break;
            case 'ArrowRight':
                e.preventDefault();
                movePiece(1, 0);
                break;
            case 'ArrowDown':
                e.preventDefault();
                if (movePiece(0, 1)) score += 1;
                break;
            case 'ArrowUp':
            case 'KeyX':
                e.preventDefault();
                rotatePiece(1);
                break;
            case 'KeyZ':
                e.preventDefault();
                rotatePiece(-1);
                break;
            case 'Space':
                e.preventDefault();
                hardDrop();
                break;
            case 'KeyP':
            case 'Escape':
                e.preventDefault();
                if (gameState === 'playing' || gameState === 'paused') {
                    togglePause();
                }
                break;
            case 'KeyR':
                e.preventDefault();
                restart();
                break;
        }

        render();
    }

    function handleMobileAction(action) {
        switch (action) {
            case 'left':
                movePiece(-1, 0);
                break;
            case 'right':
                movePiece(1, 0);
                break;
            case 'down':
                if (movePiece(0, 1)) score += 1;
                break;
            case 'rotateLeft':
                rotatePiece(-1);
                break;
            case 'rotateRight':
                rotatePiece(1);
                break;
            case 'hardDrop':
                hardDrop();
                break;
        }
        render();
    }

    // Public API
    return {
        init,
        start,
        togglePause,
        restart
    };
})();

// Initialize when DOM is ready and Tetris view is shown
document.addEventListener('DOMContentLoaded', () => {
    TetrisGame.init();
});
