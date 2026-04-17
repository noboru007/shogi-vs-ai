import copy
import logging
import random
import time

logger = logging.getLogger("shogi")

# === 設定 ===
CPU_DEPTH = 3           # 最大探索深度
CPU_TIME_LIMIT = 30     # 制限時間（秒）- 反復深化で時間内に最大限深く読む
QUIESCENCE_DEPTH = 4    # 静止探索の最大深度

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
    "歩": 90, "香": 315, "桂": 405, "銀": 495, "金": 540, "角": 855, "飛": 990, "王": 15000,
    "と": 540, "杏": 540, "圭": 540, "全": 540, "馬": 1100, "竜": 1395
}

# === 駒の位置評価テーブル (先手視点, y=0が敵陣1段目) ===
# 歩: 敵陣に近いほど高評価、3段目到達でボーナス
PST_PAWN = [
    [0,  0,  0,  0,  0,  0,  0,  0,  0],  # y=0 (成れるはず)
    [15, 15, 15, 15, 15, 15, 15, 15, 15],  # y=1
    [10, 10, 12, 15, 20, 15, 12, 10, 10],  # y=2 (敵陣3段目)
    [5,  5,  8,  12, 15, 12,  8,  5,  5],  # y=3
    [2,  2,  5,   8, 10,  8,  5,  2,  2],  # y=4 (中央)
    [0,  0,  2,   5,  5,  5,  2,  0,  0],  # y=5
    [0,  0,  0,   0,  0,  0,  0,  0,  0],  # y=6 (初期位置)
    [0,  0,  0,   0,  0,  0,  0,  0,  0],  # y=7
    [0,  0,  0,   0,  0,  0,  0,  0,  0],  # y=8
]

# 飛車: 中央ファイルや2筋が強い
PST_ROOK = [
    [5,  10, 5,  5,  5,  5,  5,  10, 5],
    [10, 15, 10, 10, 10, 10, 10, 15, 10],
    [5,  10, 8,  8,  8,  8,  8,  10, 5],
    [5,  5,  5,  5,  5,  5,  5,  5,  5],
    [0,  0,  0,  0,  5,  0,  0,  0,  0],
    [0,  0,  0,  0,  0,  0,  0,  0,  0],
    [0,  0,  0,  0,  0,  0,  0,  0,  0],
    [-5, 0,  0,  0,  0,  0,  0,  0, -5],
    [-5, 0,  0,  0,  0,  0,  0,  0, -5],
]

# 角: 中央寄りが有利
PST_BISHOP = [
    [0,  0,  0,  0,  0,  0,  0,  0,  0],
    [0,  5,  0,  0,  0,  0,  0,  5,  0],
    [0,  0,  8,  0,  0,  0,  8,  0,  0],
    [0,  0,  0,  10, 0,  10, 0,  0,  0],
    [0,  0,  0,  0,  15, 0,  0,  0,  0],
    [0,  0,  0,  10, 0,  10, 0,  0,  0],
    [0,  0,  8,  0,  0,  0,  8,  0,  0],
    [0,  5,  0,  0,  0,  0,  0,  5,  0],
    [0,  0,  0,  0,  0,  0,  0,  0,  0],
]

# 金: 自玉付近で守備力を発揮
PST_GOLD = [
    [0,  0,  0,  0,  0,  0,  0,  0,  0],
    [0,  0,  0,  0,  0,  0,  0,  0,  0],
    [0,  0,  0,  0,  5,  0,  0,  0,  0],
    [0,  0,  0,  5,  5,  5,  0,  0,  0],
    [0,  0,  0,  0,  0,  0,  0,  0,  0],
    [0,  0,  5,  5,  5,  5,  5,  0,  0],
    [0,  5,  8,  10, 10, 10, 8,  5,  0],
    [5,  8,  10, 12, 10, 12, 10, 8,  5],
    [5,  5,  8,  10, 5,  10, 8,  5,  5],
]

