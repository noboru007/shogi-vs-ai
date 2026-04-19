import os
import re
import json
import sys
import logging
import time
import traceback

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import google.generativeai as genai
import requests

from game_logic import ShogiGame, SENTE, GOTE, parse_usi_string, to_usi

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

# Configure logger
logger = logging.getLogger("shogi")
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger.addHandler(_handler)

load_dotenv()

# Configure Gemini
api_key = os.getenv("GOOGLE_API_KEY")
if api_key:
    genai.configure(api_key=api_key)

app = Flask(__name__, static_url_path='', static_folder='../static')
CORS(app) # Enable CORS for all routes

# Default settings
DEFAULT_SENTE_MODEL = "gemini-3.1-pro-preview"
DEFAULT_GOTE_MODEL = "gemini-3.1-pro-preview"

# TTS Voice Settings per LLM model
# Each entry: system_prompt for voice style, voice name from Gemini TTS
TTS_VOICE_CONFIG = {
    "gemini-3.1-pro-preview": {
        "system_prompt": "将棋の解説をする。18歳の高音の声で、フレンドリーで楽しそうな、少し早口のトーンで。",
        "voice": "Leda"
    },
    "gemini-3-pro-preview": {
        "system_prompt": "将棋の解説をする。18歳の高音の声で、フレンドリーで楽しそうな、少し早口のトーンで。",
        "voice": "Leda"
    },
    "gemini-3-flash-preview": {
        "system_prompt": "将棋の解説をする。18歳の高音の声で、フレンドリーで楽しそうな、少し早口のトーンで。",
        "voice": "Leda"
    },
    "gpt-5.4": {
        "system_prompt": "将棋の解説をする。28歳の、恋人に甘えるピロートークの、少し早口のトーンで。",
        "voice": "Leda"
    },
    "gpt-5.3-codex": {
        "system_prompt": "将棋の解説をする。28歳の、恋人に甘えるピロートークの、少し早口のトーンで。",
        "voice": "Leda"
    },
    "gpt-5.2": {
        "system_prompt": "将棋の解説をする。28歳の、恋人に甘えるピロートークの、少し早口のトーンで。",
        "voice": "Leda"
    },
    "gpt-5.2-high": {
        "system_prompt": "将棋の解説をする。28歳の、恋人に甘えるピロートークの、少し早口のトーンで。",
        "voice": "Despina"
    },
    "claude-opus-4-7": {
        "system_prompt": "将棋の解説をする。40歳のベテラン棋士のような威厳と温かみのあるが、少し早口なトーンで。",
        "voice": "Puck"
    },
    "claude-opus-4-6": {
        "system_prompt": "将棋の解説をする。40歳のベテラン棋士のような威厳と温かみのあるが、少し早口なトーンで。",
        "voice": "Puck"
    },
    "claude-sonnet-4-6": {
        "system_prompt": "将棋の解説をする。22歳の明るく柔らかい語り口で、少し早口なトーンで。",
        "voice": "Kore"
    },
    "default": {
        "system_prompt": "",
        "voice": "Sadaltager"
    }
}

TTS_MODEL = "gemini-3.1-flash-tts-preview"

def get_tts_config(model_name, is_fallback=False):
    """Get TTS config for the given LLM model name."""
    if is_fallback:
        return TTS_VOICE_CONFIG["default"]
    
    # Strip suffixes like -high, -low, -medium
    base_model = model_name
    for suffix in ["-high", "-medium", "-low"]:
        if base_model.endswith(suffix):
            base_model = base_model[:-len(suffix)]
            break
    
    # Check exact match first
    if base_model in TTS_VOICE_CONFIG:
        return TTS_VOICE_CONFIG[base_model]
    
    # Check partial match (e.g. "gemini-3-pro-preview" matches "gemini-3-pro")
    for key in TTS_VOICE_CONFIG:
        if key != "default" and base_model.startswith(key):
            return TTS_VOICE_CONFIG[key]
    
    return TTS_VOICE_CONFIG["default"]

