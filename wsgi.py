"""WSGI entrypoint for production servers."""

from app import app as application


if __name__ == "__main__":
    # Convenience for local invocation.
    application.run(host="0.0.0.0", port=8002, debug=False)
