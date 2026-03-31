// LLM Bomberman — Frontend Renderer
const canvas = document.getElementById("game-canvas");
const ctx = canvas.getContext("2d");
const TILE = 48;
const COLS = 15;
const ROWS = 13;

// Cell types
const FLOOR = 0;
const WALL = 1;
const BRICK = 2;

// Colors
const COLOR_FLOOR = "#4a7c3f";
const COLOR_WALL = "#888888";
const COLOR_WALL_BORDER = "#666666";
const COLOR_BRICK = "#8b4513";
const COLOR_BRICK_HIGHLIGHT = "#a0522d";
const COLOR_P1 = "#7c3aed";
const COLOR_P2 = "#e85d04";
const COLOR_BOMB = "#111111";
const COLOR_FUSE = "#ffffff";
const COLOR_EXPLOSION1 = "#ff6600";
const COLOR_EXPLOSION2 = "#ffcc00";

let lastState = null;
let lastP1Score = 0;
let lastP2Score = 0;

// --- WebSocket ---
function connectWS() {
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${protocol}//${location.host}/ws`);
    const statusEl = document.getElementById("connection-status");

    ws.onopen = () => {
        statusEl.textContent = "Connected";
        statusEl.className = "connected";
    };

    ws.onmessage = (event) => {
        const state = JSON.parse(event.data);
        lastState = state;
        render(state);
        updateHUD(state);
        updateThoughts(state);
    };

    ws.onclose = () => {
        statusEl.textContent = "Disconnected — reconnecting...";
        statusEl.className = "disconnected";
        setTimeout(connectWS, 2000);
    };

    ws.onerror = () => {
        ws.close();
    };
}

connectWS();

