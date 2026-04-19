const BOARD_SIZE = 9;
const SENTE = 1;
const GOTE = -1;

// localStorage keys (single source of truth)
const STORAGE_KEYS = {
    session: 'shogi_session_id',
    state: 'shogi_state',
    aiSettings: 'shogi_ai_settings'
};

// Single source of truth for AI model options
const MODEL_OPTIONS = [
    { value: "gemini-3.1-pro-preview-high", label: "Gemini 3.1 Pro Preview High" },
    { value: "gemini-3.1-pro-preview-medium", label: "Gemini 3.1 Pro Preview Medium" },
    { value: "gemini-3-pro-preview-high", label: "Gemini 3 Pro Preview High" },
    { value: "gemini-3-flash-preview", label: "Gemini 3 Flash Preview" },
    { value: "gemini-3-flash-preview-high", label: "Gemini 3 Flash Preview High" },
    { value: "gpt-5.4", label: "GPT-5.4" },
    { value: "gpt-5.4-high", label: "GPT-5.4 (High Reasoning)" },
    { value: "gpt-5.3-codex", label: "GPT-5.3 Codex" },
    { value: "gpt-5.3-codex-high", label: "GPT-5.3 Codex (High Reasoning)" },
    { value: "gpt-5.2", label: "GPT-5.2" },
    { value: "gpt-5.2-high", label: "GPT-5.2 (High Reasoning)" },
    { value: "claude-opus-4-7", label: "Claude Opus 4.7" },
    { value: "claude-opus-4-7-medium", label: "Claude Opus 4.7 (Adaptive)" },
    { value: "claude-opus-4-6", label: "Claude Opus 4.6" },
    { value: "claude-opus-4-6-medium", label: "Claude Opus 4.6 (Adaptive)" },
    { value: "claude-sonnet-4-6", label: "Claude Sonnet 4.6" },
    { value: "claude-sonnet-4-6-medium", label: "Claude Sonnet 4.6 (Adaptive)" },
    { value: "human", label: "人間" },
    { value: "cpu", label: "3手先まで読むCPU" }
];

// Populate a <select> element with MODEL_OPTIONS
function populateModelSelect(selectId, defaultValue) {
    const sel = document.getElementById(selectId);
    if (!sel) return;
    sel.innerHTML = "";
    MODEL_OPTIONS.forEach(opt => {
        const o = document.createElement("option");
        o.value = opt.value;
        o.textContent = opt.label;
        if (opt.value === defaultValue) o.selected = true;
        sel.appendChild(o);
    });
}

console.log("SCRIPT LOADED vdebug3");

// Helper to log moves
function logMove(moveCount, modelName, moveStr, reasoning = null, isFallback = false) {
    const rArea = document.getElementById('reasoning-area');
    if (!rArea) return;

    // Always show if it's hidden
    rArea.style.display = 'block';

    const entry = document.createElement('div');
    entry.classList.add('log-entry');

    if (isFallback) {
        entry.classList.add('log-fallback');
    }

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

    // Append SFEN
    if (gameState && gameState.sfen) {
        const sfenDiv = document.createElement('div');
        sfenDiv.classList.add('sfen-text');
        sfenDiv.style.fontSize = "0.8em";
        sfenDiv.style.marginTop = "2px";
        if (!isFallback) {
            sfenDiv.style.color = "#777";
        }
        sfenDiv.textContent = `SFEN: ${gameState.sfen}`;
        entry.appendChild(sfenDiv);
    }

    rArea.insertBefore(entry, rArea.firstChild);
}

let gameState = null;
let selected = null; // {type: 'board', pos: [x, y]} or {type: 'hand', name: 'PieceName'}
let pendingMove = null; // Store move waiting for promotion confirmation
let gSenteModel = "gemini-2.5-pro";
let gGoteModel = "gemini-2.5-pro";
let gMaxRetries = 2;
let gInstructionType = "medium";
let gTtsEnabled = false;
let gTtsSaveFile = false;
let gVideoMode = false;
let gMatchPrefix = ""; // yyyymmdd_hhmmss_Sente_vs_Gote
let gMatchMoves = []; // Metadata for each move (video mode)
let currentMatchId = null; // To prevent stale AI responses from overwriting new game

// Save AI settings to localStorage for refresh recovery
function saveAiSettings() {
    const settings = {
        currentMatchId: currentMatchId,
        senteModel: gSenteModel,
        goteModel: gGoteModel,
        maxRetries: gMaxRetries,
        instructionType: gInstructionType,
        ttsEnabled: gTtsEnabled,
        ttsSaveFile: gTtsSaveFile,
        videoMode: gVideoMode,
        matchPrefix: gMatchPrefix,
        matchMoves: gMatchMoves
    };
    localStorage.setItem(STORAGE_KEYS.aiSettings, JSON.stringify(settings));
}

// Session Management (Local Only)
function getSessionId() {
    let sid = localStorage.getItem(STORAGE_KEYS.session);
    if (!sid) {
        sid = 'sess_' + Math.random().toString(36).substr(2, 9);
        localStorage.setItem(STORAGE_KEYS.session, sid);
    }
    return sid;
}

