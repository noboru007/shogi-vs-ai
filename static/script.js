const BOARD_SIZE = 9;
const SENTE = 1;
const GOTE = -1;

console.log("SCRIPT LOADED vdebug3");

// Helper to log moves
function logMove(moveCount, modelName, moveStr, reasoning = null) {
    const rArea = document.getElementById('reasoning-area');
    if (!rArea) return;

    // Always show if it's hidden
    rArea.style.display = 'block';

    const entry = document.createElement('div');
    entry.style.borderBottom = "1px solid #eee";
    entry.style.marginBottom = "5px";
    entry.style.paddingBottom = "5px";

    const moveNum = moveCount ? `[#${moveCount}]` : "";
    const mStr = moveStr || "";
    const model = modelName || "Unknown";

    const meta = document.createElement('span');
    meta.textContent = `${moveNum} (${model}) `;
    entry.appendChild(meta);

    const moveBold = document.createElement('strong');
    moveBold.textContent = `${mStr}: `;
    entry.appendChild(moveBold);

    if (reasoning) {
        const reasonText = document.createTextNode(reasoning);
        entry.appendChild(reasonText);
    }

    rArea.insertBefore(entry, rArea.firstChild);
}

let gameState = null;
let selected = null; // {type: 'board', pos: [x, y]} or {type: 'hand', name: 'PieceName'}
let gSenteModel = "gemini-2.5-pro";
let gGoteModel = "gemini-2.5-pro";

// Session Management (Local Only)
function getSessionId() {
    let sid = localStorage.getItem('shogi_session_id');
    if (!sid) {
        sid = 'sess_' + Math.random().toString(36).substr(2, 9);
        localStorage.setItem('shogi_session_id', sid);
    }
    return sid;
}

// Client-Side State Helpers
function updateGameState(newState) {
    if (!newState) return;
    gameState = newState;
    localStorage.setItem('shogi_state', JSON.stringify(gameState));

    // Sync models if present (Persistence fix)
    if (gameState.sente_model) gSenteModel = gameState.sente_model;
    if (gameState.gote_model) gGoteModel = gameState.gote_model;

    render();
}

function loadLocalState() {
    const saved = localStorage.getItem('shogi_state');
    if (saved) {
        try {
            const parsed = JSON.parse(saved);
            updateGameState(parsed);
            return true;
        } catch (e) {
            console.error("Local state parse error", e);
            return false;
        }
    }
    return false;
}

// Direct Cloud Run URL to bypass Firebase Hosting 60s timeout
const IS_LOCALHOST = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
// Cloud Run URL from logs:
const CLOUD_RUN_URL = 'https://shogi-api-5hgqbhxnha-uc.a.run.app';

async function apiCall(endpoint, method = 'GET', body = null) {
    const headers = {
        'X-Session-ID': getSessionId()
    };
    if (body) {
        headers['Content-Type'] = 'application/json';
    }

    const options = { method, headers };
    if (body) options.body = JSON.stringify(body);

    let url;
    if (IS_LOCALHOST) {
        // Localhost proxy works fine
        url = endpoint;
    } else {
        // Bypass Firebase Hosting proxy (60s limit) by going direct to Cloud Run
        const cleanEndpoint = endpoint.startsWith('/') ? endpoint.substring(1) : endpoint;
        url = `${CLOUD_RUN_URL}/${cleanEndpoint}`;
    }

    // Add timestamp to GET to prevent caching
    if (method === 'GET') {
        url += (url.includes('?') ? '&' : '?') + 't=' + new Date().getTime();
    }

    console.log(`DEBUG: apiCall requesting ${url}`, method, body);

    const response = await fetch(url, options);
    if (!response.ok) {
        const text = await response.text();
        throw new Error(`HTTP ${response.status}: ${text.substring(0, 100)}...`);
    }
    return response;
}


async function startGame(vsCpu) {
    if (gameState && !confirm("新しい対局を始めますか？")) return;

    try {
        const response = await apiCall('/api/reset', 'POST', { vs_ai: vsCpu });
        const result = await response.json();

        selected = null;
        updateGameState(result.game_state);

    } catch (e) {
        alert("Start Game Error: " + e.message);
    }
}

