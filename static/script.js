const BOARD_SIZE = 9;
const SENTE = 1;
const GOTE = -1;

let gameState = null;
let selected = null; // {type: 'board', pos: [x, y]} or {type: 'hand', name: 'PieceName'}

async function fetchGameState() {
    const response = await fetch(`/api/game?t=${new Date().getTime()}`);
    gameState = await response.json();
    render();

    if (gameState.vs_ai && gameState.turn === GOTE && !gameState.game_over) {
        // CPU Turn (Minimax)
        setTimeout(cpuMove, 100);
    } else if (gameState.ai_vs_ai_mode && !gameState.game_over) {
        // AI vs AI Loop
        processAiVsAi();
    }
}

async function startGame(vsCpu) {
    if (!confirm("新しい対局を始めますか？")) return;

    await fetch('/api/reset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ vs_ai: vsCpu })
    });
    selected = null;
    fetchGameState();
}

async function cpuMove() {
    if (!gameState.vs_ai) return; // double check

    const response = await fetch('/api/cpu', { method: 'POST' });
    const result = await response.json();
    if (result.status === 'ok') {
        fetchGameState();
    } else {
        console.error(result.message);
    }
}

function render() {
    renderBoard();
    renderHands();
    renderStatus();
    document.getElementById('sfen-entry').value = `あなたは最強の将棋CPUです。この局面の次の一手は？\n${gameState.sfen}`;
}

function copySfen() {
    const copyText = document.getElementById("sfen-entry");
    copyText.select();
    copyText.setSelectionRange(0, 99999);
    navigator.clipboard.writeText(copyText.value).then(() => {
        alert("コピーしました！");
    });
}

function renderBoard() {
    const boardEl = document.getElementById('board');
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
    if (gameState.game_over) {
        indicator.textContent = "勝負あり - 新しい対局を選んでください";
    } else {
        indicator.textContent = gameState.turn === SENTE ? "手番: 先手 (下)" : "手番: 後手 (上)";
    }
}

function onHandClick(name) {
    if (gameState.game_over) return;
    if (gameState.turn !== SENTE) return; // Only Sente can click hand in this UI for now (assuming vs CPU or Human Sente)

    if (selected && selected.type === 'hand' && selected.name === name) {
        selected = null;
    } else {
        selected = { type: 'hand', name: name };
    }
    render();
}

async function onBoardClick(x, y) {
    if (gameState.game_over) return;
    if (gameState.turn !== SENTE && gameState.vs_ai) return; // Block input during CPU turn if vs CPU

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
                to: [x, y]
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
        console.log(`Checking promotion for ${sourcePiece.name} from ${sx},${sy} to ${x},${y}`);

        const response = await fetch('/api/check_promote', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                from: [sx, sy],
                to: [x, y],
                name: sourcePiece.name
            })
        });
        const check = await response.json();
        console.log(`Promotion check result: ${check.can_promote}`);

        if (check.can_promote) {
            showPromotionModal(sx, sy, x, y);
        } else {
            await makeMove({
                type: 'move',
                from: [sx, sy],
                to: [x, y],
                promote: false
            });
        }
    }
}

function showPromotionModal(sx, sy, ex, ey) {
    // Create modal elements dynamically if not exist
    let modal = document.getElementById('promotion-modal');
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'promotion-modal';
        modal.style.position = 'fixed';
        modal.style.top = '0';
        modal.style.left = '0';
        modal.style.width = '100%';
        modal.style.height = '100%';
        modal.style.backgroundColor = 'rgba(0,0,0,0.5)';
        modal.style.display = 'flex';
        modal.style.justifyContent = 'center';
        modal.style.alignItems = 'center';
        modal.style.zIndex = '1000';

        const content = document.createElement('div');
        content.style.backgroundColor = '#fff';
        content.style.padding = '20px';
        content.style.borderRadius = '5px';
        content.style.textAlign = 'center';
        content.style.boxShadow = '0 2px 10px rgba(0,0,0,0.2)';

        const text = document.createElement('p');
        text.textContent = '成りますか？';
        text.style.marginBottom = '20px';
        text.style.fontSize = '18px';

        const btnContainer = document.createElement('div');
        btnContainer.style.display = 'flex';
        btnContainer.style.justifyContent = 'center';
        btnContainer.style.gap = '10px';

        const yesBtn = document.createElement('button');
        yesBtn.textContent = 'はい';
        yesBtn.style.padding = '5px 20px';
        yesBtn.style.fontSize = '16px';
        yesBtn.cursor = 'pointer';
        yesBtn.id = 'promote-yes';

        const noBtn = document.createElement('button');
        noBtn.textContent = 'いいえ';
        noBtn.style.padding = '5px 20px';
        noBtn.style.fontSize = '16px';
        noBtn.cursor = 'pointer';
        noBtn.id = 'promote-no';

        btnContainer.appendChild(yesBtn);
        btnContainer.appendChild(noBtn);
        content.appendChild(text);
        content.appendChild(btnContainer);
        modal.appendChild(content);
        document.body.appendChild(modal);
    }

    modal.style.display = 'flex';

    // Handle clicks
    const yesBtn = document.getElementById('promote-yes');
    const noBtn = document.getElementById('promote-no');

    // Remove old listeners to avoid multiple calls (simple way: clone node or one-time listener)
    // Using one-time listener approach for simplicity in this context
    const handleYes = async () => {
        modal.style.display = 'none';
        cleanup();
        await makeMove({
            type: 'move',
            from: [sx, sy],
            to: [ex, ey],
            promote: true
        });
    };

    const handleNo = async () => {
        modal.style.display = 'none';
        cleanup();
        await makeMove({
            type: 'move',
            from: [sx, sy],
            to: [ex, ey],
            promote: false
        });
    };

    function cleanup() {
        yesBtn.removeEventListener('click', handleYes);
        noBtn.removeEventListener('click', handleNo);
    }

    yesBtn.addEventListener('click', handleYes);
    noBtn.addEventListener('click', handleNo);
}