// Client-Side State Helpers

// Sanitize game state to fix potential browser compatibility issues
function sanitizeGameState(state) {
    if (!state) return null;

    try {
        // Ensure board is a proper 9x9 array
        if (!state.board || !Array.isArray(state.board) || state.board.length !== 9) {
            console.warn("Invalid board structure, resetting");
            return null;
        }

        // Verify each row is also a proper array of 9 elements
        for (let y = 0; y < 9; y++) {
            if (!Array.isArray(state.board[y]) || state.board[y].length !== 9) {
                console.warn(`Invalid board row ${y}, resetting`);
                return null;
            }
        }

        // Normalize hands keys (convert string keys to integers)
        if (state.hands) {
            const normalizedHands = {};
            for (const key of Object.keys(state.hands)) {
                const intKey = parseInt(key, 10);
                if (!isNaN(intKey) && (intKey === 1 || intKey === -1)) {
                    normalizedHands[intKey] = state.hands[key] || {};
                }
            }
            // Ensure both SENTE(1) and GOTE(-1) exist
            if (!normalizedHands[1]) normalizedHands[1] = {};
            if (!normalizedHands[-1]) normalizedHands[-1] = {};
            state.hands = normalizedHands;
        } else {
            state.hands = { 1: {}, "-1": {} };
        }

        // Ensure turn is integer
        if (state.turn !== undefined) {
            state.turn = parseInt(state.turn, 10);
            if (state.turn !== 1 && state.turn !== -1) {
                state.turn = 1; // Default to SENTE
            }
        }

        return state;
    } catch (e) {
        console.error("State sanitization error:", e);
        return null;
    }
}

function updateGameState(newState) {
    if (!newState) return;

    // Sanitize before storing
    const sanitized = sanitizeGameState(newState);
    if (!sanitized) {
        console.error("Failed to sanitize game state, ignoring update");
        return;
    }

    gameState = sanitized;
    localStorage.setItem(STORAGE_KEYS.state, JSON.stringify(gameState));

    // Sync models if present (Persistence fix)
    if (gameState.sente_model) gSenteModel = gameState.sente_model;
    if (gameState.gote_model) gGoteModel = gameState.gote_model;

    render();
}