// Helper to toggle thinking indicator
// Helper to toggle thinking indicator
function setThinking(turn, visible, modelName = null) {
    const sEl = document.getElementById('sente-thinking');
    const gEl = document.getElementById('gote-thinking');
    if (!sEl || !gEl) return;

    // Clear both first if visible is false, or if strictly setting one
    if (!visible) {
        sEl.style.display = 'none';
        gEl.style.display = 'none';
        return;
    }

    const text = modelName ? `(${modelName} 考え中...)` : "(考え中...)";

    if (turn === SENTE) {
        sEl.textContent = text;
        sEl.style.display = 'inline';
        gEl.style.display = 'none';
    } else {
        gEl.textContent = text;
        sEl.style.display = 'none';
        gEl.style.display = 'inline';
    }
}

async function cpuMove() {
    if (!gameState || (!gameState.vs_ai && !gameState.ai_vs_ai_mode)) return;

    setThinking(GOTE, true, 'CPU');
    try {
        const response = await apiCall('/api/cpu', 'POST', {
            sfen: gameState.sfen,
            vs_ai: gameState.vs_ai,
            ai_vs_ai: gameState.ai_vs_ai_mode,
            sente_model: gSenteModel,
            gote_model: gGoteModel
        });
        const result = await response.json();
        if (result.status === 'ok') {
            updateGameState(result.game_state);
            // Log CPU Move
            if (result.move_str_ja) {
                logMove(result.move_count, 'CPU', result.move_str_ja, result.reasoning);
            }
        } else {
            console.error(result.message);
        }
    } catch (e) {
        console.error("CPU Move Error", e);
    } finally {
        setThinking(GOTE, false);
    }
}

function render() {
    if (!gameState) return;
    renderBoard();
    renderHands();
    renderStatus();
    if (gameState.sfen) {
        // Just for display/copy
        const sfenEl = document.getElementById('sfen-entry');
        if (sfenEl) sfenEl.value = `あなたは最強の将棋AIです。この局面の次の一手は？\n${gameState.sfen}`;
    }
}

function copySfen() {
    const copyText = document.getElementById("sfen-entry");
    if (!copyText) return;
    copyText.select();
    navigator.clipboard.writeText(copyText.value).then(() => {
        alert("コピーしました！");
    });
}

function renderBoard() {
    const boardEl = document.getElementById('board');
    if (!boardEl) return;
    boardEl.innerHTML = '';

    // Top Coordinates (9 to 1)
    for (let i = 9; i >= 1; i--) {
        const coord = document.createElement('div');
        coord.className = 'coord';
        coord.textContent = i;
        boardEl.appendChild(coord);
    }
    const emptyCorner = document.createElement('div');
    boardEl.appendChild(emptyCorner);

    const kanjiNumbers = ["一", "二", "三", "四", "五", "六", "七", "八", "九"];

    for (let y = 0; y < BOARD_SIZE; y++) {
        for (let x = 0; x < BOARD_SIZE; x++) {
            const cell = document.createElement('div');
            cell.className = 'cell';
            cell.dataset.x = x;
            cell.dataset.y = y;
            cell.onclick = () => onBoardClick(x, y);

            const pieceData = gameState.board[y][x];
            if (pieceData) {
                const piece = document.createElement('div');
                piece.className = 'piece';
                piece.textContent = pieceData.name;
                if (pieceData.owner === GOTE) {
                    piece.classList.add('gote');
                }

                if (selected && selected.type === 'board' && selected.pos[0] === x && selected.pos[1] === y) {
                    piece.style.color = 'red';
                }

                // Highlight last moved piece (Sente or Gote)
                if (gameState.last_move) {
                    const [lx, ly] = gameState.last_move.to;
                    if (lx === x && ly === y) {
                        piece.style.color = 'red';
                        piece.style.fontWeight = 'bold';
                    }
                }

                cell.appendChild(piece);
            }

            boardEl.appendChild(cell);
        }

        const rowCoord = document.createElement('div');
        rowCoord.className = 'coord';
        rowCoord.textContent = kanjiNumbers[y];
        boardEl.appendChild(rowCoord);
    }
}

