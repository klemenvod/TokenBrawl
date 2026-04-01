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
let currentWS = null;

// --- Smooth movement interpolation with position queue ---
const MOVE_DURATION = 160; // ms per cell — tuned for 2-tick (200ms) backend steps
const playerInterp = {
    p1: { x: 1, y: 1, queue: [], segStart: 0, fromX: 1, fromY: 1, toX: 1, toY: 1, animating: false },
    p2: { x: 13, y: 11, queue: [], segStart: 0, fromX: 13, fromY: 11, toX: 13, toY: 11, animating: false },
};

function updatePlayerInterp(pid, newX, newY) {
    const interp = playerInterp[pid];
    // Only enqueue if this is a genuinely new target
    const lastQueued = interp.queue.length > 0 ? interp.queue[interp.queue.length - 1] : null;
    const lastX = lastQueued ? lastQueued[0] : interp.toX;
    const lastY = lastQueued ? lastQueued[1] : interp.toY;
    if (newX !== lastX || newY !== lastY) {
        interp.queue.push([newX, newY]);
        if (!interp.animating) {
            advanceQueue(pid);
        }
    }
}

function advanceQueue(pid) {
    const interp = playerInterp[pid];
    if (interp.queue.length === 0) {
        interp.animating = false;
        return;
    }
    const [nx, ny] = interp.queue.shift();
    interp.fromX = interp.x;
    interp.fromY = interp.y;
    interp.toX = nx;
    interp.toY = ny;
    interp.segStart = performance.now();
    interp.animating = true;
}

function getInterpPos(pid, now) {
    const interp = playerInterp[pid];
    if (!interp.animating) {
        return { x: interp.x, y: interp.y };
    }
    const elapsed = now - interp.segStart;
    let t = Math.min(1, elapsed / MOVE_DURATION);
    // Smooth ease-in-out (sine) for fluid continuous motion
    t = 0.5 - 0.5 * Math.cos(Math.PI * t);
    const cx = interp.fromX + (interp.toX - interp.fromX) * t;
    const cy = interp.fromY + (interp.toY - interp.fromY) * t;
    // When segment finishes, snap and try next queued position
    if (elapsed >= MOVE_DURATION) {
        interp.x = interp.toX;
        interp.y = interp.toY;
        advanceQueue(pid);
        // If there's a next segment, blend into it immediately
        if (interp.animating) {
            return getInterpPos(pid, now);
        }
        return { x: interp.x, y: interp.y };
    }
    return { x: cx, y: cy };
}

// --- Start Button ---
const startBtn = document.getElementById("start-btn");
startBtn.addEventListener("click", () => {
    if (currentWS && currentWS.readyState === WebSocket.OPEN) {
        currentWS.send("start");
        startBtn.style.display = "none";
    }
});

// --- Restart Button ---
const restartBtn = document.getElementById("restart-btn");
restartBtn.addEventListener("click", () => {
    if (currentWS && currentWS.readyState === WebSocket.OPEN) {
        currentWS.send("restart");
        restartBtn.style.display = "none";
        deathLogShown = false;
        document.getElementById("death-log").style.display = "none";
        // Reset interpolation to spawn positions
        playerInterp.p1 = { x: 1, y: 1, queue: [], segStart: 0, fromX: 1, fromY: 1, toX: 1, toY: 1, animating: false };
        playerInterp.p2 = { x: 13, y: 11, queue: [], segStart: 0, fromX: 13, fromY: 11, toX: 13, toY: 11, animating: false };
    }
});

