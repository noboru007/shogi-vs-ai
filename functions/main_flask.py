import os
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from game_logic import ShogiGame, SENTE, GOTE, CPU_DEPTH
import copy
import google.generativeai as genai
import sys
import logging

load_dotenv()

# Configure Gemini
api_key = os.getenv("GOOGLE_API_KEY")
if api_key:
    genai.configure(api_key=api_key)

app = Flask(__name__, static_url_path='', static_folder='static')

# Default settings
DEFAULT_SENTE_MODEL = "gemini-2.5-pro"
DEFAULT_GOTE_MODEL = "gemini-2.5-pro"

# Helper to reconstruct game from SFEN part of request
def game_from_request(data):
    sfen = data.get('sfen')
    vs_ai_flag = data.get('vs_ai', False) # Read vs_ai flag
    
    game = ShogiGame(vs_ai=vs_ai_flag)
    if sfen:
        game.from_sfen(sfen)
    return game, data # Return data to extract ai settings later

def get_full_state(game, ai_settings=None):
    if ai_settings is None:
        ai_settings = {"ai_vs_ai_mode": False} 
        
    return {
        'board': game.board,
        'hands': game.hands,
        'turn': game.turn,
        'game_over': game.game_over,
        'sfen': game.get_sfen(),
        'last_move': game.last_move,
        'vs_ai': game.vs_ai,
        'ai_vs_ai_mode': ai_settings.get('ai_vs_ai_mode') or ai_settings.get('ai_vs_ai', False),
        'sente_model': ai_settings.get('sente_model', DEFAULT_SENTE_MODEL),
        'gote_model': ai_settings.get('gote_model', DEFAULT_GOTE_MODEL)
    }

@app.route('/api/health')
def health_check():
    return jsonify({'status': 'ok'})

@app.route('/api/game', methods=['GET'])
def get_game_state():
    return jsonify({'status': 'ok', 'message': 'Server is stateless. Use local state.'})

@app.route('/api/reset', methods=['POST'])
def reset_game():
    data = request.json
    vs_cpu = data.get('vs_ai', True)
    ai_vs_ai_mode = data.get('ai_vs_ai', False)
    
    if ai_vs_ai_mode:
        vs_cpu = False

    game = ShogiGame(vs_ai=vs_cpu)
    
    return jsonify({
        'status': 'ok',
        'game_state': get_full_state(game, data)
    })

# Helper: Parse USI string to internal move dict
def parse_usi_string(usi):
    files = "987654321"
    ranks = "abcdefghi"
    
    # Drop: P*5e
    if '*' in usi:
        name_char, pos_str = usi.split('*')
        from game_logic import SFEN_MAP
        CHAR_TO_KANJI = {v: k for k, v in SFEN_MAP.items()}
        name = CHAR_TO_KANJI.get(name_char.upper(), name_char)
        
        tx = files.index(pos_str[0])
        ty = ranks.index(pos_str[1])
        
        return {
            'type': 'drop',
            'name': name,
            'to': [tx, ty]
        }
    
    # Move: 7g7f or 7g7f+
    else:
        promote = False
        if usi.endswith('+'):
            promote = True
            usi = usi[:-1]
            
        sx = files.index(usi[0])
        sy = ranks.index(usi[1])
        tx = files.index(usi[2])
        ty = ranks.index(usi[3])
        
        return {
            'type': 'move',
            'from': [sx, sy],
            'to': [tx, ty],
            'promote': promote
        }