def generate_tts_audio(text, model_name, turn, is_fallback=False):
    """
    Generate TTS audio using Gemini TTS API.
    Returns base64-encoded audio data or None on error.
    Retries up to 2 times on 500 errors.
    """
    google_api_key = os.getenv("GOOGLE_API_KEY")
    if not google_api_key:
        logger.error("TTS: GOOGLE_API_KEY not set")
        return None
    
    tts_config = get_tts_config(model_name, is_fallback)
    voice_name = tts_config["voice"]
    system_prompt = tts_config["system_prompt"]
    
    turn_str = "先手" if turn == SENTE else "後手"
    
    # Combine system prompt with the content to speak
    full_text = f"{system_prompt}\n\n{turn_str}：{text}"
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{TTS_MODEL}:generateContent?key={google_api_key}"
    
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{
            "parts": [{"text": full_text}]
        }],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "temperature": 0.5,
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {
                        "voiceName": voice_name
                    }
                }
            }
        }
    }
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            logger.info(f"TTS: Generating audio with voice={voice_name}, model={TTS_MODEL} (attempt {attempt+1}/{max_retries})")
            resp = requests.post(url, headers=headers, json=payload, timeout=60)
            
            if resp.status_code == 500 and attempt < max_retries - 1:
                logger.error(f"TTS API 500 error (attempt {attempt+1}), retrying in 2s...")
                time.sleep(2)
                continue
            
            if resp.status_code != 200:
                logger.error(f"TTS API error: {resp.status_code} {resp.text[:200]}")
                return None
            
            resp_json = resp.json()
            
            # Extract base64 audio data
            try:
                audio_data = resp_json['candidates'][0]['content']['parts'][0]['inlineData']['data']
                logger.info(f"TTS: Successfully generated audio, size={len(audio_data)} chars")
                return audio_data
            except (KeyError, IndexError) as e:
                logger.error(f"TTS: Failed to parse response: {e}")
                return None
                
        except requests.exceptions.Timeout:
            logger.error(f"TTS: Request timeout (attempt {attempt+1})")
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            return None
        except Exception as e:
            logger.error(f"TTS: Request failed: {e}")
            return None
    
    return None

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

# Favicon silencing
@app.route('/favicon.ico')
@app.route('/apple-touch-icon.png')
@app.route('/apple-touch-icon-precomposed.png')
def favicon_silence():
    return "", 204

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

    legal_moves = game.get_legal_moves(game.turn)

    if move_type == 'move':
        start = tuple(data.get('from'))
        end = tuple(data.get('to'))
        promote = data.get('promote', False)
        move_dict = {'type': 'move', 'from': start, 'to': end, 'promote': promote}
        is_legal = any(
            m['type'] == 'move' and m['from'] == start and m['to'] == end and m['promote'] == promote
            for m in legal_moves
        )
        make_args = ('move', start, end, game.turn, promote)
    elif move_type == 'drop':
        name = data.get('name')
        to_pos = tuple(data.get('to'))
        move_dict = {'type': 'drop', 'name': name, 'to': to_pos}
        is_legal = any(
            m['type'] == 'drop' and m['name'] == name and m['to'] == to_pos
            for m in legal_moves
        )
        make_args = ('drop', name, to_pos, game.turn)
    else:
        return jsonify({'status': 'error', 'message': 'Unknown move type'}), 400

    if not is_legal:
        return jsonify({'status': 'error', 'message': 'Invalid or Illegal move', 'debug': str(move_dict)}), 400

    move_str_ja = get_japanese_move_str(game, move_dict)
    current_move_count = game.move_count
    game.make_move(*make_args)
    game.switch_turn()

    if len(game.get_legal_moves(game.turn)) == 0:
        game.game_over = True

    return jsonify({
        'status': 'ok',
        'game_state': get_full_state(game, ai_settings=req_data),
        'move_str_ja': move_str_ja,
        'move_count': current_move_count
    })

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
        logger.info("CPU Thinking (Iterative Deepening)...")
        best_val, best_move = game.iterative_deepening(is_maximizing)
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
        return jsonify({'status': 'error', 'message': str(e), 'trace': traceback.format_exc()}), 500


# ========== LLM Move Helper Functions ==========

