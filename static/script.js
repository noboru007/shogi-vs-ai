const BOARD_SIZE = 9;
const SENTE = 1;
const GOTE = -1;

console.log("SCRIPT LOADED vdebug3");

let gameState = null;
let selected = null; // {type: 'board', pos: [x, y]} or {type: 'hand', name: 'PieceName'}
let gSenteModel = "gemini-2.5-pro";
let gGoteModel = "gemini-2.5-pro";

// Session Management (Local Only)
// We don't really need session ID for server anymore, but keep for headers if needed
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

async function apiCall(endpoint, method = 'GET', body = null) {
    const headers = {
        'X-Session-ID': getSessionId()
    };
    if (body) {
        headers['Content-Type'] = 'application/json';
    }

    const options = { method, headers };
    if (body) options.body = JSON.stringify(body);

    // Add timestamp to GET to prevent caching
    let url = endpoint;
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

// fetchGameState Removed - Stateless

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

async function cpuMove() {
    if (!gameState || !gameState.vs_ai) return;

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
        } else {
            console.error(result.message);
        }
    } catch (e) {
        console.error("CPU Move Error", e);
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

                // Highlight Gote's last moved piece
                if (gameState.last_move && gameState.last_move.owner === GOTE) {
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

    if (selected && selected.type === 'hand' && selected.name === name) {
        selected = null;
    } else {
        selected = { type: 'hand', name: name };
    }
    render();
}

async function onBoardClick(x, y) {
    if (gameState.game_over) return;
    if (gameState.turn !== SENTE && gameState.vs_ai) return;

    // If nothing selected
    if (!selected) {
        const piece = gameState.board[y][x];
        if (piece && piece.owner === gameState.turn) {
            selected = { type: 'board', pos: [x, y] };
            render();
        }
        return;
    }

    // If hand piece selected -> Drop
    if (selected.type === 'hand') {
        const piece = gameState.board[y][x];
        if (!piece) {
            // Try drop
            await makeMove({
                type: 'drop',
                name: selected.name,
                to: [x, y],
                sfen: gameState.sfen // STATELESS REQUIREMENT
            });
        } else {
            // Change selection if clicking own piece
            if (piece.owner === gameState.turn) {
                selected = { type: 'board', pos: [x, y] };
                render();
            } else {
                selected = null;
                render();
            }
        }
        return;
    }

    // If board piece selected -> Move
    if (selected.type === 'board') {
        const [sx, sy] = selected.pos;
        if (sx === x && sy === y) {
            selected = null;
            render();
            return;
        }

        const piece = gameState.board[y][x];
        if (piece && piece.owner === gameState.turn) {
            // Change selection
            selected = { type: 'board', pos: [x, y] };
            render();
            return;
        }

        // Attempt move
        const sourcePiece = gameState.board[sy][sx];

        try {
            const response = await apiCall('/api/check_promote', 'POST', {
                from: [sx, sy],
                to: [x, y],
                name: sourcePiece.name,
                sfen: gameState.sfen // STATELESS REQUIREMENT
            });
            const check = await response.json();

            if (check.can_promote) {
                showPromotionModal(sx, sy, x, y);
            } else {
                await makeMove({
                    type: 'move',
                    from: [sx, sy],
                    to: [x, y],
                    promote: false,
                    sfen: gameState.sfen // STATELESS REQUIREMENT
                });
            }
        } catch (e) {
            console.error("Move Check Error", e);
        }
    }
}

function showPromotionModal(sx, sy, ex, ey) {
    let modal = document.getElementById('promotion-modal');
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'promotion-modal';
        styleModal(modal); // Helper below or inline
        // ... simplified creation for brevity ...
        // Reusing existing DOM if possible or creating simple one
        document.body.appendChild(modal);
        // Assuming modal innerHTML is safer to rebuild
    }

    // Quick rebuild to ensure clean event listeners
    modal.innerHTML = '';

    const content = document.createElement('div');
    Object.assign(content.style, {
        backgroundColor: '#fff', padding: '20px', borderRadius: '5px',
        textAlign: 'center', boxShadow: '0 2px 10px rgba(0,0,0,0.2)'
    });

    const text = document.createElement('p');
    text.textContent = '成りますか？';

    const btnContainer = document.createElement('div');
    btnContainer.style.display = 'flex';
    btnContainer.style.gap = '10px';
    btnContainer.style.justifyContent = 'center';

    const yesBtn = document.createElement('button');
    yesBtn.textContent = 'はい';
    yesBtn.onclick = async () => {
        modal.style.display = 'none';
        await makeMove({
            type: 'move', from: [sx, sy], to: [ex, ey], promote: true,
            sfen: gameState.sfen
        });
    };

    const noBtn = document.createElement('button');
    noBtn.textContent = 'いいえ';
    noBtn.onclick = async () => {
        modal.style.display = 'none';
        await makeMove({
            type: 'move', from: [sx, sy], to: [ex, ey], promote: false,
            sfen: gameState.sfen
        });
    };

    btnContainer.append(yesBtn, noBtn);
    content.append(text, btnContainer);
    modal.append(content);

    modal.style.display = 'flex';
}

