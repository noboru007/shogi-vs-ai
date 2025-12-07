from functions.game_logic import ShogiGame, SENTE, GOTE
import sys

# SFEN that caused the 502
sfen = "lnsg1gsnl/1r1k3+B1/pp1p1p1pp/2p1p4/9/2P4P1/PP1PPPP1P/7R1/LNSGKGSNL w PB 8"

print(f"Testing SFEN: {sfen}")

try:
    game = ShogiGame()
    game.from_sfen(sfen)
    print("Successfully loaded SFEN")
    
    print(f"Turn: {game.turn}")
    
    print("Getting legal moves...")
    moves = game.get_legal_moves(game.turn)
    print(f"Legal moves count: {len(moves)}")
    
    for m in moves[:5]:
        print(f"Sample move: {m}")
        
    print("Logic check passed.")
    
except Exception as e:
    print(f"CRASHED: {e}")
    import traceback
    traceback.print_exc()