// --- Rendering ---
function render(state) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const grid = state.grid;
    const explosionSet = new Set();
    const bombMap = new Map();

    // Build explosion set
    for (const exp of state.explosions) {
        for (const [x, y] of exp.cells) {
            explosionSet.add(`${x},${y}`);
        }
    }

    // Build bomb map
    for (const bomb of state.bombs) {
        bombMap.set(`${bomb.pos[0]},${bomb.pos[1]}`, bomb);
    }

    // 1. Draw floor & walls & bricks
    for (let y = 0; y < ROWS; y++) {
        for (let x = 0; x < COLS; x++) {
            const cell = grid[y][x];
            const px = x * TILE;
            const py = y * TILE;

            if (cell === WALL) {
                ctx.fillStyle = COLOR_WALL;
                ctx.fillRect(px, py, TILE, TILE);
                ctx.strokeStyle = COLOR_WALL_BORDER;
                ctx.lineWidth = 1;
                ctx.strokeRect(px + 0.5, py + 0.5, TILE - 1, TILE - 1);
                // Add subtle pattern
                ctx.fillStyle = "#777777";
                ctx.fillRect(px + 2, py + 2, TILE / 2 - 2, TILE / 2 - 2);
                ctx.fillRect(px + TILE / 2 + 1, py + TILE / 2 + 1, TILE / 2 - 3, TILE / 2 - 3);
            } else if (cell === BRICK) {
                ctx.fillStyle = COLOR_BRICK;
                ctx.fillRect(px, py, TILE, TILE);
                // Brick pattern
                ctx.strokeStyle = "#6b3410";
                ctx.lineWidth = 1;
                ctx.strokeRect(px + 1, py + 1, TILE - 2, TILE - 2);
                // Highlight edge
                ctx.fillStyle = COLOR_BRICK_HIGHLIGHT;
                ctx.fillRect(px + 2, py + 2, TILE - 4, 3);
                ctx.fillRect(px + 2, py + 2, 3, TILE - 4);
            } else {
                ctx.fillStyle = COLOR_FLOOR;
                ctx.fillRect(px, py, TILE, TILE);
                // Subtle grid line
                ctx.strokeStyle = "#3d6b34";
                ctx.lineWidth = 0.5;
                ctx.strokeRect(px, py, TILE, TILE);
            }
        }
    }

    // 2. Draw bombs
    const now = Date.now();
    for (const bomb of state.bombs) {
        const bx = bomb.pos[0] * TILE + TILE / 2;
        const by = bomb.pos[1] * TILE + TILE / 2;
        const fuseRatio = bomb.fuse_ticks / 30;
        // Pulse speed increases as fuse decreases
        const pulseFreq = 2 + (1 - fuseRatio) * 15;
        const pulseSize = Math.sin(now * pulseFreq / 1000 * Math.PI * 2) * 3;
        const radius = TILE / 3 + pulseSize;

        ctx.beginPath();
        ctx.arc(bx, by, Math.max(radius, 5), 0, Math.PI * 2);
        ctx.fillStyle = COLOR_BOMB;
        ctx.fill();
        ctx.strokeStyle = bomb.owner === "p1" ? COLOR_P1 : COLOR_P2;
        ctx.lineWidth = 2;
        ctx.stroke();

        // Fuse dot
        ctx.beginPath();
        ctx.arc(bx, by - radius + 2, 3, 0, Math.PI * 2);
        ctx.fillStyle = fuseRatio < 0.3 ? "#ff3333" : COLOR_FUSE;
        ctx.fill();
    }

    // 3. Draw explosions
    for (const exp of state.explosions) {
        const alpha = Math.min(1, exp.ttl_ticks / 3);
        for (const [x, y] of exp.cells) {
            const px = x * TILE;
            const py = y * TILE;

            ctx.globalAlpha = alpha;
            // Outer glow
            ctx.fillStyle = COLOR_EXPLOSION1;
            ctx.fillRect(px + 2, py + 2, TILE - 4, TILE - 4);
            // Inner bright
            ctx.fillStyle = COLOR_EXPLOSION2;
            ctx.fillRect(px + 8, py + 8, TILE - 16, TILE - 16);
            ctx.globalAlpha = 1;
        }
    }

    // 4. Draw players
    for (const pid of ["p1", "p2"]) {
        const player = state.players[pid];
        if (!player.alive) continue;

        const px = player.pos[0] * TILE + TILE / 2;
        const py = player.pos[1] * TILE + TILE / 2;
        const color = pid === "p1" ? COLOR_P1 : COLOR_P2;

        // Shadow
        ctx.beginPath();
        ctx.ellipse(px + 2, py + 4, TILE / 3, TILE / 5, 0, 0, Math.PI * 2);
        ctx.fillStyle = "rgba(0,0,0,0.3)";
        ctx.fill();

        // Body
        ctx.beginPath();
        ctx.arc(px, py, TILE / 3, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.fill();
        ctx.strokeStyle = "#ffffff";
        ctx.lineWidth = 2;
        ctx.stroke();

        // Label
        ctx.fillStyle = "#ffffff";
        ctx.font = "bold 14px Courier New";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(pid === "p1" ? "1" : "2", px, py);
    }

    // 5. Game over overlay
    if (state.game_over) {
        drawGameOver(state);
    }
}

function drawGameOver(state) {
    // Semi-transparent overlay
    ctx.fillStyle = "rgba(0, 0, 0, 0.7)";
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    ctx.textAlign = "center";
    ctx.textBaseline = "middle";

    const cx = canvas.width / 2;
    const cy = canvas.height / 2;

    // Winner text
    let winnerText;
    if (state.winner === "draw") {
        winnerText = "DRAW!";
        ctx.fillStyle = "#ffcc00";
    } else if (state.winner === "p1") {
        winnerText = "BOMBER-1 WINS!";
        ctx.fillStyle = COLOR_P1;
    } else {
        winnerText = "BOMBER-2 WINS!";
        ctx.fillStyle = COLOR_P2;
    }

    ctx.font = "bold 36px Courier New";
    ctx.fillText(winnerText, cx, cy - 40);

    // Reason
    let reasonText = "";
    if (state.win_reason === "kill") {
        reasonText = "Reason: opponent eliminated";
    } else if (state.win_reason === "bricks") {
        reasonText = "Reason: all bricks destroyed";
    } else if (state.win_reason === "timer") {
        reasonText = "Reason: time expired";
    }

    ctx.fillStyle = "#cccccc";
    ctx.font = "16px Courier New";
    ctx.fillText(reasonText, cx, cy + 10);

    // Final score
    const p1s = state.players.p1.score;
    const p2s = state.players.p2.score;
    ctx.fillStyle = "#ffffff";
    ctx.font = "20px Courier New";
    ctx.fillText(`Final score: ${p1s} - ${p2s}`, cx, cy + 45);
}

