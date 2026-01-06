import copy
import random

# === 設定 ===
# 読みの深さ（2=自分->相手まで読む）
# === 設定 ===
# 読みの深さ（2=自分->相手まで読む）
CPU_DEPTH = 2

# 定数定義
BOARD_SIZE = 9
CELL_SIZE = 50 # GUI用だが、座標計算などで使われる可能性があるので残すか、ロジックでは不要なら消す。一旦残す。
# FONT_SIZE = 24 # GUI用
# HAND_AREA_HEIGHT = 120 # GUI用
# BOARD_Y_OFFSET = HAND_AREA_HEIGHT # GUI用
# ... GUI layout constants removed ...

# プレイヤー
SENTE = 1  # 先手（下/人間）
GOTE = -1  # 後手（上/CPU）

# === SFEN変換用マッピング ===
SFEN_MAP = {
    "歩": "P", "香": "L", "桂": "N", "銀": "S", "金": "G", "角": "B", "飛": "R", "王": "K",
    "と": "+P", "杏": "+L", "圭": "+N", "全": "+S", "馬": "+B", "竜": "+R"
}

# === 駒の価値 ===
PIECE_VALUES = {
    "歩": 100, "香": 300, "桂": 400, "銀": 500, "金": 600, "角": 800, "飛": 1000, "王": 15000,
    "と": 600, "杏": 600, "圭": 600, "全": 600, "馬": 1000, "竜": 1200
}