def parse_model_name(model_name):
    """Parse model name to extract base name and reasoning level."""
    display_name = model_name
    reasoning_level = None
    
    for suffix, level in [("-high", "high"), ("-medium", "medium"), ("-low", "low")]:
        if model_name.endswith(suffix):
            model_name = model_name[:-len(suffix)]
            reasoning_level = level
            break
    
    return model_name, display_name, reasoning_level


def format_legal_moves_grouped(legal_moves_usi):
    """Group legal moves by source square (or as drops) for readable prompt display.

    出力例:
        8b発: 8b9b, 8b7b, 8b6b, 8b5b, 8b4b, 8b3b
        7c発: 7c7d
        打: P*5e, P*5f
    """
    from_piece = {}
    drops = []
    for m in legal_moves_usi:
        if "*" in m:
            drops.append(m)
        else:
            src = m[:2]
            from_piece.setdefault(src, []).append(m)
    lines = []
    for src in sorted(from_piece.keys()):
        lines.append(f"        {src}発: {', '.join(from_piece[src])}")
    if drops:
        lines.append(f"        打: {', '.join(drops)}")
    return "\n".join(lines)


def build_prompts(game, turn, req_data, legal_moves_usi):
    """Build system and user prompts based on instruction level.

    Returns (system_prompt, user_prompt, retry_legal_list).
    retry_legal_list is the grouped legal moves string for use in retry messages
    (advanced mode only; None for simple/medium to respect the user's challenge level).
    """
    sfen = game.get_sfen()
    
    # Describe pieces in hand for the AI
    hand_pieces = []
    current_hand = game.hands[turn]
    for p, count in current_hand.items():
        if count > 0:
            hand_pieces.append(f"{p} x{count}")
    hand_desc = ", ".join(hand_pieces) if hand_pieces else "None (なし)"
    
    turn_str = '先手 (Sente)' if turn == SENTE else '後手 (Gote)'
    
    if turn == SENTE:
        piece_guide = "あなた**先手**で駒はSFEN上で大文字(P, L, N, S, G, B, R, K)で表されます。\n        相手の駒は小文字です。\n        あなたは盤面下側(Rank 9)から上方向(Rank 1)に向かって攻めます。"
    else:
        piece_guide = "あなた**後手**で駒はSFEN上で小文字(p, l, n, s, g, b, r, k)で表されます。\n        相手の駒は大文字です。\n        あなたは盤面上側(Rank 1)から下方向(Rank 9)に向かって攻めます。"

    grouped_legal_str = format_legal_moves_grouped(legal_moves_usi)
    guide_instruction = f"""
        選択可能な合法手リスト（発駒マス別、合計 {len(legal_moves_usi)} 手）:
        ----
{grouped_legal_str}
        ----

        あなたは必ず上記リストの中から一手を選ばなければなりません。
        リストに無い手は反則負けとなります。
        特に、同じマスから複数の行き先が並んでいるブロック（例: 8b発の行）に
        自分の選んだ手が含まれていない場合、それは違法手です。
        """
    
    # Prompt components
    system_prompt_basic = f"""
        役割：あなたは最強のAI将棋棋士です。ユーザーから受け取ったSFENデータ（局面）の次の一手を打つ番です。
        タスク：ユーザーから受け取ったSFENデータのみに基づいて局面を推論し、最善の一手を出力してください。
        """
    system_prompt_piece_guide = f"""
        {piece_guide}
        {guide_instruction}
        """
    # Medium: Optimizer版 — 自力列挙を強調
    system_prompt_rules_medium = f"""
        ルール（思考プロセス）:
        1. SFENを正確に解析して、あなたの駒と相手の駒を正確に把握する。
        2. 外部から合法手リストは与えられない前提で、局面からあなたの全ての合法手を内部で列挙する。
        ※自玉に王手がかかっている場合、それを回避しない手は違法手として除外すること。
        3. 列挙した合法手の中から最善の一手を選択する。
        4. 選択した最善手（Move）と、その回答を以下の回答フォーマットの形式で出力する。
        ※最終的な回答は回答フォーマットに違反せず、指定されたUSI形式のみを出力すること。挨拶など余計な文章の出力は禁止する。

        制約：
        1. 回答は必ず日本語出力すること
        """
    # Advanced: 合法手リスト付き — 最終検証ステップを明示
    system_prompt_rules_advanced = f"""
        ルール（思考プロセス）:
        1. SFENを正確に解析し、自駒と相手駒を把握する。
        2. 与えられた合法手リストの中から最善手の候補を検討する。
        ※自玉に王手がかかっている場合、回避しない手は候補から除外する。
        3. 最善手を1つに絞る。
        4. 【最終検証 / 必須】出力直前に、選んだUSI文字列が合法手リストの要素と
           **完全一致**するかを1文字ずつ確認する。該当する発駒マスのブロックを
           再度読み、その中に選んだ手が存在することを確認すること。
           一致しない場合はステップ2に戻り再選択する。
           リストに無い手の出力は本タスクの最大の失敗である。
        5. 回答フォーマットに従って出力する。挨拶や余計な文章の出力は禁止。

        制約：
        1. 回答は必ず日本語出力すること
        """
    system_prompt_format = f"""
        回答フォーマット:
        Move: [USI Move]（例：7g7f、G*5h。持ち駒がない場合は打てません）
        解説: [この一手を選んだ理由を後付けのフレンドリーな**日本語**で3行以内。「2bと」ではなく、「2二と」のように表記してください。]
        """
    user_prompt_basic = f"""
        現在の局面(SFEN): {sfen}
        """
    user_prompt_hand = f"""
        あなたの手番: {turn_str}
        あなたの持ち駒: {hand_desc}
        """

    # Instruction level mapping
    ui_instruction_type = req_data.get('ai_instruction_type', 'medium')
    
    retry_legal_list = None
    if ui_instruction_type == "simple":
        system_prompt = system_prompt_basic + system_prompt_format
        user_prompt = user_prompt_basic
    elif ui_instruction_type == "advanced":
        system_prompt = system_prompt_basic + system_prompt_piece_guide + system_prompt_rules_advanced + system_prompt_format
        user_prompt = user_prompt_basic + user_prompt_hand
        retry_legal_list = grouped_legal_str
    else:  # "medium" (default)
        system_prompt = system_prompt_basic + system_prompt_rules_medium + system_prompt_format
        user_prompt = user_prompt_basic

    # Log Prompts at Game Start
    if game.move_count <= 2:
        logger.info(f"=== SYSTEM PROMPT (Start of Game) ===\n{system_prompt}\n=====================================")
        logger.info(f"=== USER PROMPT (Start of Game) ===\n{user_prompt}\n===================================")

    return system_prompt, user_prompt, retry_legal_list