// --- HUD ---
function updateHUD(state) {
    const p1ScoreEl = document.getElementById("p1-score");
    const p2ScoreEl = document.getElementById("p2-score");
    const bricksEl = document.getElementById("bricks-display");
    const timeEl = document.getElementById("time-display");

    const p1Score = state.players.p1.score;
    const p2Score = state.players.p2.score;

    // Flash on score change
    if (p1Score !== lastP1Score) {
        p1ScoreEl.classList.add("score-flash");
        setTimeout(() => p1ScoreEl.classList.remove("score-flash"), 300);
    }
    if (p2Score !== lastP2Score) {
        p2ScoreEl.classList.add("score-flash");
        setTimeout(() => p2ScoreEl.classList.remove("score-flash"), 300);
    }

    lastP1Score = p1Score;
    lastP2Score = p2Score;

    p1ScoreEl.textContent = p1Score;
    p2ScoreEl.textContent = p2Score;
    bricksEl.textContent = `Bricks: ${state.bricks_remaining}`;

    const totalSec = Math.max(0, Math.floor(state.time_remaining_ticks / 10));
    const min = Math.floor(totalSec / 60);
    const sec = totalSec % 60;
    const timeStr = `${min}:${sec.toString().padStart(2, "0")}`;
    timeEl.textContent = timeStr;

    if (totalSec < 30) {
        timeEl.classList.add("time-critical");
    } else {
        timeEl.classList.remove("time-critical");
    }
}

// --- Thoughts ---
let lastP1Thought = "";
let lastP2Thought = "";
let thinkingDots = 0;

setInterval(() => {
    thinkingDots = (thinkingDots + 1) % 4;
}, 500);

function updateThoughts(state) {
    const p1ThoughtEl = document.getElementById("p1-thought");
    const p2ThoughtEl = document.getElementById("p2-thought");
    const p1ActionEl = document.getElementById("p1-action");
    const p2ActionEl = document.getElementById("p2-action");

    const p1Thought = state.agent_thoughts?.p1 || "";
    const p2Thought = state.agent_thoughts?.p2 || "";
    const p1Action = state.agent_last_action?.p1 || "";
    const p2Action = state.agent_last_action?.p2 || "";

    if (p1Thought && p1Thought !== lastP1Thought) {
        p1ThoughtEl.textContent = `"${p1Thought}"`;
        lastP1Thought = p1Thought;
    } else if (!p1Thought) {
        const dots = ".".repeat(thinkingDots);
        p1ThoughtEl.textContent = `thinking${dots}`;
    }

    if (p2Thought && p2Thought !== lastP2Thought) {
        p2ThoughtEl.textContent = `"${p2Thought}"`;
        lastP2Thought = p2Thought;
    } else if (!p2Thought) {
        const dots = ".".repeat(thinkingDots);
        p2ThoughtEl.textContent = `thinking${dots}`;
    }

    p1ActionEl.textContent = p1Action ? `Action: ${p1Action}` : "";
    p2ActionEl.textContent = p2Action ? `Action: ${p2Action}` : "";
}

// Animation loop for smooth bomb pulsing
function animationLoop() {
    if (lastState) {
        render(lastState);
    }
    requestAnimationFrame(animationLoop);
}

requestAnimationFrame(animationLoop);