function renderHands() {
    const senteHandEl = document.getElementById('sente-hand-pieces');
    const goteHandEl = document.getElementById('gote-hand-pieces');
    if (!senteHandEl || !goteHandEl) return;

    senteHandEl.innerHTML = '';
    goteHandEl.innerHTML = '';

    // Sente Hand
    for (const [name, count] of Object.entries(gameState.hands[SENTE])) {
        if (count > 0) {
            const piece = document.createElement('div');
            piece.className = 'hand-piece';
            piece.textContent = `${name}:${count}`;
            if (selected && selected.type === 'hand' && selected.name === name) {
                piece.classList.add('selected');
            }
            piece.onclick = () => onHandClick(name);
            senteHandEl.appendChild(piece);
        }
    }

    // Gote Hand
    for (const [name, count] of Object.entries(gameState.hands[GOTE])) {
        if (count > 0) {
            const piece = document.createElement('div');
            piece.className = 'hand-piece';
            const inner = document.createElement('div');
            inner.textContent = `${name}:${count}`;
            inner.style.transform = 'rotate(180deg)';
            piece.appendChild(inner);
            goteHandEl.appendChild(piece);
        }
    }
}

function renderStatus() {
    const indicator = document.getElementById('turn-indicator');
    if (!indicator) return;

    if (gameState.game_over) {
        indicator.textContent = "勝負あり - 新しい対局を選んでください";
    } else {
        indicator.textContent = gameState.turn === SENTE ? "手番: 先手 (下)" : "手番: 後手 (上)";
    }
}

function onHandClick(name) {
    if (gameState.game_over) return;
    if (gameState.turn !== SENTE && !gameState.ai_vs_ai_mode) return;

    // In AI/Mixed mode, prevent human from moving if it's not their turn (i.e. model is not 'human')
    if (gameState.ai_vs_ai_mode) {
        const currentModel = (gameState.turn === SENTE) ? gSenteModel : gGoteModel;
        if (currentModel !== 'human') return;
    }

    if (selected && selected.type === 'hand' && selected.name === name) {
        selected = null;
    } else {
        selected = { type: 'hand', name: name };
    }
    render();
}

async function onBoardClick(x, y) {
    if (gameState.game_over) return;
    if (gameState.turn !== SENTE && !gameState.ai_vs_ai_mode) return;

    // In AI/Mixed mode, prevent human from moving if it's not their turn
    if (gameState.ai_vs_ai_mode) {
        const currentModel = (gameState.turn === SENTE) ? gSenteModel : gGoteModel;
        if (currentModel !== 'human') return;
    }

    if (selected) {
        if (selected.type === 'board') {
            // Move piece
            const from = selected.pos;
            const to = [x, y];

            // Check promotion locally first (optional UI hint)
            const piece = gameState.board[from[1]][from[0]];
            const isPromoteZone = (dir) => (dir === SENTE && y <= 2) || (dir === GOTE && y >= 6);

            // Re-implement check_promote API call logic
            let promote = false;
            if (piece) {
                // Quick client check or API check
                const response = await apiCall('/api/check_promote', 'POST', {
                    sfen: gameState.sfen,
                    name: piece.name,
                    from: from,
                    to: to
                });
                const res = await response.json();
                if (res.can_promote) {
                    promote = confirm("成りますか？");
                }
            }

            makeMove({
                type: 'move',
                from: from,
                to: to,
                promote: promote
            });
            selected = null;

        } else if (selected.type === 'hand') {
            // Drop piece
            makeMove({
                type: 'drop',
                name: selected.name,
                to: [x, y]
            });
            selected = null;
        }
        render();
    } else {
        // Select piece
        const piece = gameState.board[y][x];
        if (piece && piece.owner === gameState.turn) {
            selected = { type: 'board', pos: [x, y] };
            render();
        }
    }
}

async function makeMove(moveData) {
    try {
        const payload = { ...moveData, sfen: gameState.sfen, vs_ai: gameState.vs_ai, ai_vs_ai: gameState.ai_vs_ai_mode, sente_model: gSenteModel, gote_model: gGoteModel };
        const response = await apiCall('/api/move', 'POST', payload);
        const result = await response.json();

        if (result.status === 'ok') {
            updateGameState(result.game_state);

            // Log Human Move
            // If makeMove was successful and we have move_str_ja, log it.
            // Human turn is implicitly handled here.
            // But we need to check if it WAS a human turn? 
            // Yes, makeMove is called by UI interaction.
            if (result.move_str_ja) {
                logMove(result.move_count, '人間', result.move_str_ja);
            }

            // Trigger CPU or AI vs AI Loop
            if (gameState.ai_vs_ai_mode && !gameState.game_over) {
                setTimeout(processAiVsAi, 500);
            } else if (gameState.vs_ai && !gameState.game_over && gameState.turn === GOTE) {
                setTimeout(cpuMove, 500);
            }
        } else {
            console.error(result.message);
            alert("Move Error: " + result.message);
        }
    } catch (e) {
        alert("Server Error: " + e.message);
    }
}