async function makeMove(moveData) {
    const response = await fetch('/api/move', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(moveData)
    });

    const result = await response.json();
    if (result.status === 'ok') {
        selected = null;
        fetchGameState();
    } else {
        alert(result.message);
        selected = null;
        render(); // Re-render to clear selection if invalid
    }
}

// Initial load
fetchGameState();

function showAiSettings() {
    document.getElementById('ai-settings').style.display = 'block';
}

async function startAiVsAiMatch() {
    const senteModel = document.getElementById('sente-model').value;
    const goteModel = document.getElementById('gote-model').value;

    document.getElementById('ai-settings').style.display = 'none';

    await fetch('/api/reset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            vs_ai: false,
            ai_vs_ai: true,
            sente_model: senteModel,
            gote_model: goteModel
        })
    });
    selected = null;
    fetchGameState();
}

async function processAiVsAi() {
    if (gameState.game_over) return;

    // Safety delay
    await new Promise(r => setTimeout(r, 1000));

    // Request LLM Move
    try {
        const response = await fetch('/api/llm_move', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                sfen: gameState.sfen,
                turn: gameState.turn
            })
        });
        const result = await response.json();
        if (result.status !== 'ok') {
            console.error("LLM Error:", result.message);
            // Retry or Stop? Stop for now.
            return;
        }

        const usi = result.usi;
        console.log("LLM Move:", usi, result.reasoning);

        // Execute Move
        const moveData = parseUsi(usi);
        if (moveData) {
            await makeMove(moveData);
        } else {
            console.error("Failed to parse USI:", usi);
        }

    } catch (e) {
        console.error("AI processing error", e);
    }
}

function parseUsi(usi) {
    // USI format: 7g7f or B*5e or 7g7f+
    // Internal x: 0(9)..8(1)
    // Internal y: 0(a)..8(i)

    const FILES = "987654321";
    const RANKS = "abcdefghi";

    // Drop?
    if (usi.includes('*')) {
        const [pieceChar, pos] = usi.split('*');
        // pieceChar: B, R, G, S, N, L, P
        // Need to map USI piece char to internal name.
        // Game Logic uses: 'Hu', 'Ky', 'Ke', 'Gi', 'Ki', 'Ka', 'Hi', 'Ou' (Japanese Romaji?)
        // Wait, app.py game_logic constants:
        // PIECES = { "Hu":..., "Ky":... }
        // get_sfen uses: P, L, N, S, G, B, R, K etc.
        // Dictionary for Drop:
        const dropMap = {
            'P': 'Hu', 'L': 'Ky', 'N': 'Ke', 'S': 'Gi', 'G': 'Ki', 'B': 'Ka', 'R': 'Hi',
            'p': 'Hu', 'l': 'Ky', 'n': 'Ke', 's': 'Gi', 'g': 'Ki', 'b': 'Ka', 'r': 'Hi'
        };
        const name = dropMap[pieceChar];
        if (!name) return null;

        const x = FILES.indexOf(pos[0]);
        const y = RANKS.indexOf(pos[1]);
        if (x === -1 || y === -1) return null;

        return { type: 'drop', name: name, to: [x, y] };
    }

    // Move
    // e.g. 7g7f, 7g7f+
    // src: 7g -> x,y
    // dst: 7f -> x,y
    // promote: +

    // Regex for move
    // 4 chars + optional +
    const match = usi.match(/^([1-9])([a-i])([1-9])([a-i])(\+)?$/);
    if (!match) return null;

    const sx = FILES.indexOf(match[1]);
    const sy = RANKS.indexOf(match[2]);
    const ex = FILES.indexOf(match[3]);
    const ey = RANKS.indexOf(match[4]);
    const promote = !!match[5];

    return {
        type: 'move',
        from: [sx, sy],
        to: [ex, ey],
        promote: promote
    };
}