def call_openai_api(model_name, system_prompt, user_prompt, reasoning_level):
    """Call OpenAI API (v1/responses or v1/chat/completions). Returns response text."""
    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not openai_api_key or OpenAI is None:
        raise Exception("OpenAI API Key not set or openai package not installed")
    
    reasoning_params = {}
    if reasoning_level:
        reasoning_params = {"effort": reasoning_level}
    
    if "gpt-5" in model_name or "codex" in model_name:
        return _call_openai_responses(model_name, system_prompt, user_prompt, openai_api_key, reasoning_params)
    else:
        return _call_openai_chat(model_name, system_prompt, user_prompt, openai_api_key, reasoning_level)


def _call_openai_responses(model_name, system_prompt, user_prompt, api_key, reasoning_params):
    """Call OpenAI v1/responses API with optional polling."""
    url = "https://api.openai.com/v1/responses"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model_name,
        "input": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
    }
    if reasoning_params:
        payload["reasoning"] = reasoning_params

    resp = requests.post(url, headers=headers, json=payload, timeout=1200)
    if resp.status_code != 200:
        raise Exception(f"OpenAI v1/responses error: {resp.status_code} {resp.text}")
    
    resp_json = resp.json()
    logger.debug(f"v1/responses keys: {list(resp_json.keys())}")
    
    # Check if async polling is needed
    should_poll = False
    if 'id' in resp_json:
        if 'choices' not in resp_json and 'output' not in resp_json:
            should_poll = True
        elif resp_json.get('type') == 'reasoning':
            should_poll = True
    
    if should_poll:
        resp_json = _poll_openai_response(resp_json['id'], headers)

    return _extract_openai_text(resp_json)