@app.route('/api/move', methods=['POST'])
def make_move():
    data = request.json
    try:
        game, req_data = game_from_request(data)
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Invalid SFEN: {e}'}), 400

    if game.game_over:
        return jsonify({'status': 'error', 'message': 'Game Over'}), 400
    
    # === USI Support ===
    if 'usi' in data:
        try:
            parsed = parse_usi_string(data['usi'])
            # Merge parsed data into main vars - be careful not to lose context like 'vs_ai' which is in req_data/data
            move_type = parsed['type']
            # We only need move details from parsed
            data.update(parsed) # Update data with parsed move details
        except Exception as e:
            return jsonify({'status': 'error', 'message': f'Invalid USI: {str(e)}'}), 400
    else:
        move_type = data.get('type')
        
    owner = game.turn 
    ai_vs_ai_mode = req_data.get('ai_vs_ai', False)
    
    if not ai_vs_ai_mode:
        if owner != SENTE and game.vs_ai:
             return jsonify({'status': 'error', 'message': 'Not your turn'}), 400

    if move_type == 'move':
        moves = game.get_legal_moves(game.turn)
        legal = False
        start = tuple(data.get('from'))
        end = tuple(data.get('to'))
        promote = data.get('promote', False)

        for m in moves:
            if m['type'] == 'move' and m['from'] == start and m['to'] == end:
                if m['promote'] == promote:
                    legal = True
                    break
        
        if legal:
            game.make_move('move', start, end, game.turn, promote)
            game.switch_turn()
            
            if len(game.get_legal_moves(game.turn)) == 0:
                game.game_over = True
            
            return jsonify({
                'status': 'ok', 
                'game_state': get_full_state(game, ai_settings=req_data) 
            })
            
    elif move_type == 'drop':
        legal = False
        name = data.get('name')
        to_pos = tuple(data.get('to'))
        moves = game.get_legal_moves(game.turn)
        for m in moves:
            if m['type'] == 'drop' and m['name'] == name and m['to'] == to_pos:
                legal = True
                break
                
        if legal:
            game.make_move('drop', name, to_pos, game.turn)
            game.switch_turn()
            
            if len(game.get_legal_moves(game.turn)) == 0:
                game.game_over = True

            return jsonify({
                'status': 'ok', 
                'game_state': get_full_state(game, ai_settings=req_data) 
            })
        else:
             # Debug info
             kanji_name = name 
             hand_count = game.hands[game.turn].get(kanji_name, 0)
             debug_info = {
                 'reason': 'Drop failed',
                 'name': name,
                 'end': to_pos,
                 'hand_count': hand_count
             }
             
        return jsonify({'status': 'error', 'message': 'Invalid or Illegal move', 'debug': str(debug_info)}), 400

    return jsonify({'status': 'error', 'message': 'Unknown move type'}), 400

@app.route('/api/cpu', methods=['POST'])
def cpu_move():
    data = request.json
    try:
        game, req_data = game_from_request(data)
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Invalid SFEN: {e}'}), 400
    
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
                
            return jsonify({
                'status': 'ok', 
                'move': best_move,
                'game_state': get_full_state(game, ai_settings=req_data)
            })
        else:
            game.game_over = True
            return jsonify({
                'status': 'ok', 
                'game_over': True, 
                'winner': 'Sente',
                'game_state': get_full_state(game, ai_settings=req_data)
            }) 
    except Exception as e:
        import traceback
        return jsonify({'status': 'error', 'message': str(e), 'trace': traceback.format_exc()}), 500

# Helper for USI conversion
def to_usi(move):
    files = "987654321"
    ranks = "abcdefghi"
    
    if move["type"] == "drop":
        from game_logic import SFEN_MAP
        char = SFEN_MAP.get(move["name"])
        if not char: return None
        if char.startswith("+"): char = char[1:] 
        tx, ty = move["to"]
        return f"{char}*{files[tx]}{ranks[ty]}"
        
    elif move["type"] == "move":
        # Move: 7g7f or 7g7f+
        sx, sy = move["from"]
        tx, ty = move["to"]
        promote = "+" if move["promote"] else ""
        return f"{files[sx]}{ranks[sy]}{files[tx]}{ranks[ty]}{promote}"
    return None

