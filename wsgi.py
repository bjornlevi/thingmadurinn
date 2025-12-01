"""WSGI entrypoint with optional URL prefix support."""

import os
from typing import Callable, Iterable, Tuple

from app import app

StartResponse = Callable[[str, Iterable[Tuple[str, str]]], Callable[[bytes], None]]


class PrefixMiddleware:
    """
    Mount the app under a URL prefix.

    If THINGMADURINN_PREFIX=/thingmadurinn, requests to /thingmadurinn/* are
    routed to the app, and url_for/static continue to work because PATH_INFO is
    rewritten and SCRIPT_NAME is set.
    """

    def __init__(self, wrapped_app, prefix: str):
        self.wrapped_app = wrapped_app
        self.prefix = prefix.rstrip("/")

    def __call__(self, environ, start_response: StartResponse):
        path = environ.get("PATH_INFO", "")
        if self.prefix and path.startswith(self.prefix):
            environ["SCRIPT_NAME"] = self.prefix
            environ["PATH_INFO"] = path[len(self.prefix) :] or "/"
            return self.wrapped_app(environ, start_response)
        if not self.prefix:
            return self.wrapped_app(environ, start_response)

        start_response("404 Not Found", [("Content-Type", "text/plain")])
        return [b"Not Found"]


prefix = os.environ.get("THINGMADURINN_PREFIX", "").rstrip("/")
if prefix and not prefix.startswith("/"):
    prefix = "/" + prefix

application = PrefixMiddleware(app, prefix)


if __name__ == "__main__":
    # Convenience for local invocation.
    app.run(host="0.0.0.0", port=8002, debug=False)