def _poll_openai_response(response_id, headers):
    """Poll OpenAI async response until completion."""
    poll_url = f"https://api.openai.com/v1/responses/{response_id}"
    logger.debug(f"Async Response ID: {response_id}. Polling...")
    
    for i in range(240):  # Poll for up to 20 mins
        time.sleep(5)
        poll_resp = requests.get(poll_url, headers=headers, timeout=30)
        if poll_resp.status_code == 200:
            poll_data = poll_resp.json()
            if 'choices' in poll_data or 'output' in poll_data:
                logger.debug(f"Poll success after {i+1} tries.")
                return poll_data
            elif poll_data.get('status') == 'failed':
                raise Exception("Async response processing failed.")
        else:
            logger.debug(f"Poll failed {poll_resp.status_code}")
    
    raise Exception("Async response timed out.")


def _extract_openai_text(resp_json):
    """Extract text from OpenAI response JSON."""
    if 'choices' in resp_json:
        return resp_json['choices'][0]['message']['content']
    elif 'output' in resp_json:
        out_list = resp_json['output']
        text = ""
        if isinstance(out_list, list):
            for item in out_list:
                if isinstance(item, dict) and item.get('type') == 'message' and 'content' in item:
                    content = item['content']
                    if isinstance(content, str):
                        return content
                    elif isinstance(content, list):
                        for block in content:
                            if block.get('type') == 'output_text':
                                text += block.get('text', '')
                        if text:
                            return text
        return str(out_list)
    return str(resp_json)


def _call_openai_chat(model_name, system_prompt, user_prompt, api_key, reasoning_level):
    """Call OpenAI v1/chat/completions API."""
    client = OpenAI(api_key=api_key)
    
    kwargs = {}
    if reasoning_level:
        kwargs["reasoning_effort"] = reasoning_level
    
    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        **kwargs
    )
    return response.choices[0].message.content


def call_gemini_api(model_name, system_prompt, user_prompt, reasoning_level):
    """Call Gemini API (REST with thinking or SDK). Returns response text."""
    if reasoning_level:
        return _call_gemini_rest_with_thinking(model_name, system_prompt, user_prompt, reasoning_level)
    else:
        return _call_gemini_sdk(model_name, system_prompt, user_prompt)


def _call_gemini_rest_with_thinking(model_name, system_prompt, user_prompt, thinking_level):
    """Call Gemini REST API with thinking config."""
    google_api_key = os.getenv("GOOGLE_API_KEY")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={google_api_key}"
    
    headers = {"Content-Type": "application/json"}
    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "thinkingConfig": {
                "includeThoughts": True,
                "thinkingLevel": thinking_level
            }
        }
    }
    
    logger.debug(f"Calling Gemini REST API with Thinking (Level: {thinking_level})")
    resp = requests.post(url, headers=headers, json=payload, timeout=1200)
    
    if resp.status_code != 200:
        raise Exception(f"Gemini REST API error: {resp.status_code} {resp.text}")
    
    resp_json = resp.json()
    try:
        parts = resp_json['candidates'][0]['content']['parts']
        text = ""
        for part in parts:
            if 'text' in part:
                text += part['text'] + "\n"
        return text
    except Exception as e:
        logger.error(f"DEBUG: Failed to parse Gemini REST response: {e}")
        return str(resp_json)


def _call_gemini_sdk(model_name, system_prompt, user_prompt):
    """Call Gemini using the Python SDK."""
    model = genai.GenerativeModel(model_name, system_instruction=system_prompt)
    chat = model.start_chat(history=[])
    response = chat.send_message(user_prompt)
    return response.text


