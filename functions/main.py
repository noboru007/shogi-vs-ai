from firebase_functions import https_fn, options

# NOTE: main_flask is NOT imported at module level.
# Firebase CLI discovery must complete within 10s, but importing
# google-generativeai / openai is too slow for that window.
# Instead we lazy-load on first request.

_flask_app = None


def _get_app():
    global _flask_app
    if _flask_app is None:
        import sys
        try:
            from main_flask import app
            _flask_app = app
        except Exception as e:
            sys.stderr.write(f"CRITICAL IMPORT ERROR: {e}\n")
            import traceback
            traceback.print_exc(file=sys.stderr)
            sys.stderr.flush()
            raise
    return _flask_app


@https_fn.on_request(timeout_sec=3600, memory=options.MemoryOption.MB_512)
def shogi_api(req: https_fn.Request) -> https_fn.Response:
    app = _get_app()
    with app.request_context(req.environ):
        return app.full_dispatch_request()