# 銀: 攻めにも守りにも使える
PST_SILVER = [
    [0,  0,  0,  0,  0,  0,  0,  0,  0],
    [0,  5,  5,  5,  5,  5,  5,  5,  0],
    [0,  5,  8,  8,  10, 8,  8,  5,  0],
    [0,  0,  5,  8,  8,  8,  5,  0,  0],
    [0,  0,  0,  5,  5,  5,  0,  0,  0],
    [0,  0,  5,  5,  5,  5,  5,  0,  0],
    [0,  5,  8,  8,  5,  8,  8,  5,  0],
    [5,  8,  10, 8,  5,  8,  10, 8,  5],
    [0,  5,  5,  5,  0,  5,  5,  5,  0],
]

# 王: 自陣の端に近い方が安全（囲い寄り）
PST_KING = [
    [-30,-20,-20,-20,-20,-20,-20,-20,-30],
    [-20,-15,-15,-15,-15,-15,-15,-15,-20],
    [-15,-10,-10,-10,-10,-10,-10,-10,-15],
    [-10, -5, -5, -5, -5, -5, -5, -5,-10],
    [-5,  0,  0,  0,  0,  0,  0,  0, -5],
    [0,   5,  5,  5,  0,  5,  5,  5,  0],
    [5,  10, 10, 10,  0, 10, 10, 10,  5],
    [10, 15, 15, 10,  5, 10, 15, 15, 10],
    [15, 20, 15, 10,  5, 10, 15, 20, 15],
]

# 駒名 -> PST のマッピング
PST_MAP = {
    "歩": PST_PAWN, "香": PST_PAWN,  # 香も前進する駒なので歩と同様
    "桂": PST_PAWN,
    "銀": PST_SILVER, "金": PST_GOLD,
    "角": PST_BISHOP, "飛": PST_ROOK,
    "王": PST_KING,
    # 成駒は金と同等の扱い
    "と": PST_GOLD, "杏": PST_GOLD, "圭": PST_GOLD, "全": PST_GOLD,
    # 馬・竜は中央が強い
    "馬": PST_BISHOP, "竜": PST_ROOK,
}

# 成駒のマッピング (成駒 -> 元駒)
UNPROMOTION_MAP = {
    "と": "歩", "杏": "香", "圭": "桂", "全": "銀", "馬": "角", "竜": "飛"
}

# USI変換用マッピング
SFEN_CHAR_TO_KANJI = {v: k for k, v in SFEN_MAP.items()}
USI_FILES = "987654321"
USI_RANKS = "abcdefghi"


def parse_usi_string(usi):
    """USI文字列を内部の move dict に変換する。
    - ドロップ: 'P*5e' 形式
    - 移動: '7g7f' / '7g7f+' 形式
    """
    if '*' in usi:
        name_char, pos_str = usi.split('*')
        name = SFEN_CHAR_TO_KANJI.get(name_char.upper(), name_char)
        tx = USI_FILES.index(pos_str[0])
        ty = USI_RANKS.index(pos_str[1])
        return {'type': 'drop', 'name': name, 'to': [tx, ty]}

    promote = False
    if usi.endswith('+'):
        promote = True
        usi = usi[:-1]
    sx = USI_FILES.index(usi[0])
    sy = USI_RANKS.index(usi[1])
    tx = USI_FILES.index(usi[2])
    ty = USI_RANKS.index(usi[3])
    return {'type': 'move', 'from': [sx, sy], 'to': [tx, ty], 'promote': promote}