def call_claude_api(model_name, system_prompt, user_prompt, reasoning_level):
    """Call Anthropic Claude Messages API. Returns response text."""
    anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
    if not anthropic_api_key:
        raise Exception("ANTHROPIC_API_KEY not set")

    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": anthropic_api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    # Adaptive Thinking 時は思考トークンも max_tokens に含まれるため余裕を持たせる
    max_tokens = 32000 if reasoning_level else 16000

    body = {
        "model": model_name,
        "max_tokens": max_tokens,
        "system": system_prompt,
        "messages": [
            {"role": "user", "content": user_prompt}
        ],
    }

    # Adaptive Thinking (official recommended approach for Opus/Sonnet 4.6+)
    # See: https://docs.anthropic.com/en/docs/build-with-claude/adaptive-thinking
    if reasoning_level:
        effort = reasoning_level if reasoning_level in ("max", "high", "medium", "low") else "high"
        body["thinking"] = {"type": "adaptive"}
        body["output_config"] = {"effort": effort}
        logger.debug(f"Claude Adaptive Thinking: effort={effort}")
    else:
        body["temperature"] = 0.2

    logger.debug(f"Claude API call: model={model_name}, reasoning={reasoning_level}")

    resp = requests.post(url, headers=headers, json=body, timeout=600)
    if resp.status_code != 200:
        logger.error(f"Claude API error {resp.status_code}: {resp.text[:300]}")
        raise Exception(f"Claude API error: {resp.status_code}")

    data = resp.json()

    usage = data.get("usage", {})
    logger.debug(
        "Claude usage: input=%s, output=%s",
        usage.get("input_tokens"), usage.get("output_tokens"),
    )

    # Extract text from content blocks (skip thinking blocks)
    text_parts = []
    for block in data.get("content", []):
        if block.get("type") == "text":
            text_parts.append(block["text"])

    result = "\n".join(text_parts)
    logger.debug(f"Claude response ({len(result)} chars): {result[:200]}")
    return result


def call_llm(model_name, system_prompt, user_prompt, reasoning_level):
    """Route LLM call to the appropriate provider."""
    if model_name.startswith("gpt") or model_name.startswith("o"):
        return call_openai_api(model_name, system_prompt, user_prompt, reasoning_level)
    elif model_name.startswith("claude"):
        return call_claude_api(model_name, system_prompt, user_prompt, reasoning_level)
    else:
        return call_gemini_api(model_name, system_prompt, user_prompt, reasoning_level)


def parse_llm_response(text):
    """Parse LLM response to extract reasoning and USI move."""
    reasoning = ""
    reasoning_match = re.search(
        r"(?:解説|Reasoning|Explanation)[:：][\s\*]*([\s\S]+?)(?=[\s\*]*Move:|http|$)",
        text, re.IGNORECASE
    )
    if reasoning_match:
        reasoning = reasoning_match.group(1).strip().strip("* \t\n")

    # Extract USI move candidates
    candidates = re.findall(r"Move:[\s\*]*([a-zA-Z0-9\+\*]+)", text, re.IGNORECASE)
    
    usi_move = None
    for cand in candidates:
        cand = cand.strip().strip("'\"`")
        if re.match(r"^[1-9][a-i][1-9][a-i]\+?$", cand):
            usi_move = cand
            break
        elif re.match(r"^[PLNSGBRK]\*[1-9][a-i]$", cand):
            usi_move = cand
            break
        else:
            logger.debug(f"Skipping invalid candidate: {cand}")

    return usi_move, reasoning


def validate_and_execute_move(game, usi_move, turn, legal_moves_usi):
    """Validate parsed USI move and execute it if legal. Returns (success, parsed_move)."""
    if not usi_move:
        return False, None
    
    try:
        parsed_move = parse_usi_string(usi_move)
    except Exception as e:
        logger.debug(f"Failed to parse USI: {usi_move} with error: {e}")
        return False, None

    # Check if strictly legal
    if usi_move in legal_moves_usi:
        return True, parsed_move
    
    # Check if physically possible (pseudo-legal fallback)
    move_type = parsed_move['type']
    is_possible = False
    
    if move_type == 'move':
        is_possible = game.is_physically_possible('move', parsed_move['from'], parsed_move['to'], turn, parsed_move['promote'])
        if is_possible and parsed_move['promote']:
            sx, sy = parsed_move['from']
            p = game.board[sy][sx]
            if p and not game.can_promote(sy, parsed_move['to'][1], turn, p['name']):
                logger.debug(f"Illegal Promotion Detected: {usi_move}")
                is_possible = False
    elif move_type == 'drop':
        is_possible = game.is_physically_possible('drop', parsed_move['name'], parsed_move['to'], turn)
    
    if is_possible:
        logger.debug(f"Permitting physically possible but strictly illegal move: {usi_move}")
        return True, parsed_move
    
    logger.debug(f"Move is physically impossible: {usi_move}")
    return False, None