function loadLocalState() {
    const saved = localStorage.getItem(STORAGE_KEYS.state);
    if (saved) {
        try {
            const parsed = JSON.parse(saved);
            const sanitized = sanitizeGameState(parsed);
            if (sanitized) {
                updateGameState(sanitized);
                return true;
            } else {
                console.warn("Clearing corrupted local storage");
                localStorage.removeItem(STORAGE_KEYS.state);
                return false;
            }
        } catch (e) {
            console.error("Local state parse error", e);
            localStorage.removeItem(STORAGE_KEYS.state);
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
        url = endpoint;
    } else {
        const cleanEndpoint = endpoint.startsWith('/') ? endpoint.substring(1) : endpoint;
        url = `${CLOUD_RUN_URL}/${cleanEndpoint}`;
    }

    if (method === 'GET') {
        url += (url.includes('?') ? '&' : '?') + 't=' + new Date().getTime();
    }

    // Retry Logic (Max 3 attempts)
    let attempts = 0;
    const maxAttempts = 3;

    while (attempts < maxAttempts) {
        try {
            console.log(`DEBUG: apiCall requesting ${url} (Attempt ${attempts + 1})`, method, body);
            const response = await fetch(url, options);
            if (!response.ok) {
                // If 5xx error, might be transient. If 4xx, probably permanent.
                // We retry 5xx.
                if (response.status >= 500) {
                    const text = await response.text();
                    console.warn(`Server Error ${response.status}: ${text}. Retrying...`);
                    attempts++;
                    await new Promise(r => setTimeout(r, 1000 * attempts)); // Backoff
                    continue;
                }
                const text = await response.text();
                throw new Error(`HTTP ${response.status}: ${text.substring(0, 100)}...`);
            }
            return response;
        } catch (e) {
            console.error(`Fetch Error (Attempt ${attempts + 1}):`, e);
            attempts++;
            if (attempts >= maxAttempts) throw e;
            await new Promise(r => setTimeout(r, 1000 * attempts));
        }
    }
}


async function startGame(vsCpu) {
    if (gameState && !confirm("新しい対局を始めますか？")) return;

    try {
        const response = await apiCall('/api/reset', 'POST', { vs_ai: vsCpu });
        const result = await response.json();

        selected = null;
        pendingMove = null;
        currentMatchId = Date.now().toString(); // New Match ID
        saveAiSettings();

        // Clear Game Over Modal
        const goModal = document.getElementById('game-over-modal');
        if (goModal) goModal.style.display = 'none';

        updateGameState(result.game_state);

    } catch (e) {
        showMessage("Start Game Error: " + e.message);
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

    // Capture match ID called with
    const matchId = currentMatchId;

    const turn = gameState.turn;
    setThinking(turn, true, 'CPU');
    try {
        const response = await apiCall('/api/cpu', 'POST', {
            sfen: gameState.sfen,
            vs_ai: gameState.vs_ai,
            ai_vs_ai: gameState.ai_vs_ai_mode,
            sente_model: gSenteModel,
            gote_model: gGoteModel
        });

        // Stale Check
        if (matchId !== currentMatchId) {
            console.log("DEBUG: Ignoring stale CPU response", matchId, currentMatchId);
            return;
        }

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
        setThinking(turn, false);
    }
}

function render() {
    if (!gameState) return;
    renderBoard();
    renderHands();
    renderStatus();
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
        const alphabet = String.fromCharCode(97 + y); // a, b, c...
        rowCoord.innerHTML = `${kanjiNumbers[y]}<br>${alphabet}`;
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
            if (selected && selected.type === 'hand' && selected.name === name && gameState.turn === SENTE) {
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
            if (selected && selected.type === 'hand' && selected.name === name && gameState.turn === GOTE) {
                piece.classList.add('selected');
            }
            piece.onclick = () => onHandClick(name);
            goteHandEl.appendChild(piece);
        }
    }
}

function renderStatus() {
    const indicator = document.getElementById('turn-indicator');
    if (!indicator) return;

    if (gameState.game_over) {
        indicator.textContent = "勝負あり - 新しい対局を選んでください";
        // Show Game Over Modal
        const modal = document.getElementById('game-over-modal');
        if (modal && modal.style.display !== 'flex') {
            modal.style.display = 'flex';

            // Show download button if TTS was enabled and files exist
            if (gTtsSaveFile && currentMatchId) {
                getTtsFilesForMatch(currentMatchId).then(files => {
                    const btn = document.getElementById('download-audio-btn');
                    if (btn && files && files.length > 0) {
                        btn.style.display = 'inline-block';
                    }
                }).catch(e => console.error('Error checking TTS files:', e));
            }
        }
    } else {
        indicator.textContent = gameState.turn === SENTE ? "手番: 先手 (下)" : "手番: 後手 (上)";
    }
}

// 現在手番でユーザー操作が可能かを判定（vs AI / AI vs AI / 人間対人間を統一扱い）
function canHumanPlay() {
    if (!gameState || gameState.game_over) return false;
    if (gameState.vs_ai && gameState.turn !== SENTE) return false;
    if (gameState.ai_vs_ai_mode) {
        const currentModel = (gameState.turn === SENTE) ? gSenteModel : gGoteModel;
        if (currentModel !== 'human') return false;
    }
    return true;
}

function onHandClick(name) {
    if (!canHumanPlay()) return;

    // 自分の持駒だけを選択可能にする（相手の持駒はクリックしても無効）
    const myHand = gameState.hands[gameState.turn];
    if (!myHand || !(name in myHand) || myHand[name] <= 0) return;

    if (selected && selected.type === 'hand' && selected.name === name) {
        selected = null;
    } else {
        selected = { type: 'hand', name: name };
    }
    render();
}

async function onBoardClick(x, y) {
    if (!canHumanPlay()) return;

    if (selected) {
        if (selected.type === 'board') {
            // Move piece
            const from = selected.pos;
            const to = [x, y];

            // Check promotion locally first (optional UI hint)
            const piece = gameState.board[from[1]][from[0]];
            const isPromoteZone = (dir) => (dir === SENTE && y <= 2) || (dir === GOTE && y >= 6);

            // Re-implement check_promote API call logic
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
                    pendingMove = { type: 'move', from: from, to: to };
                    document.getElementById('promotion-modal').style.display = 'flex';
                    return;
                }
            }

            makeMove({
                type: 'move',
                from: from,
                to: to,
                promote: false
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

            if (result.forfeit_reason) {
                const msgEl = document.getElementById('game-over-message');
                if (msgEl) msgEl.textContent = result.forfeit_reason;
                logMove(result.move_count, 'システム', result.forfeit_reason);
                return;
            }

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
            showMessage("Move Error: " + result.message);
        }
    } catch (e) {
        showMessage("Server Error: " + e.message);
    }
}



// Promotion Modal Handler
function resolvePromotion(shouldPromote) {
    document.getElementById('promotion-modal').style.display = 'none';
    if (pendingMove) {
        makeMove({
            ...pendingMove,
            promote: shouldPromote
        });
        pendingMove = null;
        selected = null;
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

function showRetryInfo() {
    const modal = document.getElementById('retry-info-modal');
    if (modal) {
        modal.style.display = 'flex';
    }
}

function closeRetryInfo(event) {
    const modal = document.getElementById('retry-info-modal');
    if (modal) {
        modal.style.display = 'none';
    }
}

// Generic Message Modal Helpers
function showMessage(text) {
    const modal = document.getElementById('message-modal');
    const msgText = document.getElementById('message-text');
    if (modal && msgText) {
        msgText.textContent = text;
        modal.style.display = 'flex';
    }
}

function closeMessage(event) {
    const modal = document.getElementById('message-modal');
    if (modal) {
        modal.style.display = 'none';
    }
}

// ========== IndexedDB TTS Management ==========
let ttsDB = null;

async function initTtsDB() {
    return new Promise((resolve, reject) => {
        const request = indexedDB.open('ShogiTTS', 1);

        request.onerror = () => reject(request.error);
        request.onsuccess = () => {
            ttsDB = request.result;
            resolve(ttsDB);
        };

        request.onupgradeneeded = (event) => {
            const db = event.target.result;
            if (!db.objectStoreNames.contains('audioFiles')) {
                const objectStore = db.createObjectStore('audioFiles', { keyPath: 'id' });
                objectStore.createIndex('matchId', 'matchId', { unique: false });
            }
        };
    });
}

async function saveTtsToIndexedDB(matchId, moveCount, filename, base64Audio) {
    if (!ttsDB) await initTtsDB();

    return new Promise((resolve, reject) => {
        const transaction = ttsDB.transaction(['audioFiles'], 'readwrite');
        const objectStore = transaction.objectStore('audioFiles');

        const data = {
            id: `${matchId}_${String(moveCount).padStart(3, '0')}`,
            matchId: matchId,
            moveCount: moveCount,
            filename: filename,
            audioData: base64Audio,
            timestamp: Date.now()
        };

        const request = objectStore.put(data);
        request.onsuccess = () => resolve();
        request.onerror = () => reject(request.error);
    });
}

async function getTtsFilesForMatch(matchId) {
    if (!ttsDB) await initTtsDB();

    return new Promise((resolve, reject) => {
        const transaction = ttsDB.transaction(['audioFiles'], 'readonly');
        const objectStore = transaction.objectStore('audioFiles');
        const index = objectStore.index('matchId');
        const request = index.getAll(matchId);

        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
    });
}

async function clearTtsForMatch(matchId) {
    if (!ttsDB) await initTtsDB();

    return new Promise((resolve, reject) => {
        const transaction = ttsDB.transaction(['audioFiles'], 'readwrite');
        const objectStore = transaction.objectStore('audioFiles');
        const index = objectStore.index('matchId');
        const request = index.openCursor(IDBKeyRange.only(matchId));

        request.onsuccess = (event) => {
            const cursor = event.target.result;
            if (cursor) {
                cursor.delete();
                cursor.continue();
            } else {
                resolve();
            }
        };
        request.onerror = () => reject(request.error);
    });
}

async function downloadMatchAudio() {
    if (!currentMatchId) {
        showMessage('対局IDが見つかりません');
        return;
    }

    try {
        const audioFiles = await getTtsFilesForMatch(currentMatchId);
        const screenshots = gVideoMode ? await getScreenshotsForMatch(currentMatchId) : [];

        if ((!audioFiles || audioFiles.length === 0) && (!screenshots || screenshots.length === 0)) {
            showMessage('保存されたファイルがありません');
            return;
        }

        const zip = new JSZip();
        const rootFolder = gMatchPrefix || currentMatchId;

        // Audio files → rootFolder/audio/
        if (audioFiles && audioFiles.length > 0) {
            audioFiles.sort((a, b) => a.moveCount - b.moveCount);
            const audioDir = gVideoMode ? `${rootFolder}/audio` : rootFolder;

            for (const file of audioFiles) {
                const wavData = createWavFile(base64ToBytes(file.audioData));
                zip.file(`${audioDir}/${file.filename}`, wavData);
            }
        }

        // Screenshots → rootFolder/images/ (video mode only)
        if (gVideoMode && screenshots && screenshots.length > 0) {
            screenshots.sort((a, b) => a.moveCount - b.moveCount);
            for (const ss of screenshots) {
                zip.file(`${rootFolder}/images/${ss.filename}`, base64ToBytes(ss.imageData));
            }
        }

        // metadata.json (video mode only)
        if (gVideoMode && gMatchMoves.length > 0) {
            const metadata = {
                match_id: rootFolder,
                sente_model: gSenteModel,
                gote_model: gGoteModel,
                instruction_level: gInstructionType,
                total_moves: gMatchMoves.length,
                moves: gMatchMoves,
                result: gameState && gameState.game_over ? (gameState.turn === SENTE ? 'gote_win' : 'sente_win') : 'ongoing'
            };
            zip.file(`${rootFolder}/metadata.json`, JSON.stringify(metadata, null, 2));
        }

        // Generate ZIP and download
        const zipBlob = await zip.generateAsync({ type: 'blob' });
        const url = URL.createObjectURL(zipBlob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${rootFolder}.zip`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);

        const totalFiles = (audioFiles ? audioFiles.length : 0) + (screenshots ? screenshots.length : 0);
        console.log(`Downloaded ${totalFiles} files as ZIP`);

        // Clear IndexedDB
        await clearTtsForMatch(currentMatchId);
        if (gVideoMode) await clearScreenshotsForMatch(currentMatchId);

        // Hide download button
        const btn = document.getElementById('download-audio-btn');
        if (btn) btn.style.display = 'none';

    } catch (e) {
        console.error('Download error:', e);
        showMessage('ダウンロードエラー: ' + e.message);
    }
}

function createWavFile(pcmData) {
    const sampleRate = 24000;
    const numChannels = 1;
    const bitsPerSample = 16;
    const byteRate = sampleRate * numChannels * bitsPerSample / 8;
    const blockAlign = numChannels * bitsPerSample / 8;
    const dataSize = pcmData.length;
    const headerSize = 44;
    const fileSize = headerSize + dataSize - 8;

    const wavBuffer = new ArrayBuffer(headerSize + dataSize);
    const view = new DataView(wavBuffer);

    writeString(view, 0, 'RIFF');
    view.setUint32(4, fileSize, true);
    writeString(view, 8, 'WAVE');
    writeString(view, 12, 'fmt ');
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, numChannels, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, byteRate, true);
    view.setUint16(32, blockAlign, true);
    view.setUint16(34, bitsPerSample, true);
    writeString(view, 36, 'data');
    view.setUint32(40, dataSize, true);

    const wavBytes = new Uint8Array(wavBuffer);
    wavBytes.set(pcmData, headerSize);

    return wavBytes;
}

// ========== TTS Audio Playback and Save Functions ==========
function base64ToBytes(base64) {
    const binaryString = atob(base64);
    const bytes = new Uint8Array(binaryString.length);
    for (let i = 0; i < binaryString.length; i++) {
        bytes[i] = binaryString.charCodeAt(i);
    }
    return bytes;
}

function playTtsAudio(base64Audio) {
    if (!base64Audio) return;
    try {
        const bytes = base64ToBytes(base64Audio);
        const wavData = createWavFile(bytes);
        const blob = new Blob([wavData], { type: 'audio/wav' });
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);
        audio.play().catch(e => console.error('TTS playback error:', e));
        audio.onended = () => URL.revokeObjectURL(url);
        return wavData;
    } catch (e) {
        console.error('TTS audio processing error:', e);
        return null;
    }
}

function writeString(view, offset, string) {
    for (let i = 0; i < string.length; i++) {
        view.setUint8(offset + i, string.charCodeAt(i));
    }
}

function saveTtsAudioFile(base64Audio, moveCount, moveStr) {
    if (!base64Audio) return;

    try {
        const bytes = base64ToBytes(base64Audio);
        const wavData = createWavFile(bytes);

        // Generate filename
        const paddedCount = String(moveCount).padStart(3, '0');
        const cleanMoveStr = moveStr.replace(/[\/\\:*?"<>|]/g, '');

        let filename;
        if (typeof gMatchPrefix !== 'undefined' && gMatchPrefix) {
            filename = `${gMatchPrefix}_${paddedCount}_${cleanMoveStr}.wav`;
        } else {
            const now = new Date();
            const dateStr = now.getFullYear().toString() +
                String(now.getMonth() + 1).padStart(2, '0') +
                String(now.getDate()).padStart(2, '0');
            filename = `${paddedCount}_${cleanMoveStr}_${dateStr}.wav`;
        }

        // Immediate download
        const blob = new Blob([wavData], { type: 'audio/wav' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);

        console.log(`TTS: Downloaded audio file: ${filename}`);
    } catch (e) {
        console.error('TTS save error:', e);
    }
}

function initTtsUI() {
    const ttsCheckbox = document.getElementById('tts-enabled');
    const saveOption = document.getElementById('tts-save-option');
    if (ttsCheckbox && saveOption) {
        ttsCheckbox.addEventListener('change', () => {
            saveOption.style.display = ttsCheckbox.checked ? 'block' : 'none';
            if (!ttsCheckbox.checked) {
                document.getElementById('tts-save-file').checked = false;
            }
        });
    }

    // Video mode: auto-enable TTS + save when checked
    const videoCheckbox = document.getElementById('video-mode');
    if (videoCheckbox) {
        videoCheckbox.addEventListener('change', () => {
            if (videoCheckbox.checked) {
                if (ttsCheckbox) ttsCheckbox.checked = true;
                const ttsSave = document.getElementById('tts-save-file');
                if (ttsSave) ttsSave.checked = true;
                if (saveOption) saveOption.style.display = 'block';
            }
        });
    }
}

// Update model name labels on the board
function updateModelLabels(senteModel, goteModel) {
    const senteLabel = document.getElementById('sente-model-label');
    const goteLabel = document.getElementById('gote-model-label');
    // Find display label from MODEL_OPTIONS
    const findLabel = (val) => {
        const opt = MODEL_OPTIONS.find(o => o.value === val);
        return opt ? opt.label : val;
    };
    if (senteLabel) senteLabel.textContent = senteModel ? findLabel(senteModel) : '';
    if (goteLabel) goteLabel.textContent = goteModel ? findLabel(goteModel) : '';
}

// ========== Screenshot (Video Mode) ==========
let screenshotDB = null;

async function initScreenshotDB() {
    return new Promise((resolve, reject) => {
        const request = indexedDB.open('ShogiScreenshots', 1);
        request.onerror = () => reject(request.error);
        request.onsuccess = () => { screenshotDB = request.result; resolve(screenshotDB); };
        request.onupgradeneeded = (event) => {
            const db = event.target.result;
            if (!db.objectStoreNames.contains('screenshots')) {
                const store = db.createObjectStore('screenshots', { keyPath: 'id' });
                store.createIndex('matchId', 'matchId', { unique: false });
            }
        };
    });
}

async function captureBoard(matchId, moveCount, moveJa) {
    try {
        const gameArea = document.querySelector('.game-area');
        if (!gameArea) return null;

        const canvas = await html2canvas(gameArea, {
            backgroundColor: '#f5f5dc',
            scale: 2,
            useCORS: true
        });

        const dataUrl = canvas.toDataURL('image/png');
        const base64 = dataUrl.split(',')[1];

        // Save to IndexedDB
        if (!screenshotDB) await initScreenshotDB();
        const paddedCount = String(moveCount).padStart(3, '0');
        const cleanMove = (moveJa || '').replace(/[\/\\:*?"<>|]/g, '');
        const filename = `${paddedCount}_${cleanMove}.png`;

        await new Promise((resolve, reject) => {
            const tx = screenshotDB.transaction(['screenshots'], 'readwrite');
            const store = tx.objectStore('screenshots');
            store.put({
                id: `${matchId}_${paddedCount}`,
                matchId: matchId,
                moveCount: moveCount,
                filename: filename,
                imageData: base64,
                timestamp: Date.now()
            });
            tx.oncomplete = () => resolve();
            tx.onerror = () => reject(tx.error);
        });

        console.log(`Screenshot saved: ${filename}`);
        return filename;
    } catch (e) {
        console.error('Screenshot capture error:', e);
        return null;
    }
}

async function getScreenshotsForMatch(matchId) {
    if (!screenshotDB) await initScreenshotDB();
    return new Promise((resolve, reject) => {
        const tx = screenshotDB.transaction(['screenshots'], 'readonly');
        const index = tx.objectStore('screenshots').index('matchId');
        const req = index.getAll(matchId);
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
    });
}

async function clearScreenshotsForMatch(matchId) {
    if (!screenshotDB) await initScreenshotDB();
    return new Promise((resolve, reject) => {
        const tx = screenshotDB.transaction(['screenshots'], 'readwrite');
        const store = tx.objectStore('screenshots');
        const index = store.index('matchId');
        const req = index.openCursor(IDBKeyRange.only(matchId));
        req.onsuccess = (event) => {
            const cursor = event.target.result;
            if (cursor) { cursor.delete(); cursor.continue(); }
            else resolve();
        };
        req.onerror = () => reject(req.error);
    });
}

// Stop AI Match
function stopAiMatch() {
    console.log("DEBUG: Stopping AI match, matchId:", currentMatchId);

    // Stop the loop by disabling ai_vs_ai mode (don't change currentMatchId — it's the IndexedDB key)
    if (gameState) {
        gameState.ai_vs_ai_mode = false;
        gameState.game_over = true;
    }

    // Hide stop button
    const stopBtn = document.getElementById('stop-match-btn');
    if (stopBtn) stopBtn.style.display = 'none';

    // Clear thinking indicators
    setThinking(SENTE, false);
    setThinking(GOTE, false);

    showMessage('対局を中止しました。📥素材DLボタンからデータをダウンロードできます。');
    console.log("DEBUG: Match stopped. matchId preserved:", currentMatchId);
}

// AI vs AI Loop
// AI vs AI Loop
async function startAiVsAiMatch(isResume = false) {
    console.log("DEBUG: startAiVsAiMatch clicked", isResume);
    hideAiSettings();
    const sModel = document.getElementById('sente-model').value;
    const gModel = document.getElementById('gote-model').value;
    const retryVal = document.getElementById('max-retries').value;
    const instructionEl = document.getElementById('ai_instruction_type');
    const instructionVal = instructionEl ? instructionEl.value : 'medium';

    gSenteModel = sModel;
    gGoteModel = gModel;
    gMaxRetries = parseInt(retryVal, 10);
    gInstructionType = instructionVal;

    // TTS Settings
    const ttsCheckbox = document.getElementById('tts-enabled');
    const ttsSaveCheckbox = document.getElementById('tts-save-file');
    gTtsEnabled = ttsCheckbox ? ttsCheckbox.checked : false;
    gTtsSaveFile = ttsSaveCheckbox ? ttsSaveCheckbox.checked : false;

    // Video Mode
    const videoCheckbox = document.getElementById('video-mode');
    gVideoMode = videoCheckbox ? videoCheckbox.checked : false;
    gMatchMoves = []; // Reset metadata

    // Generate Match Prefix: yyyymmdd_hhmmss_Sente_vs_Gote
    const now = new Date();
    const dateStr = now.getFullYear().toString() +
        String(now.getMonth() + 1).padStart(2, '0') +
        String(now.getDate()).padStart(2, '0') + '_' +
        String(now.getHours()).padStart(2, '0') +
        String(now.getMinutes()).padStart(2, '0') +
        String(now.getSeconds()).padStart(2, '0');
    const cleanS = sModel.replace(/[^a-zA-Z0-9.\-_]/g, '');
    const cleanG = gModel.replace(/[^a-zA-Z0-9.\-_]/g, '');
    gMatchPrefix = `${dateStr}_${cleanS}_vs_${cleanG}`;
    saveAiSettings();

    // Update model name labels
    updateModelLabels(sModel, gModel);

    // Show video download button if video mode is on
    const videoDlBtn = document.getElementById('video-download-btn');
    if (videoDlBtn) videoDlBtn.style.display = gVideoMode ? 'inline-block' : 'none';

    console.log("DEBUG: TTS:", gTtsEnabled, "Video:", gVideoMode, "Prefix:", gMatchPrefix);

    // SFEN Resume Logic
    let sfen = null;
    if (isResume) {
        const sfenInput = document.getElementById('resume-sfen');
        if (sfenInput && sfenInput.value.trim().length > 0) {
            sfen = sfenInput.value.trim();
        } else {
            showMessage("SFEN文字列を入力してください");
            return;
        }
    }

    console.log("DEBUG: Selected Models:", sModel, gModel, "SFEN Resume:", !!sfen);

    // Check if Human vs Human (Legacy Mode)
    if (sModel === 'human' && gModel === 'human') {
        console.log("DEBUG: Human vs Human detected.");
        currentMatchId = Date.now().toString(); // Invalidate any pending AI calls
        const stopBtn = document.getElementById('stop-match-btn');
        if (stopBtn) stopBtn.style.display = 'none';
        try {
            const response = await apiCall('/api/reset', 'POST', {
                vs_ai: false,
                ai_vs_ai: false,
                sfen: sfen // Pass optional SFEN
            });
            const result = await response.json();

            // Clear UI and State
            const rArea = document.getElementById('reasoning-area');
            if (rArea) rArea.innerHTML = '';
            selected = null;
            pendingMove = null;

            updateGameState(result.game_state);
        } catch (e) {
            console.error("Game Start Error", e);
            showMessage("Start Failed");
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
            gote_model: gModel,
            ai_instruction_type: document.getElementById('ai_instruction_type').value,
            sfen: sfen // Pass optional SFEN
        });
        const result = await response.json();
        console.log("DEBUG: Reset Response:", result);

        // Clear UI and State
        const rArea = document.getElementById('reasoning-area');
        if (rArea) rArea.innerHTML = '';
        selected = null;
        pendingMove = null;
        currentMatchId = Date.now().toString(); // New Match ID
        saveAiSettings();

        // Show stop button
        const stopBtn = document.getElementById('stop-match-btn');
        if (stopBtn) stopBtn.style.display = 'inline-block';

        // Clear Game Over Modal
        const goModal = document.getElementById('game-over-modal');
        if (goModal) goModal.style.display = 'none';

        updateGameState(result.game_state);

        console.log("DEBUG: Starting AI Loop...", currentMatchId);
        setTimeout(() => processAiVsAi(currentMatchId), 1000); // Start loop with ID

    } catch (e) {
        console.error("AI vs AI Start Error", e);
        showMessage("Failed to start AI match: " + e.message);
    }
}

async function processAiVsAi(matchId) {
    // If matchId is provided and doesn't match current, abort
    if (matchId && matchId !== currentMatchId) {
        console.log("DEBUG: Stale processAiVsAi call ignored.", matchId, currentMatchId);
        return;
    }
    // If no matchId provided (recurved call might need to handle this differently, 
    // but easiest is to pass it along or grab current if we trust flow)
    // Better: Always pass matchId.
    if (!matchId) matchId = currentMatchId;

    if (!gameState || !gameState.ai_vs_ai_mode || gameState.game_over) {
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

        // Stale check after await
        if (matchId !== currentMatchId) return;

        // cpuMove logic calls updateGameState.
        // We need to ensure the loop continues after CPU moves.
        // cpuMove is async and updates state. We should schedule next poll.
        if (!gameState.game_over) {
            setTimeout(() => processAiVsAi(matchId), 1000);
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
            max_retries: gMaxRetries,
            ai_instruction_type: document.getElementById('ai_instruction_type') ? document.getElementById('ai_instruction_type').value : 'medium',
            vs_ai: gameState.vs_ai,
            ai_vs_ai: gameState.ai_vs_ai_mode,
            tts_enabled: gTtsEnabled
        });

        // Stale Check immediately after await
        if (matchId !== currentMatchId) {
            console.log("DEBUG: Ignoring stale LLM response.", matchId, currentMatchId);
            return;
        }

        const result = await response.json();

        console.log("DEBUG: LLM Move Result:", result);

        if (result.status === 'ok') {
            updateGameState(result.game_state);

            // Handle AI Fallback Warning (Optional: can still keep it or rely on red text)
            // User requested red text in log, so passing flag to logMove is key.
            // Removing renderStatus warning update as per request.
            if (result.fallback_used) {
                gameState.ai_fallback_triggered = true;
                // renderStatus(); // Removed as requested
            }

            // Show Reasoning
            if (result.reasoning || result.move_str_ja) {
                const mStr = result.move_str_ja || result.usi || "";
                const model = result.model || "AI";
                logMove(result.move_count, model, mStr, result.reasoning, result.fallback_used);
            }

            // TTS Playback and Save
            if (result.tts_audio) {
                playTtsAudio(result.tts_audio);

                if (gVideoMode && result.move_str_ja) {
                    // Video mode: save to IndexedDB for ZIP download (skip individual download)
                    const paddedCount = String(result.move_count).padStart(3, '0');
                    const cleanMove = (result.move_str_ja || '').replace(/[\/\\:*?"<>|]/g, '');
                    const filename = `${paddedCount}_${cleanMove}.wav`;
                    await saveTtsToIndexedDB(currentMatchId, result.move_count, filename, result.tts_audio);
                } else if (gTtsSaveFile && result.move_str_ja) {
                    // Normal mode: individual file download
                    saveTtsAudioFile(result.tts_audio, result.move_count, result.move_str_ja);
                }
            } else if (result.tts_error) {
                console.error("TTS ERROR:", result.tts_error);
            } else if (gTtsEnabled) {
                console.warn("TTS: No audio in response (TTS may have failed silently)");
            }

            // Video Mode: capture screenshot + accumulate metadata
            if (gVideoMode && result.move_str_ja) {
                const imgFile = await captureBoard(currentMatchId, result.move_count, result.move_str_ja);
                const paddedCount = String(result.move_count).padStart(3, '0');
                const cleanMove = (result.move_str_ja || '').replace(/[\/\\:*?"<>|]/g, '');
                gMatchMoves.push({
                    number: result.move_count,
                    turn: gameState.turn === SENTE ? 'gote' : 'sente', // After move, turn flipped
                    model: result.model || 'AI',
                    usi: result.usi || '',
                    move_ja: result.move_str_ja,
                    reasoning: result.reasoning || '',
                    image: imgFile ? `images/${imgFile}` : null,
                    audio: `audio/${paddedCount}_${cleanMove}.wav`
                });
                saveAiSettings(); // Persist metadata to localStorage
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
window.onload = async () => {
    // Populate model <select> elements from single source of truth
    populateModelSelect("sente-model", "human");
    populateModelSelect("gote-model", "human");

    const loaded = loadLocalState();
    initTtsUI();

    // Restore AI settings from localStorage
    const savedSettings = localStorage.getItem(STORAGE_KEYS.aiSettings);
    if (savedSettings) {
        try {
            const settings = JSON.parse(savedSettings);
            if (settings.currentMatchId) currentMatchId = settings.currentMatchId;
            if (settings.senteModel) gSenteModel = settings.senteModel;
            if (settings.goteModel) gGoteModel = settings.goteModel;
            if (settings.maxRetries) gMaxRetries = settings.maxRetries;
            if (settings.instructionType) gInstructionType = settings.instructionType;
            if (settings.ttsEnabled !== undefined) gTtsEnabled = settings.ttsEnabled;
            if (settings.ttsSaveFile !== undefined) gTtsSaveFile = settings.ttsSaveFile;
            if (settings.videoMode !== undefined) gVideoMode = settings.videoMode;
            if (settings.matchPrefix) gMatchPrefix = settings.matchPrefix;
            if (settings.matchMoves) gMatchMoves = settings.matchMoves;
            console.log("DEBUG: Restored AI settings from localStorage", settings);

            // Restore model labels
            if (gSenteModel || gGoteModel) {
                updateModelLabels(gSenteModel, gGoteModel);
            }
        } catch (e) {
            console.error("AI settings restore error:", e);
        }
    }

    // Re-trigger AI turn after refresh
    if (loaded && gameState && !gameState.game_over) {
        if (gameState.ai_vs_ai_mode) {
            // AI vs AI mode: resume the AI loop
            if (!currentMatchId) currentMatchId = Date.now().toString();
            console.log("DEBUG: Resuming AI vs AI loop after refresh, matchId:", currentMatchId);
            setTimeout(() => processAiVsAi(currentMatchId), 1000);
        } else if (gameState.vs_ai && gameState.turn === GOTE) {
            // Human vs AI mode, AI's turn: trigger CPU move
            if (!currentMatchId) currentMatchId = Date.now().toString();
            console.log("DEBUG: Resuming CPU move after refresh");
            setTimeout(cpuMove, 500);
        }
    }

    // 初回アクセス時は初期盤面を生成
    if (!loaded) {
        try {
            const response = await apiCall('/api/reset', 'POST', {
                vs_ai: false,
                ai_vs_ai: false
            });
            const result = await response.json();
            updateGameState(result.game_state);
        } catch (e) {
            console.error("Failed to initialize game:", e);
        }
    }
};
