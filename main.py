from flask import Flask, jsonify, request, send_from_directory
from game_logic import ShogiGame, SENTE, GOTE, CPU_DEPTH
import copy
import os
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()

# Configure Gemini
api_key = os.getenv("GOOGLE_API_KEY")
if api_key:
    genai.configure(api_key=api_key)

app = Flask(__name__, static_url_path='', static_folder='static')

game = ShogiGame(vs_ai=True)
# Extension for AI vs AI
ai_vs_ai_mode = False
sente_model_name = "gemini-2.5-flash"
gote_model_name = "gemini-2.5-flash"

@app.route('/')
def index():
    response = send_from_directory('static', 'index.html')
    response.headers.add("Cache-Control", "no-cache, no-store, must-revalidate")
    return response

@app.route('/api/game', methods=['GET'])
def get_game_state():
    response = jsonify({
        'board': game.board,
        'hands': game.hands,
        'turn': game.turn,
        'game_over': game.game_over,
        'sfen': game.get_sfen(),
        'last_move': game.last_move,
        'vs_ai': game.vs_ai,
        'ai_vs_ai_mode': ai_vs_ai_mode
    })
    response.headers.add("Cache-Control", "no-cache, no-store, must-revalidate")
    return response

@app.route('/api/reset', methods=['POST'])
def reset_game():
    global game, ai_vs_ai_mode, sente_model_name, gote_model_name
    data = request.json
    vs_cpu = data.get('vs_ai', True)
    
    # AI vs AI settings
    ai_vs_ai_mode = data.get('ai_vs_ai', False)
    if ai_vs_ai_mode:
        sente_model_name = data.get('sente_model', 'gemini-1.5-pro')
        gote_model_name = data.get('gote_model', 'gemini-1.5-pro')
        vs_cpu = False # Disable standard minimax CPU

    game = ShogiGame(vs_ai=vs_cpu)
    return jsonify({'status': 'ok'})

@app.route('/api/move', methods=['POST'])
def make_move():
    if game.game_over:
        return jsonify({'status': 'error', 'message': 'Game Over'}), 400
    
    data = request.json
    move_type = data.get('type')
    owner = game.turn 
    
    # Validation override for AI vs AI (backend doesn't block "Not your turn" if it's AI vs AI controller doing it)
    # But usually frontend will call this sequentially.
    if not ai_vs_ai_mode:
        if owner != SENTE and game.vs_ai:
            return jsonify({'status': 'error', 'message': 'Not your turn'}), 400

    if move_type == 'move':
        start = tuple(data.get('from'))
        end = tuple(data.get('to'))
        promote = data.get('promote', False)
        
        piece = game.get_piece(start[0], start[1])
        if not piece or piece['owner'] != owner:
             return jsonify({'status': 'error', 'message': 'Invalid piece'}), 400
             
        if not game.is_pseudo_valid_move(start, end, piece, owner):
             return jsonify({'status': 'error', 'message': 'Invalid move'}), 400
             
        if not game.simulate_move_check("move", start, end, owner, promote):
             return jsonify({'status': 'error', 'message': 'Illegal move (Check or Stuck)'}), 400
             
        game.make_move("move", start, end, owner, promote)
        
    elif move_type == 'drop':
        name = data.get('name')
        end = tuple(data.get('to'))
        
        if game.hands[owner].get(name, 0) <= 0:
             return jsonify({'status': 'error', 'message': 'No such piece in hand'}), 400
             
        if not game.simulate_move_check("drop", name, end, owner):
             return jsonify({'status': 'error', 'message': 'Illegal drop'}), 400
             
        game.make_move("drop", name, end, owner)
        
    game.switch_turn()
    
    if len(game.get_legal_moves(game.turn)) == 0:
        game.game_over = True
        winner = "Sente" if game.turn == GOTE else "Gote"
        return jsonify({'status': 'ok', 'game_over': True, 'winner': winner})

    return jsonify({'status': 'ok'})

@app.route('/api/cpu', methods=['POST'])
def cpu_move():
    if game.game_over or (game.vs_ai and game.turn != GOTE):
        return jsonify({'status': 'error', 'message': 'Not CPU turn'}), 400
        
    try:
        best_val, best_move = game.minimax(game, CPU_DEPTH, -float('inf'), float('inf'), True)
        if best_move:
            if best_move["type"] == "move":
                game.make_move("move", best_move["from"], best_move["to"], GOTE, best_move["promote"])
            else:
                game.make_move("drop", best_move["name"], best_move["to"], GOTE)
            game.switch_turn()
            
            if len(game.get_legal_moves(game.turn)) == 0:
                game.game_over = True
                return jsonify({'status': 'ok', 'game_over': True, 'winner': 'Gote'})
                
            return jsonify({'status': 'ok', 'move': best_move})
        else:
            game.game_over = True
            return jsonify({'status': 'ok', 'game_over': True, 'winner': 'Sente'}) 
    except Exception as e:
        print(e)
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/llm_move', methods=['POST'])
def llm_move():
    if not api_key:
        return jsonify({'status': 'error', 'message': 'API Key not configured'}), 500

    data = request.json
    sfen = data.get('sfen')
    turn = data.get('turn') # 1 or -1
    model_name = sente_model_name if turn == SENTE else gote_model_name
    
    # Prompt construction
    prompt = f"""
    You are playing Shogi (Japanese Chess).
    Current SFEN: {sfen}
    You are {'Sente (Black)' if turn == SENTE else 'Gote (White)'}.
    
    Think about the best move. 
    Explain your reasoning briefly in 1-2 sentences.
    Then, output the move in USI format (e.g., 7g7f, 8h2b+, B*5e).
    
    Format your response exactly like this:
    Reasoning: [Your reasoning]
    Move: [USI Move]
    """
    
    try:
        model = genai.GenerativeModel(model_name)
        response = model.generate_content(prompt)
        text = response.text
        
        # Simple parsing
        import re
        move_match = re.search(r"Move:\s*([^\s]+)", text)
        if move_match:
            usi_move = move_match.group(1).strip()
            # We need to convert USI to internal format for execution or return it to frontend to execute
            # Converting USI to internal format here is better for validation, but frontend logic expects "make_move"
            # Let's return the USI move and reasoning, and let frontend or helper helper convert it.
            # Actually, let's try to convert it here to ensure it's valid?
            # Creating a helper to convert USI to internal move would be good.
            # For now, let's return it and handle parsing carefully.
            return jsonify({'status': 'ok', 'usi': usi_move, 'reasoning': text, 'model': model_name})
        else:
             return jsonify({'status': 'error', 'message': 'Could not parse move from LLM', 'raw': text}), 500

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/check_promote', methods=['POST'])
def check_promote():
    data = request.json
    start = tuple(data.get('from'))
    end = tuple(data.get('to'))
    piece_name = data.get('name')
    
    can_promote = game.can_promote(start[1], end[1], game.turn, piece_name)
    
    return jsonify({'can_promote': can_promote})

if __name__ == '__main__':
    app.run(debug=True, port=5000)