// --- WebSocket ---
function connectWS() {
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${protocol}//${location.host}/ws`);
    const statusEl = document.getElementById("connection-status");
    currentWS = ws;

    ws.onopen = () => {
        statusEl.textContent = "Connected";
        statusEl.className = "connected";
    };

    ws.onmessage = (event) => {
        const state = JSON.parse(event.data);
        lastState = state;
        startBtn.style.display = "none";

        // Feed positions into interpolation system
        for (const pid of ["p1", "p2"]) {
            const p = state.players[pid];
            if (p.alive) {
                updatePlayerInterp(pid, p.pos[0], p.pos[1]);
            } else {
                // Snap dead players
                const interp = playerInterp[pid];
                interp.x = p.pos[0];
                interp.y = p.pos[1];
                interp.queue = [];
                interp.animating = false;
            }
        }

        updateHUD(state);
        updateThoughts(state);
        updateDeathLog(state);

        if (state.game_over) {
            restartBtn.style.display = "block";
        } else {
            restartBtn.style.display = "none";
        }
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

                // Coordinate labels on border walls
                if (y === 0 || y === ROWS - 1 || x === 0 || x === COLS - 1) {
                    let label = "";
                    if ((y === 0 || y === ROWS - 1) && x > 0 && x < COLS - 1) {
                        label = String(x);
                    } else if ((x === 0 || x === COLS - 1) && y > 0 && y < ROWS - 1) {
                        label = String(y);
                    }
                    if (label) {
                        ctx.fillStyle = "rgba(255,255,255,0.5)";
                        ctx.font = "bold 11px Courier New";
                        ctx.textAlign = "center";
                        ctx.textBaseline = "middle";
                        ctx.fillText(label, px + TILE / 2, py + TILE / 2);
                    }
                }
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
        const fuseRatio = bomb.fuse_ticks / 60;

        // Static bomb circle (no pulse animation)
        const radius = TILE / 3;

        ctx.beginPath();
        ctx.arc(bx, by, radius, 0, Math.PI * 2);
        ctx.fillStyle = "#333333";
        ctx.fill();
        ctx.strokeStyle = bomb.owner === "p1" ? COLOR_P1 : COLOR_P2;
        ctx.lineWidth = 2;
        ctx.stroke();

        // Countdown timer text
        const secondsLeft = Math.ceil(bomb.fuse_ticks / 10);
        const timerColor = fuseRatio < 0.3 ? "#ff3333" : "#ffffff";
        ctx.font = "bold 18px Courier New";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        // Dark outline for readability
        ctx.strokeStyle = "#000000";
        ctx.lineWidth = 3;
        ctx.strokeText(secondsLeft, bx, by);
        // Fill text on top
        ctx.fillStyle = timerColor;
        ctx.fillText(secondsLeft, bx, by);
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
    const now = performance.now();
    for (const pid of ["p1", "p2"]) {
        const player = state.players[pid];
        if (!player.alive) continue;

        const interpPos = getInterpPos(pid, now);
        const px = interpPos.x * TILE + TILE / 2;
        const py = interpPos.y * TILE + TILE / 2;
        const color = pid === "p1" ? COLOR_P1 : COLOR_P2;

        // Intent line to target tile
        const target = state.agent_target?.[pid];
        if (target && target.pos) {
            const tx = target.pos[0] * TILE + TILE / 2;
            const ty = target.pos[1] * TILE + TILE / 2;
            ctx.beginPath();
            ctx.moveTo(px, py);
            ctx.lineTo(tx, ty);
            ctx.strokeStyle = target.bomb ? "rgba(255,50,50,0.7)" : "rgba(255,255,255,0.45)";
            ctx.lineWidth = target.bomb ? 2 : 1.5;
            ctx.setLineDash([6, 4]);
            ctx.stroke();
            ctx.setLineDash([]);
            // Small marker on target tile
            ctx.beginPath();
            ctx.arc(tx, ty, 4, 0, Math.PI * 2);
            ctx.fillStyle = target.bomb ? "rgba(255,50,50,0.8)" : "rgba(255,255,255,0.6)";
            ctx.fill();
        }

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

        // Thinking bubble when waiting for LLM response
        if (state.agent_thinking && state.agent_thinking[pid]) {
            const bubbleX = px + 12;
            const bubbleY = py - TILE / 2 - 10;

            // Bubble background
            ctx.fillStyle = "rgba(255,255,255,0.9)";
            ctx.beginPath();
            ctx.roundRect(bubbleX - 16, bubbleY - 8, 32, 16, 4);
            ctx.fill();

            // Animated dots
            const dotPhase = Math.floor(Date.now() / 300) % 4;
            ctx.fillStyle = "#333";
            ctx.font = "bold 12px Courier New";
            ctx.textAlign = "center";
            ctx.textBaseline = "middle";
            const dots = ".".repeat(dotPhase || 1);
            ctx.fillText(dots, bubbleX, bubbleY);

            // Small triangle pointing to player
            ctx.fillStyle = "rgba(255,255,255,0.9)";
            ctx.beginPath();
            ctx.moveTo(bubbleX - 4, bubbleY + 8);
            ctx.lineTo(bubbleX + 2, bubbleY + 8);
            ctx.lineTo(px + 6, py - TILE / 3);
            ctx.fill();
        }
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

// --- Death Log ---
let deathLogShown = false;

function updateDeathLog(state) {
    const deathLogEl = document.getElementById("death-log");

    console.log("death_log:", JSON.stringify(state.death_log));

    if (!state.death_log || Object.keys(state.death_log).length === 0) {
        if (!state.game_over) {
            deathLogEl.style.display = "none";
            deathLogShown = false;
        }
        return;
    }

    if (deathLogShown) return;
    deathLogShown = true;

    let html = "<h3>DEATH LOG</h3>";

    for (const [pid, log] of Object.entries(state.death_log)) {
        const label = pid === "p1" ? "BOMBER-1" : "BOMBER-2";
        const color = pid === "p1" ? "#7c3aed" : "#e85d04";
        html += `<div class="death-entry">`;
        html += `<div style="color:${color};font-weight:bold">${label} killed at (${log.killed_at[0]},${log.killed_at[1]}) on tick ${log.tick}</div>`;

        if (log.last_actions && log.last_actions.length > 0) {
            html += `<div style="margin-top:4px;color:#ff9999">Last actions:</div>`;
            for (const a of log.last_actions) {
                const targetStr = a.target ? ` → (${a.target[0]},${a.target[1]})` : "";
                html += `<div class="action-line">  tick ${a.tick} | pos (${a.pos[0]},${a.pos[1]}) | ${a.action}${targetStr} | "${a.reasoning}"</div>`;
            }
        }
        html += `</div>`;
    }

    deathLogEl.innerHTML = html;
    deathLogEl.style.display = "block";
}

// Animation loop for smooth bomb pulsing
function animationLoop() {
    if (lastState) {
        render(lastState);
    }
    requestAnimationFrame(animationLoop);
}

requestAnimationFrame(animationLoop);
