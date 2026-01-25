import sys
sys.path.insert(0, 'functions')
from game_logic import ShogiGame, SENTE, GOTE

# Simulate multiple round-trips like the API does
print("=== Simulating 49 moves with round-trips ===")

# Start with initial board
game = ShogiGame()
print(f"Initial: {game.get_sfen()}")

# Simulate moving 7-6 pawn and then parsing/regenerating
game.make_move("move", (2, 6), (2, 5), SENTE, False)
game.switch_turn()

sfen_after_1 = game.get_sfen()
print(f"After move 1: {sfen_after_1}")

# Now simulate what the API does: create new game from SFEN
game2 = ShogiGame()
game2.from_sfen(sfen_after_1)
sfen_roundtrip = game2.get_sfen()
print(f"After roundtrip 1: {sfen_roundtrip}")
print(f"Match: {sfen_after_1 == sfen_roundtrip}")

# Test if board data matches
print("\nComparing board row 0:")
for x in range(9):
    p1 = game.board[0][x]
    p2 = game2.board[0][x]
    match = (p1 == p2)
    print(f"  x={x}: game1={p1}, game2={p2}, match={match}")

# Test the problematic scenario more directly
print("\n=== Testing with Correct Board and checking SFEN ===")
game3 = ShogiGame()
# Manually create the correct board state based on 'ln6l'
game3.board[0] = [None] * 9
game3.board[0][0] = {"name": "香", "owner": GOTE}
game3.board[0][1] = {"name": "桂", "owner": GOTE}
game3.board[0][8] = {"name": "香", "owner": GOTE}

sfen3 = game3.get_sfen()
row0 = sfen3.split("/")[0]
print(f"Created board with ln6l layout")
print(f"Generated row 0: {row0}")
print(f"Expected: ln6l")
print(f"Match: {row0 == 'ln6l'}")

# Inverse test: create board with n6l1 layout  
print("\n=== Inverse: Create board with n6l1 layout ===")
game4 = ShogiGame()
game4.board[0] = [None] * 9
game4.board[0][0] = {"name": "桂", "owner": GOTE}  # n at x=0
game4.board[0][7] = {"name": "香", "owner": GOTE}  # l at x=7

sfen4 = game4.get_sfen()
row0_4 = sfen4.split("/")[0]
print(f"Board: knight at x=0, lance at x=7")
print(f"Generated row 0: {row0_4}")
print(f"Expected: n6l1")
print(f"Match: {row0_4 == 'n6l1'}")

print("\n=== CONCLUSION ===")
print("If get_sfen generates 'n6l1', but user expected 'ln6l',")
print("then the board data itself has the pieces in wrong positions.")
print("The knight is at x=0 but should be at x=1.")
print("The lance is at x=7 but should be at x=0 and x=8.")