def apply_move(game, parsed_move, turn):
    """Apply a parsed move to the game."""
    move_type = parsed_move['type']
    if move_type == 'move':
        game.make_move('move', parsed_move['from'], parsed_move['to'], turn, parsed_move['promote'])
    elif move_type == 'drop':
        game.make_move('drop', parsed_move['name'], parsed_move['to'], turn)
    game.switch_turn()


def check_game_over(game):
    """Check if the current player has no legal moves (game over)."""
    if len(game.get_legal_moves(game.turn)) == 0:
        game.game_over = True
        return True
    return False


def build_ai_settings(ai_vs_ai_mode, sente_model, gote_model):
    """Build ai_settings dict for get_full_state."""
    return {'ai_vs_ai_mode': ai_vs_ai_mode, 'sente_model': sente_model, 'gote_model': gote_model}


def cpu_fallback(game, turn, last_error, tts_enabled, model_name, ai_settings):
    """Execute CPU fallback when LLM fails.

    Uses iterative deepening minimax (same engine as /cpu_move) with a short time
    budget so fallback responses stay within request latency limits. Falls back
    to random only if the search itself errors out or returns nothing.
    """
    best_move = None
    try:
        _, best_move = game.iterative_deepening(
            maximizing=(turn == GOTE), time_limit=3.0
        )
    except Exception as e:
        logger.warning(f"CPU fallback minimax failed: {e}. Using random move.")
    if not best_move:
        best_move = game.get_random_move()
    move_str_ja = ""
    current_move_count = game.move_count
    reasoning = f"(LLMの応答が不適切なため、CPUが代打ちしました。{last_error})"

    if best_move:
        move_str_ja = get_japanese_move_str(game, best_move)
        move_type = best_move['type']
        start_or_name = best_move['from'] if move_type == 'move' else best_move['name']
        end = best_move['to']
        promote = best_move.get('promote', False)
        game.make_move(move_type, start_or_name, end, turn, promote)
        game.switch_turn()

    check_game_over(game)

    response_data = {
        'status': 'ok',
        'move': best_move,
        'usi': "CPU_FALLBACK_ERROR",
        'move_str_ja': move_str_ja,
        'move_count': current_move_count,
        'reasoning': reasoning,
        'model': f"{model_name} (Fallback)",
        'fallback_used': True,
        'game_state': get_full_state(game, ai_settings)
    }

    if tts_enabled and move_str_ja:
        turn_str = "先手" if turn == SENTE else "後手"
        tts_text = f"{turn_str}が違法手を選択したため、CPUが代打ちしました。{move_str_ja}。{turn_str}の一手と理由：{last_error}"
        tts_audio = generate_tts_audio(tts_text, model_name, turn, is_fallback=True)
        if tts_audio:
            response_data['tts_audio'] = tts_audio

    return response_data


# ========== LLM Move Endpoint ==========