function styleModal(modal) {
    Object.assign(modal.style, {
        position: 'fixed', top: '0', left: '0', width: '100%', height: '100%',
        backgroundColor: 'rgba(0,0,0,0.5)', display: 'none',
        justifyContent: 'center', alignItems: 'center', zIndex: '1000'
    });
}

async function makeMove(moveData) {
    try {
        // Inject stateless flags
        if (gameState) {
            moveData.vs_ai = gameState.vs_ai;
            moveData.ai_vs_ai = gameState.ai_vs_ai_mode;
            moveData.sente_model = gSenteModel;
            moveData.gote_model = gGoteModel;
        }

        const response = await apiCall('/api/move', 'POST', moveData);

        const result = await response.json();
        if (result.status === 'ok') {
            selected = null;
            updateGameState(result.game_state);

            // Trigger CPU logic IF vs_ai
            // But wait, updateGameState already renders.
            if (gameState.vs_ai && gameState.turn === GOTE && !gameState.game_over) {
                setTimeout(cpuMove, 300);
            }
        } else {
            alert(result.message);
            selected = null;
            render();
        }
    } catch (e) {
        console.error("Make Move Error", e);
        alert("Move failed: " + e.message);
    }
}


function showAiSettings() {
    console.log("DEBUG: showAiSettings clicked");
    const el = document.getElementById('ai-settings');
    if (el) {
        el.style.display = 'block';
        console.log("DEBUG: ai-settings display set to block");
    } else {
        console.error("DEBUG: ai-settings element not found");
    }
}

async function startAiVsAiMatch() {
    console.log("DEBUG: startAiVsAiMatch clicked");
    try {
        const senteModelEl = document.getElementById('sente-model');
        const goteModelEl = document.getElementById('gote-model');

        if (!senteModelEl || !goteModelEl) {
            throw new Error("Model select elements not found!");
        }

        const senteModel = senteModelEl.value;
        const goteModel = goteModelEl.value;

        console.log("DEBUG: Selected Models:", senteModel, goteModel);

        gSenteModel = senteModel;
        gGoteModel = goteModel;

        const settingsEl = document.getElementById('ai-settings');
        if (settingsEl) settingsEl.style.display = 'none';

        console.log("DEBUG: Calling /api/reset...");
        const response = await apiCall('/api/reset', 'POST', {
            vs_ai: false,
            ai_vs_ai: true,
            sente_model: senteModel,
            gote_model: goteModel
        });
        const result = await response.json();
        console.log("DEBUG: Reset Response:", result);

        selected = null;
        updateGameState(result.game_state);

        // Start Loop
        console.log("DEBUG: Starting AI Loop...");
        processAiVsAi();

    } catch (e) {
        console.error("AI Match Start Error (Caught)", e);
        alert("Failed to start match: " + e.message);
    }
}

async function processAiVsAi() {
    if (!gameState || gameState.game_over) return;
    if (!gameState.ai_vs_ai_mode) return; // Safety

    // Safety delay
    await new Promise(r => setTimeout(r, 1000));

    // Request LLM Move
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
        if (result.status !== 'ok') {
            console.error("LLM Error:", result.message);
            // Retry could happen here?
            return;
        }

        const usi = result.usi;
        console.log("LLM Move Executed:", usi, result.move);

        if (result.game_state) {
            console.log("DEBUG: Received SFEN:", result.game_state.sfen);
            console.log("DEBUG: Current Local SFEN:", gameState.sfen);

            updateGameState(result.game_state);

            console.log("DEBUG: Updated Local SFEN:", gameState.sfen);

            // Continue loop if not game over
            if (!gameState.game_over) {
                processAiVsAi(); // Recursion
            } else {
                setTimeout(() => alert("Game Over! Winner: " + result.winner), 500);
            }
        }

    } catch (e) {
        console.error("AI processing error", e);
    }
}

// Initial Load logic
// Must happen after DOM ready ideally, but script.js is likely at end of body or deferred.
// Try load local state, if fail/empty, start new game (vs AI default)
if (!loadLocalState()) {
    // Start default game
    startGame(true);
}
