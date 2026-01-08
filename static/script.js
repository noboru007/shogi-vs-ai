const BOARD_SIZE = 9;
const SENTE = 1;
const GOTE = -1;

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
let gMatchPrefix = ""; // yyyymmdd_hhmmss_Sente_vs_Gote
let currentMatchId = null; // To prevent stale AI responses from overwriting new game

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
        // Show Game Over Modal
        const modal = document.getElementById('game-over-modal');
        if (modal && modal.style.display !== 'flex') {
            modal.style.display = 'flex';
        }
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

// TTS Audio Playback and Save Functions
function playTtsAudio(base64Audio) {
    if (!base64Audio) return;
    try {
        const binaryString = atob(base64Audio);
        const bytes = new Uint8Array(binaryString.length);
        for (let i = 0; i < binaryString.length; i++) {
            bytes[i] = binaryString.charCodeAt(i);
        }
        const sampleRate = 24000;
        const numChannels = 1;
        const bitsPerSample = 16;
        const byteRate = sampleRate * numChannels * bitsPerSample / 8;
        const blockAlign = numChannels * bitsPerSample / 8;
        const dataSize = bytes.length;
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
        wavBytes.set(bytes, headerSize);
        const blob = new Blob([wavBuffer], { type: 'audio/wav' });
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);
        audio.play().catch(e => console.error('TTS playback error:', e));
        audio.onended = () => URL.revokeObjectURL(url);
        return wavBuffer;
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
        const binaryString = atob(base64Audio);
        const bytes = new Uint8Array(binaryString.length);
        for (let i = 0; i < binaryString.length; i++) {
            bytes[i] = binaryString.charCodeAt(i);
        }
        const sampleRate = 24000;
        const numChannels = 1;
        const bitsPerSample = 16;
        const byteRate = sampleRate * numChannels * bitsPerSample / 8;
        const blockAlign = numChannels * bitsPerSample / 8;
        const dataSize = bytes.length;
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
        wavBytes.set(bytes, headerSize);
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
        const blob = new Blob([wavBuffer], { type: 'audio/wav' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        console.log(`TTS: Saved audio file: ${filename}`);
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

    console.log("DEBUG: TTS Enabled:", gTtsEnabled, "Save File:", gTtsSaveFile, "Prefix:", gMatchPrefix);

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
                if (gTtsSaveFile && result.move_str_ja) {
                    saveTtsAudioFile(result.tts_audio, result.move_count, result.move_str_ja);
                }
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
    initTtsUI();
};