# 駒の動き定義
PIECES = {
    "歩": {"moves": [(0, -1)], "promote": "と", "type": "step"},
    "香": {"moves": [(0, -1)], "promote": "杏", "type": "slide"},
    "桂": {"moves": [(-1, -2), (1, -2)], "promote": "圭", "type": "jump"},
    "銀": {"moves": [(-1, -1), (0, -1), (1, -1), (-1, 1), (1, 1)], "promote": "全", "type": "step"},
    "金": {"moves": [(-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (0, 1)], "promote": None, "type": "step"},
    "角": {"moves": [(-1, -1), (1, -1), (-1, 1), (1, 1)], "promote": "馬", "type": "slide"},
    "飛": {"moves": [(0, -1), (0, 1), (-1, 0), (1, 0)], "promote": "竜", "type": "slide"},
    "王": {"moves": [(-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1)], "promote": None, "type": "step"},
    "と": {"base": "金"}, "杏": {"base": "金"}, "圭": {"base": "金"}, "全": {"base": "金"},
    "馬": {"base": "角", "extra": [(0, -1), (0, 1), (-1, 0), (1, 0)]},
    "竜": {"base": "飛", "extra": [(-1, -1), (1, -1), (-1, 1), (1, 1)]}
}

for name, data in PIECES.items():
    if "base" in data:
        base_moves = PIECES[data["base"]]["moves"]
        if "extra" in data:
            PIECES[name]["moves"] = PIECES[data["base"]]["moves"]
            PIECES[name]["type"] = PIECES[data["base"]]["type"]
            PIECES[name]["extra_moves"] = data["extra"]
        else:
            PIECES[name]["moves"] = base_moves
            PIECES[name]["type"] = "step"
    if "promote" not in PIECES[name]:
        PIECES[name]["promote"] = None

class ShogiGame:
    def __init__(self, vs_ai=False):
        self.vs_ai = vs_ai
        self.turn = SENTE
        self.board = [[None for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
        self.hands = {SENTE: {}, GOTE: {}}
        self.selected = None 
        self.game_over = False 
        self.move_count = 1
        self.last_move = None
        self.init_board()

    def init_board(self):
        setup = [
            (0, 0, "香", GOTE), (1, 0, "桂", GOTE), (2, 0, "銀", GOTE), (3, 0, "金", GOTE), (4, 0, "王", GOTE), (5, 0, "金", GOTE), (6, 0, "銀", GOTE), (7, 0, "桂", GOTE), (8, 0, "香", GOTE),
            (1, 1, "飛", GOTE), (7, 1, "角", GOTE),
            *[(i, 2, "歩", GOTE) for i in range(9)],
            *[(i, 6, "歩", SENTE) for i in range(9)],
            (1, 7, "角", SENTE), (7, 7, "飛", SENTE),
            (0, 8, "香", SENTE), (1, 8, "桂", SENTE), (2, 8, "銀", SENTE), (3, 8, "金", SENTE), (4, 8, "王", SENTE), (5, 8, "金", SENTE), (6, 8, "銀", SENTE), (7, 8, "桂", SENTE), (8, 8, "香", SENTE),
        ]
        for x, y, name, owner in setup:
            self.board[y][x] = {"name": name, "owner": owner}

    def get_piece(self, x, y):
        if 0 <= x < BOARD_SIZE and 0 <= y < BOARD_SIZE:
            return self.board[y][x]
        return None

    def switch_turn(self):
        self.turn *= -1
        self.move_count += 1

    def add_to_hand(self, owner, piece_name):
        original_names = {
            "と": "歩", "杏": "香", "圭": "桂", "全": "銀", "馬": "角", "竜": "飛"
        }
        name = original_names.get(piece_name, piece_name)
        if name in self.hands[owner]:
            self.hands[owner][name] += 1
        else:
            self.hands[owner][name] = 1

    def is_pseudo_valid_move(self, start, end, piece, owner):
        sx, sy = start
        ex, ey = end
        dx, dy = ex - sx, ey - sy
        forward = 1 if owner == SENTE else -1
        
        target = self.get_piece(ex, ey)
        if target and target["owner"] == owner:
            return False

        piece_info = PIECES[piece["name"]]
        move_type = piece_info["type"]
        base_moves = piece_info["moves"]
        extra_moves = piece_info.get("extra_moves", [])

        valid_steps = []
        for mx, my in base_moves:
            valid_steps.append((mx * forward, my * forward))
        for mx, my in extra_moves:
             valid_steps.append((mx * forward, my * forward))

        if move_type == "step" or (move_type == "slide" and (dx, dy) in valid_steps):
             if (dx, dy) in valid_steps: return True

        if move_type == "jump":
             if (dx, dy) in valid_steps: return True
        
        if move_type == "slide":
            direction = None
            for mx, my in base_moves:
                check_mx, check_my = mx * forward, my * forward
                if check_mx == 0 and dx == 0: 
                    if check_my * dy > 0: direction = (0, 1 if dy > 0 else -1)
                elif check_my == 0 and dy == 0:
                    if check_mx * dx > 0: direction = (1 if dx > 0 else -1, 0)
                elif check_mx != 0 and check_my != 0 and abs(dx) == abs(dy):
                     if (dx // abs(dx)) == check_mx and (dy // abs(dy)) == check_my:
                         direction = (check_mx, check_my)
            
            if direction:
                curr_x, curr_y = sx + direction[0], sy + direction[1]
                steps = 0
                while (curr_x, curr_y) != (ex, ey):
                    steps += 1
                    if steps > BOARD_SIZE: return False
                    if not (0 <= curr_x < BOARD_SIZE and 0 <= curr_y < BOARD_SIZE): return False
                    if self.get_piece(curr_x, curr_y) is not None:
                        return False
                    curr_x += direction[0]
                    curr_y += direction[1]
                return True
        return False

    def is_stuck(self, x, y, name, owner):
        if name == "歩" or name == "香":
            if owner == SENTE and y == 0: return True
            if owner == GOTE and y == 8: return True
        if name == "桂":
            if owner == SENTE and y <= 1: return True
            if owner == GOTE and y >= 7: return True
        return False

    def has_nifu(self, x, owner):
        for y in range(BOARD_SIZE):
            p = self.board[y][x]
            if p and p["owner"] == owner and p["name"] == "歩":
                return True
        return False

    def find_king(self, owner):
        for y in range(BOARD_SIZE):
            for x in range(BOARD_SIZE):
                p = self.board[y][x]
                if p and p["owner"] == owner and p["name"] == "王":
                    return (x, y)
        return None

    def is_king_in_check(self, owner):
        king_pos = self.find_king(owner)
        if not king_pos: return True
        kx, ky = king_pos
        opponent = owner * -1
        
        for y in range(BOARD_SIZE):
            for x in range(BOARD_SIZE):
                p = self.board[y][x]
                if p and p["owner"] == opponent:
                    if self.is_pseudo_valid_move((x, y), (kx, ky), p, opponent):
                        return True
        return False

    def can_capture_king(self, attacker):
        # Check if 'attacker' can capture the opponent's King immediately
        opponent = attacker * -1
        king_pos = self.find_king(opponent)
        if not king_pos: return False # Already captured?
        
        kx, ky = king_pos
        
        for y in range(BOARD_SIZE):
            for x in range(BOARD_SIZE):
                p = self.board[y][x]
                if p and p["owner"] == attacker:
                    # Ignore pin checks, just pure physical reachability
                    if self.is_pseudo_valid_move((x, y), (kx, ky), p, attacker):
                        return True
        return False

    def simulate_move_check(self, move_type, start_or_name, end, owner, promote=False):
        backup_board_ref = self.board
        temp_board = []
        for row in self.board:
            new_row = []
            for piece in row:
                if piece: new_row.append(piece.copy())
                else: new_row.append(None)
            temp_board.append(new_row)
        self.board = temp_board
        
        try:
            res = self.apply_move_internal(move_type, start_or_name, end, owner, promote, self.board)
        except Exception:
            res = False
        finally:
            self.board = backup_board_ref
        
        return res

    def get_random_move(self):
        moves = self.get_legal_moves(self.turn)
        if moves:
            return random.choice(moves)
        return None

    def apply_move_internal(self, move_type, start_or_name, end, owner, promote, board_ref):
        ex, ey = end
        if move_type == "move":
            sx, sy = start_or_name
            piece = board_ref[sy][sx]
            if piece is None: return False
            if not promote and self.is_stuck(ex, ey, piece["name"], owner):
                return False
            board_ref[sy][sx] = None
            name = PIECES[piece["name"]]["promote"] if promote else piece["name"]
            board_ref[ey][ex] = {"name": name, "owner": owner}
        elif move_type == "drop":
            name = start_or_name
            if self.is_stuck(ex, ey, name, owner): return False
            if name == "歩" and self.has_nifu(ex, owner): return False
            board_ref[ey][ex] = {"name": name, "owner": owner}
        if self.is_king_in_check(owner):
            return False
        return True

    def is_physically_possible(self, move_type, start_or_name, end, owner, promote=False):
        ex, ey = end
        if move_type == "move":
            sx, sy = start_or_name
            # 1. Piece must exist at source
            piece = self.board[sy][sx]
            if piece is None or piece["owner"] != owner: return False
            
            # 2. Destination must not be friendly
            target = self.board[ey][ex]
            if target and target["owner"] == owner: return False
            
            # 3. Piece movement geometry check
            if not self.is_pseudo_valid_move(start_or_name, end, piece, owner):
                return False
                
            # 4. Promotion Validity Check (Defensive Programming)
            if promote:
                if not self.can_promote(sy, ey, owner, piece["name"]):
                    return False

            # 5. Stuck check (Immobile piece)
            if not promote and self.is_stuck(ex, ey, piece["name"], owner):
                return False
                
            return True
            
        elif move_type == "drop":
            name = start_or_name
            # 1. Must have piece in hand
            if self.hands[owner].get(name, 0) <= 0: return False
            
            # 2. Destination must be empty
            if self.board[ey][ex] is not None: return False
            
            # 3. Stuck check
            if self.is_stuck(ex, ey, name, owner): return False
            
            # 4. Nifu check
            if name == "歩" and self.has_nifu(ex, owner): return False
            
            return True
            
        return False

    def make_move(self, move_type, start_or_name, end, owner, promote=False):
        ex, ey = end
        captured = None
        if move_type == "move":
            sx, sy = start_or_name
            piece = self.board[sy][sx]
            captured = self.board[ey][ex]
            self.board[sy][sx] = None
            name = PIECES[piece["name"]]["promote"] if promote else piece["name"]
            self.board[ey][ex] = {"name": name, "owner": owner}
            self.last_move = {"to": end, "owner": owner}
        elif move_type == "drop":
            name = start_or_name
            self.board[ey][ex] = {"name": name, "owner": owner}
            self.hands[owner][name] -= 1
            self.last_move = {"to": end, "owner": owner}
        if captured:
            self.add_to_hand(owner, captured["name"])

    def can_promote(self, sy, ey, owner, piece_name):
        if PIECES[piece_name]["promote"] is None:
            return False
        zone = [0, 1, 2] if owner == SENTE else [6, 7, 8]
        return sy in zone or ey in zone

    def get_legal_moves(self, owner):
        moves = []
        for y in range(BOARD_SIZE):
            for x in range(BOARD_SIZE):
                p = self.board[y][x]
                if p and p["owner"] == owner:
                    for ty in range(BOARD_SIZE):
                        for tx in range(BOARD_SIZE):
                            if self.is_pseudo_valid_move((x, y), (tx, ty), p, owner):
                                can_pm = self.can_promote(y, ty, owner, p["name"])
                                if self.simulate_move_check("move", (x, y), (tx, ty), owner, promote=False):
                                    moves.append({"type": "move", "from": (x, y), "to": (tx, ty), "promote": False})
                                if can_pm:
                                    if self.simulate_move_check("move", (x, y), (tx, ty), owner, promote=True):
                                        moves.append({"type": "move", "from": (x, y), "to": (tx, ty), "promote": True})
        for name, count in self.hands[owner].items():
            if count > 0:
                for y in range(BOARD_SIZE):
                    for x in range(BOARD_SIZE):
                        if self.board[y][x] is None:
                            if self.simulate_move_check("drop", name, (x, y), owner):
                                moves.append({"type": "drop", "name": name, "to": (x, y)})
        return moves

    def evaluate_board(self):
        score = 0
        for y in range(BOARD_SIZE):
            for x in range(BOARD_SIZE):
                p = self.board[y][x]
                if p:
                    val = PIECE_VALUES.get(p["name"], 0)
                    
                    # Position Bonus: Advance towards enemy
                    # Sente (1) wants y -> 0. Gote (-1) wants y -> 8.
                    # Simple bonus: 5 points per rank advanced
                    pos_bonus = 0
                    if p["owner"] == SENTE:
                         pos_bonus = (8 - y) * 5
                    else: # GOTE
                         pos_bonus = y * 5
                         
                    if p["owner"] == GOTE: score += (val + pos_bonus)
                    else: score -= (val + pos_bonus)
        
        # King Safety (Simplified)
        # Bonus for defenders around the King
        for owner in [SENTE, GOTE]:
            k_pos = self.find_king(owner)
            if k_pos:
                kx, ky = k_pos
                safety_score = 0
                # Check 3x3 area around King
                for dy in [-1, 0, 1]:
                    for dx in [-1, 0, 1]:
                        if dx == 0 and dy == 0: continue
                        tx, ty = kx + dx, ky + dy
                        if 0 <= tx < BOARD_SIZE and 0 <= ty < BOARD_SIZE:
                            tp = self.board[ty][tx]
                            if tp and tp["owner"] == owner:
                                # Friendly piece near King -> Good defender
                                if tp["name"] in ["金", "銀", "香", "馬", "竜"]:
                                     safety_score += 200 # Significant bonus
                                else:
                                     safety_score += 50 # Minor bonus
                
                if owner == GOTE: score += safety_score
                else: score -= safety_score

        # Hand Valuation: 1.4x to discourage reckless drops
        # Holding a piece is potential power. Dropping it loses that flexibility.
        hand_multiplier = 1.4
        
        for name, count in self.hands[GOTE].items():
            score += PIECE_VALUES.get(name, 0) * count * hand_multiplier
        for name, count in self.hands[SENTE].items():
            score -= PIECE_VALUES.get(name, 0) * count * hand_multiplier
            
        return score

    # === JSON Serialization for Firestore ===
    def to_dict(self):
        return {
            "board": self.board,
            "hands": self.hands,
            "turn": self.turn,
            "game_over": self.game_over,
            "move_count": self.move_count,
            "last_move": self.last_move,
            "vs_ai": self.vs_ai
        }

    def from_state(self, state):
        self.board = state.get("board", self.board)
        # Convert keys in hands back to int if they became strings (JSON dict keys are strings)
        raw_hands = state.get("hands", self.hands)
        self.hands = {}
        for k, v in raw_hands.items():
            self.hands[int(k)] = v
            
        self.turn = state.get("turn", self.turn)
        self.game_over = state.get("game_over", self.game_over)
        self.move_count = state.get("move_count", self.move_count)
        self.last_move = state.get("last_move", self.last_move)
        self.vs_ai = state.get("vs_ai", self.vs_ai)

    # === SFEN生成機能 ===
    def get_sfen(self):
        sfen_rows = []
        for y in range(BOARD_SIZE):
            empty_count = 0
            row_str = ""
            for x in range(BOARD_SIZE):
                piece = self.board[y][x]
                if piece is None:
                    empty_count += 1
                else:
                    if empty_count > 0:
                        row_str += str(empty_count)
                        empty_count = 0
                    char = SFEN_MAP[piece["name"]]
                    if piece["owner"] == GOTE:
                        char = char.lower()
                    row_str += char
            if empty_count > 0:
                row_str += str(empty_count)
            sfen_rows.append(row_str)
        
        board_sfen = "/".join(sfen_rows)
        turn_sfen = "b" if self.turn == SENTE else "w"
        
        hands_sfen = ""
        has_hand = False
        
        # 先手
        for name, count in self.hands[SENTE].items():
            if count > 0:
                has_hand = True
                char = SFEN_MAP[name]
                if count > 1: hands_sfen += str(count) + char
                else: hands_sfen += char
        
        # 後手
        for name, count in self.hands[GOTE].items():
            if count > 0:
                has_hand = True
                char = SFEN_MAP[name].lower()
                if count > 1: hands_sfen += str(count) + char
                else: hands_sfen += char
                
        if not has_hand:
            hands_sfen = "-"
            
        return f"{board_sfen} {turn_sfen} {hands_sfen} {self.move_count}"

    def from_sfen(self, sfen):
        try:
            parts = sfen.split(" ")
            board_str = parts[0]
            turn_str = parts[1]
            hands_str = parts[2]
            move_count_str = parts[3] if len(parts) > 3 else "1"

            # Reset Board
            self.board = [[None for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
            
            # Reverse Map
            reverse_map = {v: k for k, v in SFEN_MAP.items()}
            
            # Parse Board
            rows = board_str.split("/")
            for y, row_data in enumerate(rows):
                x = 0
                i = 0
                while i < len(row_data):
                    char = row_data[i]
                    if char.isdigit():
                        x += int(char)
                        i += 1
                        continue
                        
                    is_promoted = False
                    if char == "+":
                        is_promoted = True
                        i += 1
                        char = row_data[i]
                        
                    if x >= BOARD_SIZE: break 
                    
                    owner = SENTE if char.isupper() else GOTE
                    sfen_char = "+" + char.upper() if is_promoted else char.upper()
                    
                    name = reverse_map.get(sfen_char)
                    if not name:
                         # Fallback for simple chars if + missing in map (though SFEN_MAP has +P etc)
                         name = reverse_map.get(char.upper())

                    if name:
                        self.board[y][x] = {"name": name, "owner": owner}
                    x += 1
                    i += 1
            
            # Parse Turn
            self.turn = SENTE if turn_str == 'b' else GOTE
            
            # Parse Move Count
            self.move_count = int(move_count_str)
            
            # Parse Hands
            self.hands = {SENTE: {}, GOTE: {}}
            if hands_str != "-":
                i = 0
                while i < len(hands_str):
                    count = 1
                    num_str = ""
                    while i < len(hands_str) and hands_str[i].isdigit():
                        num_str += hands_str[i]
                        i += 1
                    if num_str:
                        count = int(num_str)
                    
                    if i < len(hands_str):
                        char = hands_str[i]
                        owner = SENTE if char.isupper() else GOTE
                        name = reverse_map.get(char.upper())
                        if name:
                            # Original names logic
                            # In hand, pieces are unpromoted usually.
                            self.hands[owner][name] = self.hands[owner].get(name, 0) + count
                        i += 1

        except Exception as e:
            print(f"Error parsing SFEN: {e}")
            # Fallback to init? Or raise?
            raise e

    def minimax(self, game_state, depth, alpha, beta, maximizing):
        legal_moves = game_state.get_legal_moves(GOTE if maximizing else SENTE)
        
        # Base Case with Check Extension
        if depth <= 0:
            current_turn = GOTE if maximizing else SENTE
            # If in check at depth 0, extend search by 1 ply to see resolution
            # Limit extension to avoid infinite recursion (depth -1 means already extended?)
            # Simplified: Allow finding a move to escape check.
            is_in_check = game_state.is_king_in_check(current_turn)
            
            # Note: valid moves usually handle escape. 
            # If legal_moves is empty => Mate. evaluate_board doesn't know mate.
            if not legal_moves:
                # Mate detection
                return (-99999 if maximizing else 99999), None
                
            if not is_in_check:
                return game_state.evaluate_board(), None
            else:
                # Extend 1 ply for check resolution
                # To prevent infinite depth, we treat depth 0 as "check extension allowed"
                # and depth -1 as "stop".
                if depth == 0:
                     depth = 1 # Extend!
                else: 
                     return game_state.evaluate_board(), None

        # Sort moves for Alpha-Beta pruning efficiency
        # Heuristic: Captures first?
        # For now, simple shuffle is okay, or sort by standard eval? 
        random.shuffle(legal_moves)
        best_move = None
        if maximizing: 
            max_eval = -float('inf')
            for move in legal_moves:
                next_state = copy.deepcopy(game_state)
                if move["type"] == "move":
                    next_state.make_move("move", move["from"], move["to"], GOTE, move["promote"])
                else:
                    next_state.make_move("drop", move["name"], move["to"], GOTE)
                next_state.switch_turn()
                eval_score, _ = self.minimax(next_state, depth - 1, alpha, beta, False)
                if eval_score > max_eval:
                    max_eval = eval_score
                    best_move = move
                alpha = max(alpha, eval_score)
                if beta <= alpha: break
            return max_eval, best_move
        else:
            min_eval = float('inf')
            for move in legal_moves:
                next_state = copy.deepcopy(game_state)
                if move["type"] == "move":
                    next_state.make_move("move", move["from"], move["to"], SENTE, move["promote"])
                else:
                    next_state.make_move("drop", move["name"], move["to"], SENTE)
                next_state.switch_turn()
                eval_score, _ = self.minimax(next_state, depth - 1, alpha, beta, True)
                if eval_score < min_eval:
                    min_eval = eval_score
                    best_move = move
                beta = min(beta, eval_score)
                if beta <= alpha: break
            return min_eval, best_move