// AI Settings UI Helpers
function showAiSettings() {
    const el = document.getElementById('ai-settings');
    if (el) el.style.display = 'block';
}

function hideAiSettings() {
    const el = document.getElementById('ai-settings');
    if (el) el.style.display = 'none';
}

// AI vs AI Loop
async function startAiVsAiMatch() {
    console.log("DEBUG: startAiVsAiMatch clicked");
    hideAiSettings();
    const sModel = document.getElementById('sente-model').value;
    const gModel = document.getElementById('gote-model').value;

    gSenteModel = sModel;
    gGoteModel = gModel;

    console.log("DEBUG: Selected Models:", sModel, gModel);

    // Check if Human vs Human (Legacy Mode)
    if (sModel === 'human' && gModel === 'human') {
        console.log("DEBUG: Human vs Human detected.");
        try {
            const response = await apiCall('/api/reset', 'POST', {
                vs_ai: false,
                ai_vs_ai: false
            });
            const result = await response.json();
            updateGameState(result.game_state);
        } catch (e) {
            console.error("Game Start Error", e);
            alert("Start Failed");
        }
        return;
    }

    // AI or Mixed Mode
    try {
        console.log("DEBUG: Calling /api/reset for AI/Mixed Mode...");
        const response = await apiCall('/api/reset', 'POST', {
            vs_ai: false, // We use ai_vs_ai flags for flexible turns
            ai_vs_ai: true,
            sente_model: sModel,
            gote_model: gModel
        });
        const result = await response.json();
        console.log("DEBUG: Reset Response:", result);

        updateGameState(result.game_state);

        console.log("DEBUG: Starting AI Loop...");
        setTimeout(processAiVsAi, 1000); // Start loop

    } catch (e) {
        console.error("AI vs AI Start Error", e);
        alert("Failed to start AI match");
    }
}

async function processAiVsAi() {
    if (!gameState || !gameState.ai_vs_ai_mode || gameState.game_over) {
        // console.log("DEBUG: Stopping AI Loop. mode:", gameState.ai_vs_ai_mode, "over:", gameState.game_over);
        return;
    }

    const currentModel = (gameState.turn === SENTE) ? gSenteModel : gGoteModel;

    // 1. Human Turn -> Wait (Return)
    if (currentModel === 'human') {
        console.log("DEBUG: Human turn. Waiting for input.");
        return;
    }

    // 2. CPU Turn -> Call CPU (Reusing cpuMove logic somewhat or just direct API)
    if (currentModel === 'cpu') {
        console.log("DEBUG: CPU Turn");
        await cpuMove();
        // cpuMove logic calls updateGameState.
        // We need to ensure the loop continues after CPU moves.
        // cpuMove is async and updates state. We should schedule next poll.
        if (!gameState.game_over) {
            setTimeout(processAiVsAi, 1000);
        }
        return;
    }

    // 3. LLM Turn
    setThinking(gameState.turn, true, currentModel);
    try {
        console.log("DEBUG: Requesting LLM Move with Models:", gSenteModel, gGoteModel);
        const response = await apiCall('/api/llm_move', 'POST', {
            sfen: gameState.sfen,
            turn: gameState.turn,
            sente_model: gSenteModel,
            gote_model: gGoteModel,
            vs_ai: gameState.vs_ai,
            ai_vs_ai: gameState.ai_vs_ai_mode
        });
        const result = await response.json();

        console.log("DEBUG: LLM Move Result:", result);

        if (result.status === 'ok') {
            updateGameState(result.game_state);

            // Show Reasoning
            if (result.reasoning || result.move_str_ja) {
                const mStr = result.move_str_ja || result.usi || "";
                const model = result.model || "AI";
                logMove(result.move_count, model, mStr, result.reasoning);
            }

            // Loop continue
            if (!result.game_over && gameState.ai_vs_ai_mode) {
                setTimeout(processAiVsAi, 1000);
            }
        } else {
            console.error("LLM Error:", result.message, result.last_error);
        }

    } catch (e) {
        console.error("AI processing error", e);
    } finally {
        setThinking(gameState.turn, false);
    }
}


// Initialization
window.onload = () => {
    loadLocalState();
};
