from firebase_functions import https_fn, options
import sys
try:
    from main_flask import app as flask_app
except Exception as e:
    sys.stderr.write(f"CRITICAL IMPORT ERROR: {e}\n")
    import traceback
    traceback.print_exc(file=sys.stderr)
    sys.stderr.flush()
    raise e


@https_fn.on_request(timeout_sec=3600, memory=options.MemoryOption.MB_512)
def shogi_api(req: https_fn.Request) -> https_fn.Response:
    with flask_app.request_context(req.environ):
        return flask_app.full_dispatch_request()
