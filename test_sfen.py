
from functions.game_logic import ShogiGame, SENTE, GOTE

def test_sfen_cycle():
    # Initial SFEN
    start_sfen = "lnsgkgsnl/1r5b1/ppppppppp/9/9/9/PPPPPPPPP/1B5R1/LNSGKGSNL b - 1"
    
    print(f"Start: {start_sfen}")
    
    # Init from SFEN
    game = ShogiGame()
    game.from_sfen(start_sfen)
    
    # Verify parsing
    sfen_1 = game.get_sfen()
    print(f"Parsed: {sfen_1}")
    assert start_sfen == sfen_1
    
    # Make Move 7g7f (Human/Sente)
    # Coordinates: 7g -> x=2 (files index), y=6
    # 7f -> x=2, y=5
    # Files: 987654321 -> index 012345678. 7 is index 2.
    move_from = (2, 6)
    move_to = (2, 5)
    
    game.make_move('move', move_from, move_to, SENTE, False)

    game.switch_turn()
    
    sfen_2 = game.get_sfen()
    print(f"After 7g7f: {sfen_2}")
    
    expected_sfen = "lnsgkgsnl/1r5b1/ppppppppp/9/9/2P6/PP1PPPPPP/1B5R1/LNSGKGSNL w - 2"
    if sfen_2 == expected_sfen:
        print("SUCCESS: SFEN updated correctly.")
    else:
        print(f"FAILURE: Expected {expected_sfen}, got {sfen_2}")

    # Test Gote Move (2c2d) -> x=7, y=2 -> x=7, y=3
    # 2c: 987654321 => 2 is index 7. c is index 2.
    # 2d: index 7, index 3.
    
    game2 = ShogiGame()
    game2.from_sfen(sfen_2)
    
    if not game2.make_move('move', (7, 2), (7, 3), GOTE, False):
        print("Gote Move failed!")
        return
        
    game2.switch_turn()
    sfen_3 = game2.get_sfen()
    print(f"After 2c2d: {sfen_3}")
    
if __name__ == "__main__":
    test_sfen_cycle()