@app.route('/api/llm_move', methods=['POST'])
def llm_move():
    session_id = request.headers.get('X-Session-ID', 'default_session')
    logging.info(f"DEBUG: llm_move called (Stateless) Session: {session_id}")
    
    if not api_key:
        logging.error("ERROR: API Key not configured")
        return jsonify({'status': 'error', 'message': 'API Key not configured'}), 500

    try:
        data = request.json
        try:
            game, req_data = game_from_request(data)
        except Exception as e:
            return jsonify({'status': 'error', 'message': f'Invalid SFEN: {e}'}), 400

        sfen = game.get_sfen()
        turn = game.turn
        
        sente_model_name = req_data.get('sente_model', DEFAULT_SENTE_MODEL)
        gote_model_name = req_data.get('gote_model', DEFAULT_GOTE_MODEL)
        model_name = sente_model_name if turn == SENTE else gote_model_name
        
        logging.info(f"DEBUG: Stateless Turn: {turn}, Model: {model_name}")

        legal_moves = game.get_legal_moves(turn)
        legal_moves_usi = []
        for m in legal_moves:
            u = to_usi(m)
            if u: legal_moves_usi.append(u)
            
        legal_moves_str = ", ".join(legal_moves_usi)
        
        base_prompt = f"""
        あなたは最強のAI将棋棋士です。
        現在の局面(SFEN): {sfen}
        あなたの手番: {'先手 (Sente)' if turn == SENTE else '後手 (Gote)'}。
        
        合法手リスト: {legal_moves_str}
        
        上記リストの中から、この局面におけるベストな一手を選んでください。
        なお、リストに含まれない手は絶対に出力しないでください。
        
        回答フォーマット:
        Move: [USI Move]
        """
        
        logging.info("DEBUG: Configuring Model...")
        model = genai.GenerativeModel(model_name)
        chat = model.start_chat(history=[])
        
        max_retries = 1 
        last_error = ""
        
        for attempt in range(max_retries):
            prompt = base_prompt
            if last_error:
                prompt += f"\n\n前回の回答エラー: {last_error}\nもう一度、合法手リストから正しい手を選んでください。"
            
            logging.info(f"DEBUG: Sending Prompt (Attempt {attempt+1})...")
            try:
                response = chat.send_message(prompt)
                text = response.text
                logging.info(f"DEBUG: LLM Response len: {len(text)}")
                
                import re
                move_match = re.search(r"Move:\s*([^\s]+)", text)
                if move_match:
                    usi_move = move_match.group(1).strip()
                    logging.info(f"DEBUG: Parsed USI: {usi_move}")
                    
                    if usi_move in legal_moves_usi:
                        parsed_move = parse_usi_string(usi_move) 
                        logging.info(f"DEBUG: Pre-Move SFEN: {game.get_sfen()}")
                        
                        move_type = parsed_move['type']
                        if move_type == 'move':
                            game.make_move('move', parsed_move['from'], parsed_move['to'], turn, parsed_move['promote'])
                        elif move_type == 'drop':
                            game.make_move('drop', parsed_move['name'], parsed_move['to'], turn)
                        
                        game.switch_turn()
                        logging.info(f"DEBUG: Post-Move SFEN: {game.get_sfen()}")
                        
                        winner = None
                        if len(game.get_legal_moves(game.turn)) == 0:
                            game.game_over = True
                            winner = "Sente" if game.turn == GOTE else "Gote"
                            logging.info(f"DEBUG: Game Over. Winner: {winner}")
                        
                        response_data = {
                            'status': 'ok',
                            'move': parsed_move,
                            'usi': usi_move,
                            'model': model_name,
                            'game_state': {
                                'board': game.board,
                                'hands': game.hands,
                                'turn': game.turn,
                                'game_over': game.game_over,
                                'sfen': game.get_sfen(),
                                'last_move': game.last_move,
                                'vs_ai': game.vs_ai,
                                'ai_vs_ai_mode': True,
                                'sente_model': sente_model_name,
                                'gote_model': gote_model_name
                            }
                        }
                        
                        if winner:
                             response_data['game_over'] = True
                             response_data['winner'] = winner
                             
                        return jsonify(response_data)
                        
                    else:
                        logging.warning(f"DEBUG: Invalid Move: {usi_move}")
                        last_error = f"手 '{usi_move}' は合法手リストに含まれていません。リスト: {legal_moves_str}"
                else:
                     logging.warning("DEBUG: No Move found in response")
                     last_error = "回答から 'Move:' が見つかりませんでした。"

            except Exception as e:
                logging.error(f"ERROR inside attempt loop: {e}")
                return jsonify({'status': 'error', 'message': str(e)}), 500

        logging.error(f"ERROR: Max retries reached. Last Error: {last_error}")
        return jsonify({'status': 'error', 'message': 'LLM failed to produce a valid move.', 'last_error': last_error, 'raw': text}), 500

    except Exception as e:
        logging.critical(f"CRITICAL ERROR in llm_move: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/check_promote', methods=['POST'])
def check_promote():
    data = request.json
    try:
        game, _ = game_from_request(data)
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Invalid SFEN: {e}'}), 400

    start = tuple(data.get('from'))
    end = tuple(data.get('to'))
    piece_name = data.get('name')
    
    can_promote = game.can_promote(start[1], end[1], game.turn, piece_name)
    
    return jsonify({'can_promote': can_promote})

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    app.run(debug=True, port=5000)