def to_usi(move):
    """内部 move dict を USI 文字列に変換する。"""
    if move["type"] == "drop":
        char = SFEN_MAP.get(move["name"])
        if not char:
            return None
        if char.startswith("+"):
            char = char[1:]
        tx, ty = move["to"]
        return f"{char}*{USI_FILES[tx]}{USI_RANKS[ty]}"
    if move["type"] == "move":
        sx, sy = move["from"]
        tx, ty = move["to"]
        promote = "+" if move["promote"] else ""
        return f"{USI_FILES[sx]}{USI_RANKS[sy]}{USI_FILES[tx]}{USI_RANKS[ty]}{promote}"
    return None

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
        self._search_start_time = 0
        self._search_time_limit = CPU_TIME_LIMIT
        self._search_aborted = False
        self._nodes_searched = 0
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
        name = UNPROMOTION_MAP.get(piece_name, piece_name)
        self.hands[owner][name] = self.hands[owner].get(name, 0) + 1

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
        except Exception as e:
            logger.debug("simulate_move_check failed: %s", e)
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

    def _piece_destinations(self, x, y, piece, owner):
        """駒の種類に応じて到達可能マスを直接列挙する。
        (tx, ty) を yield する。自駒マスは除外し、敵駒マスは含む（そこでスライドは停止）。
        """
        piece_info = PIECES[piece["name"]]
        move_type = piece_info["type"]
        base_moves = piece_info["moves"]
        extra_moves = piece_info.get("extra_moves", [])
        forward = 1 if owner == SENTE else -1

        if move_type in ("step", "jump"):
            for mx, my in base_moves:
                tx, ty = x + mx * forward, y + my * forward
                if not (0 <= tx < BOARD_SIZE and 0 <= ty < BOARD_SIZE):
                    continue
                target = self.board[ty][tx]
                if target and target["owner"] == owner:
                    continue
                yield tx, ty
            return

        # slide: 各方向にブロッカーまで進む
        for mx, my in base_moves:
            dx, dy = mx * forward, my * forward
            tx, ty = x + dx, y + dy
            while 0 <= tx < BOARD_SIZE and 0 <= ty < BOARD_SIZE:
                target = self.board[ty][tx]
                if target and target["owner"] == owner:
                    break
                yield tx, ty
                if target:
                    break
                tx += dx
                ty += dy
        # 馬/竜の追加一歩
        for mx, my in extra_moves:
            tx, ty = x + mx * forward, y + my * forward
            if not (0 <= tx < BOARD_SIZE and 0 <= ty < BOARD_SIZE):
                continue
            target = self.board[ty][tx]
            if target and target["owner"] == owner:
                continue
            yield tx, ty

    def get_legal_moves(self, owner):
        moves = []
        for y in range(BOARD_SIZE):
            for x in range(BOARD_SIZE):
                p = self.board[y][x]
                if not p or p["owner"] != owner:
                    continue
                for tx, ty in self._piece_destinations(x, y, p, owner):
                    can_pm = self.can_promote(y, ty, owner, p["name"])
                    if self.simulate_move_check("move", (x, y), (tx, ty), owner, promote=False):
                        moves.append({"type": "move", "from": (x, y), "to": (tx, ty), "promote": False})
                    if can_pm and self.simulate_move_check("move", (x, y), (tx, ty), owner, promote=True):
                        moves.append({"type": "move", "from": (x, y), "to": (tx, ty), "promote": True})
        # 打つ手: 二歩の筋を事前計算
        nifu_cols = {x for x in range(BOARD_SIZE) if self.has_nifu(x, owner)}
        for name, count in self.hands[owner].items():
            if count <= 0:
                continue
            for y in range(BOARD_SIZE):
                for x in range(BOARD_SIZE):
                    if self.board[y][x] is not None:
                        continue
                    if name == "歩" and x in nifu_cols:
                        continue
                    if self.simulate_move_check("drop", name, (x, y), owner):
                        moves.append({"type": "drop", "name": name, "to": (x, y)})
        return moves

    def evaluate_board(self):
        """強化版評価関数: 駒価値 + 位置評価 + 玉安全度 + 防御評価 + 終盤補正"""
        score = 0

        # --- 盤面の駒の総価値で終盤判定 ---
        total_material = 0
        for y in range(BOARD_SIZE):
            for x in range(BOARD_SIZE):
                p = self.board[y][x]
                if p and p["name"] != "王":
                    total_material += PIECE_VALUES.get(p["name"], 0)
        for owner in [SENTE, GOTE]:
            for name, count in self.hands[owner].items():
                total_material += PIECE_VALUES.get(name, 0) * count
        is_endgame = total_material < 4000

        # --- 1. 駒価値 + 位置評価 ---
        for y in range(BOARD_SIZE):
            for x in range(BOARD_SIZE):
                p = self.board[y][x]
                if p:
                    val = PIECE_VALUES.get(p["name"], 0)

                    # 位置評価テーブルの参照
                    pst = PST_MAP.get(p["name"])
                    pos_bonus = 0
                    if pst:
                        if p["owner"] == SENTE:
                            pos_bonus = pst[y][x]
                        else:  # GOTE: テーブルを上下反転
                            pos_bonus = pst[8 - y][8 - x]

                    if p["owner"] == GOTE:
                        score += (val + pos_bonus)
                    else:
                        score -= (val + pos_bonus)

        # --- 2. 玉の安全度（大幅強化版） ---
        for owner in [SENTE, GOTE]:
            k_pos = self.find_king(owner)
            if not k_pos:
                continue
            kx, ky = k_pos
            safety_score = 0
            opponent = owner * -1
            sign = 1 if owner == GOTE else -1

            # 2a. 玉周辺の味方駒ボーナス + 空きマスペナルティ（3x3）
            defender_values = {"金": 250, "銀": 200, "全": 200, "と": 180,
                               "杏": 150, "圭": 150, "馬": 120, "竜": 120,
                               "歩": 60, "香": 80, "桂": 40}
            empty_near_king = 0
            for dy_k in [-1, 0, 1]:
                for dx_k in [-1, 0, 1]:
                    if dx_k == 0 and dy_k == 0:
                        continue
                    tx, ty = kx + dx_k, ky + dy_k
                    if 0 <= tx < BOARD_SIZE and 0 <= ty < BOARD_SIZE:
                        tp = self.board[ty][tx]
                        if tp and tp["owner"] == owner:
                            safety_score += defender_values.get(tp["name"], 50)
                        elif tp is None:
                            empty_near_king += 1
                    # 盤外は安全とみなす（端の玉は逃げ場が少ないが壁がある）

            # 空きマスが多い = 守りが薄い（ペナルティ）
            if empty_near_king >= 5:
                safety_score -= 200
            elif empty_near_king >= 3:
                safety_score -= 80

            # 2b. 敵の大駒の脅威（飛角竜馬）
            for y2 in range(BOARD_SIZE):
                for x2 in range(BOARD_SIZE):
                    ep = self.board[y2][x2]
                    if ep and ep["owner"] == opponent:
                        if ep["name"] in ["飛", "竜"]:
                            # 同じ行 or 同じ列 → ラインアタック
                            if x2 == kx or y2 == ky:
                                dist = abs(x2 - kx) + abs(y2 - ky)
                                safety_score -= max(0, 400 - dist * 30)
                            # 竜は隣接もチェック（全方向に動けるので）
                            if ep["name"] == "竜":
                                dist = max(abs(x2 - kx), abs(y2 - ky))
                                if dist <= 2:
                                    safety_score -= 300
                        if ep["name"] in ["角", "馬"]:
                            # 同じ対角線
                            if abs(x2 - kx) == abs(y2 - ky) and x2 != kx:
                                dist = abs(x2 - kx)
                                safety_score -= max(0, 300 - dist * 25)
                            # 馬は隣接もチェック
                            if ep["name"] == "馬":
                                dist = max(abs(x2 - kx), abs(y2 - ky))
                                if dist <= 2:
                                    safety_score -= 250

            # 2c. 玉が端にいることのボーナス（自陣のみ）
            if owner == SENTE and ky >= 7:
                if kx <= 1 or kx >= 7:
                    safety_score += 80
            elif owner == GOTE and ky <= 1:
                if kx <= 1 or kx >= 7:
                    safety_score += 80

            score += safety_score * sign

        # --- 3. 敵大駒の自陣侵入ペナルティ ---
        # 相手の飛角竜馬が自陣にいると非常に危険
        invasion_penalty = {"飛": 600, "竜": 900, "角": 400, "馬": 700}
        for y in range(BOARD_SIZE):
            for x in range(BOARD_SIZE):
                p = self.board[y][x]
                if p and p["name"] in invasion_penalty:
                    penalty = invasion_penalty[p["name"]]
                    if p["owner"] == SENTE:
                        # 先手の大駒が後手陣(y<=2)にいる → 後手にとって脅威
                        if y <= 2:
                            depth_bonus = (2 - y) * 100  # 奥に入るほど危険
                            score -= (penalty + depth_bonus)  # 先手有利
                    else:  # GOTE
                        # 後手の大駒が先手陣(y>=6)にいる → 先手にとって脅威
                        if y >= 6:
                            depth_bonus = (y - 6) * 100
                            score += (penalty + depth_bonus)  # 後手有利

        # --- 4. 玉前面の歩の防壁チェック ---
        # 玉の前の筋に歩がない（飛車先が空いている）= 危険
        for owner in [SENTE, GOTE]:
            k_pos = self.find_king(owner)
            if not k_pos:
                continue
            kx, ky = k_pos
            sign = 1 if owner == GOTE else -1

            # 玉の前方3筋をチェック（自分の歩があるか）
            pawn_shield = 0
            for dx in [-1, 0, 1]:
                col = kx + dx
                if col < 0 or col >= BOARD_SIZE:
                    pawn_shield += 1  # 盤外はOK
                    continue
                has_pawn = False
                # 先手なら前方(y小さい方)、後手なら前方(y大きい方)
                if owner == SENTE:
                    for check_y in range(ky - 1, -1, -1):
                        p = self.board[check_y][col]
                        if p and p["owner"] == owner and p["name"] == "歩":
                            has_pawn = True
                            break
                        if p and p["owner"] != owner:
                            break  # 相手の駒に遮られている
                else:
                    for check_y in range(ky + 1, BOARD_SIZE):
                        p = self.board[check_y][col]
                        if p and p["owner"] == owner and p["name"] == "歩":
                            has_pawn = True
                            break
                        if p and p["owner"] != owner:
                            break
                if has_pawn:
                    pawn_shield += 1

            if pawn_shield == 0:
                score += sign * (-300)  # 3筋とも歩なし = 非常に危険
            elif pawn_shield == 1:
                score += sign * (-150)  # 2筋の歩がない
            elif pawn_shield == 2:
                score += sign * (-50)   # 1筋の歩がない

        # --- 5. 王手状態のペナルティ ---
        # 自分が王手されている = 非常に悪い局面
        for owner in [SENTE, GOTE]:
            if self.is_king_in_check(owner):
                sign = 1 if owner == GOTE else -1
                score += sign * (-500)

        # --- 6. 持ち駒の評価 ---
        hand_multiplier = 1.6 if is_endgame else 1.3
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
        for owner in (SENTE, GOTE):
            for name, count in self.hands[owner].items():
                if count <= 0:
                    continue
                char = SFEN_MAP[name]
                if owner == GOTE:
                    char = char.lower()
                hands_sfen += (str(count) if count > 1 else "") + char
        if not hands_sfen:
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
            logger.error("Error parsing SFEN: %s", e)
            raise

    def _apply_move(self, move, owner):
        """手を適用し、undo情報を返す（copy.deepcopy不要の高速化）"""
        ex, ey = move["to"]
        undo = {"move": move, "owner": owner, "captured": None,
                "old_last_move": self.last_move}

        if move["type"] == "move":
            sx, sy = move["from"]
            piece = self.board[sy][sx]
            undo["src_piece"] = piece
            captured = self.board[ey][ex]
            undo["captured"] = captured

            self.board[sy][sx] = None
            if move["promote"]:
                name = PIECES[piece["name"]]["promote"]
            else:
                name = piece["name"]
            self.board[ey][ex] = {"name": name, "owner": owner}

            if captured:
                cap_name = UNPROMOTION_MAP.get(captured["name"], captured["name"])
                if cap_name in self.hands[owner]:
                    self.hands[owner][cap_name] += 1
                else:
                    self.hands[owner][cap_name] = 1
                undo["cap_original"] = cap_name
        else:  # drop
            name = move["name"]
            self.board[ey][ex] = {"name": name, "owner": owner}
            self.hands[owner][name] -= 1

        self.last_move = {"to": (ex, ey), "owner": owner}
        self.turn *= -1
        self.move_count += 1
        return undo

    def _undo_move(self, undo):
        """_apply_moveで得たundo情報から手を元に戻す"""
        move = undo["move"]
        owner = undo["owner"]
        ex, ey = move["to"]

        self.turn *= -1
        self.move_count -= 1
        self.last_move = undo["old_last_move"]

        if move["type"] == "move":
            sx, sy = move["from"]
            self.board[sy][sx] = undo["src_piece"]
            self.board[ey][ex] = undo["captured"]

            if undo["captured"]:
                cap_name = undo["cap_original"]
                self.hands[owner][cap_name] -= 1
                if self.hands[owner][cap_name] == 0:
                    del self.hands[owner][cap_name]
        else:  # drop
            name = move["name"]
            self.board[ey][ex] = None
            self.hands[owner][name] = self.hands[owner].get(name, 0) + 1

    def _score_move(self, move, owner):
        """手の順序付けのためのスコアリング（MVV-LVA + 成り優先）"""
        score = 0
        ex, ey = move["to"]

        if move["type"] == "move":
            # 駒取りの手: MVV-LVA (Most Valuable Victim - Least Valuable Attacker)
            target = self.board[ey][ex]
            if target and target["owner"] != owner:
                victim_val = PIECE_VALUES.get(target["name"], 0)
                sx, sy = move["from"]
                attacker = self.board[sy][sx]
                attacker_val = PIECE_VALUES.get(attacker["name"], 0) if attacker else 0
                score += 10000 + victim_val * 10 - attacker_val

            # 成りの手
            if move.get("promote"):
                sx, sy = move["from"]
                piece = self.board[sy][sx]
                if piece:
                    promoted_name = PIECES[piece["name"]].get("promote")
                    if promoted_name:
                        score += 5000 + (PIECE_VALUES.get(promoted_name, 0) - PIECE_VALUES.get(piece["name"], 0))
        else:  # drop
            # 打ち込みは中程度の優先度
            score += 100
            # 敵陣への打ち込みはボーナス
            if owner == SENTE and ey <= 2:
                score += 200
            elif owner == GOTE and ey >= 6:
                score += 200

        return score

    def _order_moves(self, moves, owner):
        """手を評価順にソート（alpha-beta枝刈りの効率化）"""
        scored = [(self._score_move(m, owner), random.random(), m) for m in moves]
        scored.sort(key=lambda x: (-x[0], x[1]))  # スコア降順、同点はランダム
        return [m for _, _, m in scored]

    def _generate_captures(self, owner):
        """指定 owner の駒取りの手だけを列挙する。"""
        captures = []
        for y in range(BOARD_SIZE):
            for x in range(BOARD_SIZE):
                p = self.board[y][x]
                if not p or p["owner"] != owner:
                    continue
                for tx, ty in self._piece_destinations(x, y, p, owner):
                    target = self.board[ty][tx]
                    if not target:
                        continue
                    if self.simulate_move_check("move", (x, y), (tx, ty), owner, promote=False):
                        captures.append({"type": "move", "from": (x, y), "to": (tx, ty), "promote": False})
                    if self.can_promote(y, ty, owner, p["name"]) and \
                            self.simulate_move_check("move", (x, y), (tx, ty), owner, promote=True):
                        captures.append({"type": "move", "from": (x, y), "to": (tx, ty), "promote": True})
        return captures

    def _quiescence_search(self, alpha, beta, maximizing, depth):
        """静止探索: 駒取りの手だけを追加探索して交換を正確に評価"""
        stand_pat = self.evaluate_board()
        if depth <= 0:
            return stand_pat

        owner = GOTE if maximizing else SENTE

        if maximizing:
            if stand_pat >= beta:
                return beta
            if stand_pat > alpha:
                alpha = stand_pat
        else:
            if stand_pat <= alpha:
                return alpha
            if stand_pat < beta:
                beta = stand_pat

        captures = self._order_moves(self._generate_captures(owner), owner)
        for move in captures:
            undo = self._apply_move(move, owner)
            eval_score = self._quiescence_search(alpha, beta, not maximizing, depth - 1)
            self._undo_move(undo)

            if maximizing:
                if eval_score >= beta:
                    return beta
                if eval_score > alpha:
                    alpha = eval_score
            else:
                if eval_score <= alpha:
                    return alpha
                if eval_score < beta:
                    beta = eval_score
        return alpha if maximizing else beta

    def _is_time_up(self):
        """制限時間チェック（100ノードごとに判定して負荷を軽減）"""
        if self._nodes_searched % 100 == 0:
            if time.time() - self._search_start_time >= self._search_time_limit:
                self._search_aborted = True
                return True
        return self._search_aborted

    def minimax(self, game_state, depth, alpha, beta, maximizing):
        """強化版minimax: undo/redo方式 + 手の順序付け + 静止探索 + 王手延長 + 時間制限"""
        self._nodes_searched += 1

        # 時間切れチェック
        if self._is_time_up():
            return game_state.evaluate_board(), None

        current_turn = GOTE if maximizing else SENTE
        legal_moves = game_state.get_legal_moves(current_turn)

        # 合法手なし = 詰み
        if not legal_moves:
            return (-99999 + (CPU_DEPTH - depth) if maximizing else 99999 - (CPU_DEPTH - depth)), None

        # 深度0: 王手延長 or 静止探索
        if depth <= 0:
            is_in_check = game_state.is_king_in_check(current_turn)
            if is_in_check and depth == 0:
                depth = 1  # 王手延長: 1手だけ追加探索
            else:
                # 静止探索で駒取りの交換を正確に評価
                return game_state._quiescence_search(alpha, beta, maximizing, QUIESCENCE_DEPTH), None

        # 手の順序付け（alpha-beta枝刈りの効率化）
        ordered_moves = game_state._order_moves(legal_moves, current_turn)

        best_move = None
        best_eval = -float('inf') if maximizing else float('inf')
        sign = 1 if maximizing else -1

        for move in ordered_moves:
            undo = game_state._apply_move(move, current_turn)
            eval_score, _ = self.minimax(game_state, depth - 1, alpha, beta, not maximizing)
            game_state._undo_move(undo)

            if self._search_aborted:
                if best_move is None:
                    best_move = move
                unset = (maximizing and best_eval == -float('inf')) or \
                        (not maximizing and best_eval == float('inf'))
                return (eval_score if unset else best_eval), best_move

            if (eval_score - best_eval) * sign > 0:
                best_eval = eval_score
                best_move = move

            if maximizing:
                alpha = max(alpha, eval_score)
            else:
                beta = min(beta, eval_score)
            if beta <= alpha:
                break

        return best_eval, best_move

    def iterative_deepening(self, maximizing, time_limit=None):
        """反復深化: 制限時間内で可能な限り深く探索する"""
        if time_limit is not None:
            self._search_time_limit = time_limit
        else:
            self._search_time_limit = CPU_TIME_LIMIT
        self._search_start_time = time.time()
        self._search_aborted = False

        best_move = None
        best_val = 0
        reached_depth = 0

        for depth in range(1, CPU_DEPTH + 1):
            self._nodes_searched = 0
            self._search_aborted = False

            val, move = self.minimax(self, depth, -float('inf'), float('inf'), maximizing)

            if self._search_aborted:
                elapsed = time.time() - self._search_start_time
                logger.info("Depth %d: TIME UP (%.1fs, %d nodes) - using depth %d result",
                            depth, elapsed, self._nodes_searched, reached_depth)
                break

            best_val = val
            best_move = move
            reached_depth = depth
            elapsed = time.time() - self._search_start_time
            logger.info("Depth %d: val=%s, move=%s, time=%.1fs, nodes=%d",
                        depth, val, move, elapsed, self._nodes_searched)

            if abs(val) > 90000:
                logger.info("Mate found at depth %d!", depth)
                break

            remaining = self._search_time_limit - elapsed
            if remaining < elapsed * 5:
                logger.info("Stopping: not enough time for depth %d (remaining=%.1fs)",
                            depth + 1, remaining)
                break

        logger.info("Final: depth=%d, val=%s, total_time=%.1fs",
                    reached_depth, best_val, time.time() - self._search_start_time)
        return best_val, best_move
