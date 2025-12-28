import os
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from game_logic import ShogiGame, SENTE, GOTE, CPU_DEPTH
import copy
import google.generativeai as genai
import sys
import logging
import platform
import requests # Added for raw API calls
import time # Added for polling

# Custom Logger wrapper to force flush
def log_info(msg):
    print(msg, flush=True)

def log_error(msg):
    print(f"ERROR: {msg}", file=sys.stderr, flush=True)


load_dotenv()

# Configure Gemini
api_key = os.getenv("GOOGLE_API_KEY")
if api_key:
    genai.configure(api_key=api_key)

app = Flask(__name__, static_url_path='', static_folder='../static')
CORS(app) # Enable CORS for all routes

# Default settings
DEFAULT_SENTE_MODEL = "gemini-2.5-pro"
DEFAULT_GOTE_MODEL = "gemini-2.5-pro"

# Helper to reconstruct game from SFEN part of request
def game_from_request(data):
    sfen = data.get('sfen')
    vs_ai_flag = data.get('vs_ai', False) 
    
    game = ShogiGame(vs_ai=vs_ai_flag)
    if sfen:
        game.from_sfen(sfen)
    return game, data 

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

@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization,X-Session-ID')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')

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
    sfen_in = data.get('sfen')
    
    if ai_vs_ai_mode:
        vs_cpu = False

    game = ShogiGame(vs_ai=vs_cpu)
    
    if sfen_in:
        try:
            game.from_sfen(sfen_in)
        except Exception as e:
            return jsonify({'status': 'error', 'message': f'Invalid SFEN: {e}'}), 400
    
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
            move_type = parsed['type']
            data.update(parsed) 
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
            # Generate JP string BEFORE making move
            move_dict = {'type': 'move', 'from': start, 'to': end, 'promote': promote}
            move_str_ja = get_japanese_move_str(game, move_dict)
            current_move_count = game.move_count

            game.make_move('move', start, end, game.turn, promote)
            game.switch_turn()
            
            if len(game.get_legal_moves(game.turn)) == 0:
                game.game_over = True
            
            return jsonify({
                'status': 'ok', 
                'game_state': get_full_state(game, ai_settings=req_data),
                'move_str_ja': move_str_ja,
                'move_count': current_move_count
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
            # Generate JP string BEFORE making move
            move_dict = {'type': 'drop', 'name': name, 'to': to_pos}
            move_str_ja = get_japanese_move_str(game, move_dict)
            current_move_count = game.move_count

            game.make_move('drop', name, to_pos, game.turn)
            game.switch_turn()
            
            if len(game.get_legal_moves(game.turn)) == 0:
                game.game_over = True

            return jsonify({
                'status': 'ok', 
                'game_state': get_full_state(game, ai_settings=req_data),
                'move_str_ja': move_str_ja,
                'move_count': current_move_count
            })
        else:
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

# Helper: Convert move to Japanese notation
def get_japanese_move_str(game, move_dict):
    if not move_dict: return ""
    
    files = "１２３４５６７８９" # Full-width numbers for columns? Or simple? Standard is Arabic 7, Kanji 六.
    # Usually: 7六歩. 
    # Let's use Arabic for files to match standard input, or full-width? 
    # Standards vary. "７六歩" or "7六歩". User asked for "3四歩" (Half-width number).
    files_map = ["9", "8", "7", "6", "5", "4", "3", "2", "1"]
    ranks_map = ["一", "二", "三", "四", "五", "六", "七", "八", "九"]
    
    if move_dict['type'] == 'drop':
        name = move_dict['name']
        val = move_dict['to']
        tx, ty = val
        # Drop is usually "Piece打" e.g. "3四歩打"
        return f"{files_map[tx]}{ranks_map[ty]}{name}打"
        
    elif move_dict['type'] == 'move':
        # Need source piece name
        sx, sy = move_dict['from']
        tx, ty = move_dict['to']
        promote = move_dict.get('promote', False)
        
        piece = game.board[sy][sx]
        name = piece['name'] if piece else "?"
        
        suffix = "成" if promote else ""
        return f"{files_map[tx]}{ranks_map[ty]}{name}{suffix}"
        
    return ""

@app.route('/api/cpu', methods=['POST'])
def cpu_move():
    data = request.json
    try:
        game, req_data = game_from_request(data)
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Invalid SFEN: {e}'}), 400
    
    if game.game_over or (game.vs_ai and game.turn != GOTE):
        return jsonify({'status': 'error', 'message': 'Not CPU turn'}), 400
        
    # Determine if maximizing (Gote) or minimizing (Sente)
    # minimax is designed such that True = Gote (Maximize), False = Sente (Minimize)
    is_maximizing = (game.turn == GOTE)
    
    try:
        best_val, best_move = game.minimax(game, CPU_DEPTH, -float('inf'), float('inf'), is_maximizing)
        if best_move:
            # Generate JP string BEFORE making move (to see source piece)
            move_str_ja = get_japanese_move_str(game, best_move)
            current_move_count = game.move_count
            
            if best_move["type"] == "move":
                game.make_move("move", best_move["from"], best_move["to"], game.turn, best_move["promote"])
            else:
                game.make_move("drop", best_move["name"], best_move["to"], game.turn)
            
            game.switch_turn()
            if len(game.get_legal_moves(game.turn)) == 0:
                game.game_over = True
                
            return jsonify({
                'status': 'ok', 
                'move': best_move,
                'move_str_ja': move_str_ja,
                'move_count': current_move_count,
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
    log_info(f"DEBUG: llm_move called (Stateless) Session: {session_id}")
    
    if not api_key:
        log_error("ERROR: API Key not configured")
        return jsonify({'status': 'error', 'message': 'API Key not configured'}), 500

    try:
        data = request.json
        try:
            game, req_data = game_from_request(data)
        except Exception as e:
            return jsonify({'status': 'error', 'message': f'Invalid SFEN: {e}'}), 400

        sfen = game.get_sfen()
        turn = game.turn
        
        ai_vs_ai_mode = req_data.get('ai_vs_ai_mode', False) or req_data.get('ai_vs_ai', False)
        sente_model = req_data.get('sente_model', DEFAULT_SENTE_MODEL)
        gote_model = req_data.get('gote_model', DEFAULT_GOTE_MODEL)
        
        sente_model_name = sente_model
        gote_model_name = gote_model
        model_name = sente_model_name if turn == SENTE else gote_model_name
        
        log_info(f"DEBUG: Stateless Turn: {turn}, Model: {model_name}")

        legal_moves = game.get_legal_moves(turn)
        legal_moves_usi = []
        for m in legal_moves:
            u = to_usi(m)
            if u: legal_moves_usi.append(u)
            
        legal_moves_str = ", ".join(legal_moves_usi)
        
        # Explicitly describe pieces in hand for the AI to prevent hallucination
        hand_pieces = []
        current_hand = game.hands[turn]
        for p, count in current_hand.items():
            if count > 0:
                hand_pieces.append(f"{p} x{count}")
        hand_desc = ", ".join(hand_pieces) if hand_pieces else "None (なし)"
        
        turn_str = '先手 (Sente)' if turn == SENTE else '後手 (Gote)'
        
        piece_guide = ""
        if turn == SENTE:
             piece_guide = "あなたの駒はSFEN上で大文字(P, L, N, S, G, B, R, K)で表されます。\n        相手の駒は小文字です。\n        あなたは盤面下側(Rank 9)から上方向(Rank 1)に向かって攻めます。"
        else:
             piece_guide = "あなたの駒はSFEN上で小文字(p, l, n, s, g, b, r, k)で表されます。\n        相手の駒は大文字です。\n        あなたは盤面上側(Rank 1)から下方向(Rank 9)に向かって攻めます。"

        # === Construct Prompts ===
        
        # System Prompt: Role, Rules, Format
        system_prompt = f"""
        あなたは最強のAI将棋棋士です。
        {piece_guide}

        ルール:
        1. SFENを正確に解析して、あなたの駒と相手の駒を正確に把握すること。
        2. 自分の駒以外の駒（相手の駒）は動かせない。
        3. 持ち駒以外の駒も勝手に使えない。
        4. 回答は必ず指定されたフォーマットのみを出力すること。余計な挨拶は不要。

        回答フォーマット:
        Reasoning: [3行以内の簡潔な説明]
        Move: [USI Move]（例：7g7f。持ち駒がない場合は打てません）
        """

        # User Prompt: Current State
        user_prompt = f"""
        現在の局面(SFEN): {sfen}
        あなたの手番: {turn_str}。
        あなたの持ち駒: {hand_desc}
        
        この局面におけるベストな次の一手を選び、将棋のUSI形式（例：7776ではなく7g7f）で回答してください。
        """
        
        # Configure Gemini
        import google.generativeai as genai
        
        # Configure OpenAI
        from openai import OpenAI
        openai_client = None
        openai_api_key = os.getenv("OPENAI_API_KEY")
        if openai_api_key:
            openai_client = OpenAI(api_key=openai_api_key)
            
        max_retries_raw = data.get('max_retries', 2)
        try:
            max_retries = int(max_retries_raw)
            if max_retries < 1: max_retries = 1
            if max_retries > 3: max_retries = 3
        except:
            max_retries = 2 
        last_error = ""

        for attempt in range(max_retries):
            # Combined prompt for fallback or non-separated models (though we will use separation where possible)
            current_user_prompt = user_prompt
            if last_error:
                 current_user_prompt += f"\n\n前回の回答エラー: {last_error}\nもう一度正しい手を選んでください。"
            
            log_info(f"DEBUG: Turn: {turn_str}, SFEN: {sfen}")
            
            text = ""
            try:
                if model_name.startswith("gpt") or model_name.startswith("o"):
                    if not openai_client:
                        raise Exception("OpenAI API Key not set")
                        
                    # log_info(f"DEBUG: Calling OpenAI API with {model_name}...")
                    
                    if "gpt-5" in model_name or "codex" in model_name:
                        # Special handling for gpt-5-pro (v1/responses)
                        url = "https://api.openai.com/v1/responses"
                        headers = {
                            "Authorization": f"Bearer {openai_api_key}",
                            "Content-Type": "application/json"
                        }
                        payload = {
                            "model": model_name,
                            "input": [
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": current_user_prompt}
                            ],
                            "temperature": 1 # Default for pro/reasoning models
                        }
                        
                        resp = requests.post(url, headers=headers, json=payload)
                        if resp.status_code != 200:
                             raise Exception(f"OpenAI v1/responses error: {resp.status_code} {resp.text}")
                        
                        resp_json = resp.json()
                        
                        # Debug log to verify deployment
                        # Debug log to verify deployment and structure
                        log_info(f"DEBUG: Deployment 11 - v1/responses keys: {list(resp_json.keys())}")
                        
                        # Handle async/polling if result is not immediate
                        # Modified condition to be more explicit about 'reasoning' type
                        should_poll = False
                        if 'id' in resp_json:
                             if 'choices' not in resp_json and 'output' not in resp_json:
                                 should_poll = True
                             elif resp_json.get('type') == 'reasoning':
                                 should_poll = True
                        
                        if should_poll:
                            # Likely async response (type: reasoning, etc.)
                            response_id = resp_json['id']
                            log_info(f"DEBUG: Async Response ID: {response_id}. Polling...")
                            
                            poll_url = f"https://api.openai.com/v1/responses/{response_id}"
                            param_headers = headers.copy() # same headers
                            
                            max_retries = 30 # 60 seconds
                            for i in range(max_retries):
                                time.sleep(2)
                                poll_resp = requests.get(poll_url, headers=param_headers)
                                if poll_resp.status_code == 200:
                                    poll_data = poll_resp.json()
                                    # Check if done
                                    # Assuming 'status' field or presence of output
                                    if 'choices' in poll_data or 'output' in poll_data:
                                        resp_json = poll_data
                                        log_info(f"DEBUG: Poll success after {i+1} tries.")
                                        break
                                    elif poll_data.get('status') == 'failed':
                                        raise Exception("Async response processing failed.")
                                    # else continue polling
                                else:
                                    log_info(f"DEBUG: Poll failed {poll_resp.status_code}")
                            else:
                                raise Exception("Async response timed out.")
                        else:
                             log_info(f"DEBUG: Polling Skipped. resp_json={str(resp_json)}")

                        # Parsing logic for v1/responses or standard chat
                        if 'choices' in resp_json:
                            text = resp_json['choices'][0]['message']['content']
                        elif 'output' in resp_json:
                             # v1/responses: output is a list of events/messages
                             out_list = resp_json['output']
                             text = ""
                             found_content = False
                             
                             if isinstance(out_list, list):
                                 # Iterate backwards to find the final message, or check formatting
                                 for item in out_list:
                                     if isinstance(item, dict):
                                         # Check for message with content
                                         if item.get('type') == 'message' and 'content' in item:
                                             stats_content = item['content']
                                             # content can be string or list of blocks
                                             if isinstance(stats_content, str):
                                                 text = stats_content
                                                 found_content = True
                                             elif isinstance(stats_content, list):
                                                 for block in stats_content:
                                                     if block.get('type') == 'output_text':
                                                         text += block.get('text', '')
                                                         found_content = True
                                             if found_content: break
                             
                             if not found_content:
                                 # Fallback: dump the whole list str so we can debug if logic failed
                                 text = str(out_list)

                        else:
                            # Fallback if schema is different
                            text = str(resp_json)

                        log_info(f"DEBUG: {model_name} Response len: {len(text)}")
                    
                    else:
                        # Standard v1/chat/completions
                        # o-series and gpt-5 often require default temperature (1)
                        temp = 0.7
                        if model_name.startswith("o") or model_name.startswith("gpt-5"):
                            temp = 1
                        
                        response = openai_client.chat.completions.create(
                            model=model_name,
                            messages=[
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": current_user_prompt}
                            ],
                            temperature=temp
                        )
                        text = response.choices[0].message.content
                        log_info(f"DEBUG: OpenAI Response len: {len(text)}")
                else:
                    # Gemini Call
                    log_info("DEBUG: Configuring Gemini Model...")
                    model = genai.GenerativeModel(
                        model_name,
                        system_instruction=system_prompt
                    )
                    chat = model.start_chat(history=[])
                    
                    try:
                        response = chat.send_message(current_user_prompt)
                        text = response.text
                    except Exception as e:
                        # Handle safety blocks or other non-text responses
                        log_info(f"DEBUG: Gemini Error or Block: {e}")
                        # Check for parts or safety feedback if available
                        if hasattr(response, 'candidates') and response.candidates:
                            log_info(f"DEBUG: Candidate info: {response.candidates[0]}")
                        raise e # re-raise to trigger fallback

                    log_info(f"DEBUG: Gemini Response len: {len(text)}")

                log_info(f"DEBUG: Raw LLM Response: {text}")
                
                import re
                reasoning = ""
                # Improved regex to handle "Reasoning: **" and multiline content until "Move:" 
                # Lookahead checks for "Move:" optionally preceded by "*" or whitespace
                reasoning_match = re.search(r"Reasoning:[\s\*]*([\s\S]+?)(?=[\s\*]*Move:|http|$)", text, re.IGNORECASE)
                if reasoning_match:
                    reasoning = reasoning_match.group(1).strip()
                    # Remove leading/trailing asterisks if present
                    reasoning = reasoning.strip("* \t\n")

                # Move regex: Ignore leading ** or whitespace. Ensure move starts with alphanumeric or + (not *)
                move_match = re.search(r"Move:[\s\*]*([a-zA-Z0-9\+][a-zA-Z0-9\+\*]*)", text)
                
                usi_move = None
                parsed_move = None
                move_executed = False

                if move_match:
                    usi_move = move_match.group(1).strip().strip("`'\"")
                    # log_info(f"DEBUG: Parsed USI: {usi_move}, Reasoning: {reasoning}")
                    try:
                        parsed_move = parse_usi_string(usi_move)
                    except:
                        log_info(f"DEBUG: Failed to parse USI: {usi_move}")

                    # 1. Check if strictly legal
                    if usi_move in legal_moves_usi:
                        move_executed = True
                    # 2. Check if physically possible (Pseudo-legal)
                    elif parsed_move:
                         move_type = parsed_move['type']
                         is_possible = False
                         if move_type == 'move':
                             is_possible = game.is_physically_possible('move', parsed_move['from'], parsed_move['to'], turn, parsed_move['promote'])
                         elif move_type == 'drop':
                             is_possible = game.is_physically_possible('drop', parsed_move['name'], parsed_move['to'], turn)
                         
                         if is_possible:
                             log_info(f"DEBUG: Permitting physically possible but strictly illegal move: {usi_move}")
                             move_executed = True
                         else:
                             log_info(f"DEBUG: Move is physically impossible: {usi_move}")
                else:
                    log_info(f"DEBUG: No USI found in response. Full Response: {text}")

                # Execute Move or Fallback
                move_str_ja = ""
                current_move_count = game.move_count
                
                if move_executed and parsed_move:
                    move_str_ja = get_japanese_move_str(game, parsed_move)
                    move_type = parsed_move['type']
                    if move_type == 'move':
                        game.make_move('move', parsed_move['from'], parsed_move['to'], turn, parsed_move['promote'])
                    elif move_type == 'drop':
                        game.make_move('drop', parsed_move['name'], parsed_move['to'], turn)
                    
                    game.switch_turn()
                    log_info(f"DEBUG: Post-Move SFEN: {game.get_sfen()}")
                else:
                    # 3. Invalid Move or No Move -> Retry
                    log_info("DEBUG: Invalid move or no move found. Retrying...")
                    last_error = f"Invalid/Illegal move received: {usi_move}. Reasoning: {reasoning}"
                    continue

                winner = None
                if len(game.get_legal_moves(game.turn)) == 0:
                    game.game_over = True
                    winner = "Sente" if game.turn == GOTE else "Gote"
                    log_info(f"DEBUG: Game Over. Winner: {winner}")
                
                response_data = {
                    'status': 'ok',
                    'move': parsed_move, 
                    'usi': usi_move,
                    'move_str_ja': move_str_ja,
                    'move_count': current_move_count,
                    'reasoning': reasoning, 
                    'model': model_name,
                    'game_state': get_full_state(game, {'ai_vs_ai_mode': ai_vs_ai_mode, 'sente_model': sente_model, 'gote_model': gote_model})
                }
                return jsonify(response_data)

            except Exception as e:
                log_error(f"ERROR inside attempt loop: {e}")
                last_error = str(e)
                continue # Retry

        log_error(f"ERROR: Max retries reached. Last Error: {last_error}. Switching to CPU Fallback.")
        
        # CPU Fallback Logic (Duplicate of logic above)
        best_move = game.get_random_move()
        move_str_ja = ""
        current_move_count = game.move_count
        parsed_move = None
        usi_move = "CPU_FALLBACK_ERROR"
        reasoning = f"(エラーが発生したため、CPUが代打ちしました: {last_error})"

        if best_move:
             move_str_ja = get_japanese_move_str(game, best_move)
             move_type = best_move['type']
             start_or_name = best_move['from'] if move_type == 'move' else best_move['name']
             end = best_move['to']
             promote = best_move.get('promote', False)
             
             game.make_move(move_type, start_or_name, end, turn, promote)
             game.switch_turn()
             parsed_move = best_move
             
        if len(game.get_legal_moves(game.turn)) == 0:
             game.game_over = True
             
        response_data = {
            'status': 'ok',
            'move': parsed_move, 
            'usi': usi_move,
            'move_str_ja': move_str_ja,
            'move_count': current_move_count,
            'reasoning': reasoning, 
            'model': f"{model_name} (Fallback)",
            'game_state': get_full_state(game, {'ai_vs_ai_mode': ai_vs_ai_mode, 'sente_model': sente_model, 'gote_model': gote_model})
        }
        return jsonify(response_data)

    except Exception as e:
        log_error(f"CRITICAL ERROR in llm_move: {e}")
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
    # Keep basicConfig for local debug, but file-level logger helpers use print
    logging.basicConfig(level=logging.INFO)
    app.run(debug=True, port=5000)