@app.route('/api/llm_move', methods=['POST'])
def llm_move():
    session_id = request.headers.get('X-Session-ID', 'default_session')
    logger.debug(f"llm_move called (Stateless) Session: {session_id}")
    
    if not api_key:
        logger.error("ERROR: API Key not configured")
        return jsonify({'status': 'error', 'message': 'API Key not configured'}), 500

    try:
        data = request.json
        try:
            game, req_data = game_from_request(data)
        except Exception as e:
            return jsonify({'status': 'error', 'message': f'Invalid SFEN: {e}'}), 400

        turn = game.turn
        ai_vs_ai_mode = req_data.get('ai_vs_ai_mode', False) or req_data.get('ai_vs_ai', False)
        sente_model = req_data.get('sente_model', DEFAULT_SENTE_MODEL)
        gote_model = req_data.get('gote_model', DEFAULT_GOTE_MODEL)
        tts_enabled = req_data.get('tts_enabled', False)
        ai_settings = build_ai_settings(ai_vs_ai_mode, sente_model, gote_model)

        raw_model_name = sente_model if turn == SENTE else gote_model
        model_name, display_model_name, reasoning_level = parse_model_name(raw_model_name)
        
        logger.debug(f"Turn: {turn}, Model: {model_name}, Reasoning: {reasoning_level}")

        # Build legal moves list
        legal_moves = game.get_legal_moves(turn)
        legal_moves_usi = [u for m in legal_moves if (u := to_usi(m))]

        # Build prompts
        system_prompt, user_prompt, retry_legal_list = build_prompts(game, turn, req_data, legal_moves_usi)

        # Retry loop
        max_retries = min(max(int(data.get('max_retries', 2)), 1), 3)
        last_error = ""

        for attempt in range(max_retries):
            current_user_prompt = user_prompt
            if last_error:
                current_user_prompt += f"\n\n【前回の違反】{last_error}"
                if retry_legal_list:
                    current_user_prompt += (
                        f"\n改めて次の合法手リストからのみ選択してください（発駒マス別）:\n"
                        f"----\n{retry_legal_list}\n----\n"
                        f"出力前に、選んだMoveがリスト内の要素と完全一致することを必ず確認すること。"
                    )
                else:
                    current_user_prompt += "\nもう一度正しい手を選んでください。"

            try:
                text = call_llm(model_name, system_prompt, current_user_prompt, reasoning_level)
                logger.debug(f"Raw LLM Response: {text}")

                usi_move, reasoning = parse_llm_response(text)

                if not usi_move:
                    logger.debug(f"No USI found in response.")
                    last_error = "前回の応答からUSI形式の手を抽出できませんでした。回答フォーマットの `Move:` 行にUSI手のみを記載してください。"
                    continue

                logger.debug(f"Found valid USI move: {usi_move}")
                move_executed, parsed_move = validate_and_execute_move(game, usi_move, turn, legal_moves_usi)

                if not move_executed:
                    logger.debug("Invalid move. Retrying...")
                    last_error = f"前回の出力 `{usi_move}` は合法手リストに存在しません。"
                    continue

                # Move is valid — execute
                move_str_ja = get_japanese_move_str(game, parsed_move)
                current_move_count = game.move_count
                apply_move(game, parsed_move, turn)
                logger.debug(f"Post-Move SFEN: {game.get_sfen()}")

                # Check if previous move was fatal (king can be captured)
                if game.can_capture_king(game.turn):
                    logger.debug("King Capture allowed! Previous move was fatal.")
                    game.game_over = True
                    winner_name = "Sente" if game.turn == SENTE else "Gote"
                    return jsonify({
                        'status': 'ok',
                        'move': parsed_move, 'usi': usi_move,
                        'move_str_ja': move_str_ja,
                        'move_count': current_move_count,
                        'reasoning': reasoning + " (反則負け: 王将を取られる状態です)",
                        'model': display_model_name,
                        'game_over': True, 'winner': winner_name,
                        'game_state': get_full_state(game, ai_settings)
                    })

                # Normal success
                winner = None
                if check_game_over(game):
                    winner = "Sente" if game.turn == GOTE else "Gote"
                    logger.debug(f"Game Over. Winner: {winner}")

                response_data = {
                    'status': 'ok',
                    'move': parsed_move, 'usi': usi_move,
                    'move_str_ja': move_str_ja,
                    'move_count': current_move_count,
                    'reasoning': reasoning,
                    'model': display_model_name,
                    'game_state': get_full_state(game, ai_settings)
                }

                if tts_enabled and move_str_ja:
                    tts_text = f"{move_str_ja}。{reasoning}" if reasoning else move_str_ja
                    tts_audio = generate_tts_audio(tts_text, model_name, turn, is_fallback=False)
                    if tts_audio:
                        response_data['tts_audio'] = tts_audio
                    else:
                        response_data['tts_error'] = "TTS generation failed (quota exceeded or API error)"

                return jsonify(response_data)

            except Exception as e:
                logger.error(f"ERROR inside attempt loop: {e}")
                last_error = str(e)
                continue

        # All retries exhausted — CPU fallback
        logger.error(f"ERROR: Max retries reached. Last Error: {last_error}. Switching to CPU Fallback.")
        return jsonify(cpu_fallback(game, turn, last_error, tts_enabled, model_name, ai_settings))

    except Exception as e:
        logger.error(f"CRITICAL ERROR in llm_move: {e}")
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
