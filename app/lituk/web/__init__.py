import pathlib

from flask import Flask, send_from_directory

from lituk.web import sessions as _sessions


_STATIC = pathlib.Path(__file__).parent / "static"


def create_app(db_path: str | None = None) -> Flask:
    app = Flask(__name__, static_folder=None)

    if db_path:
        _sessions.configure(db_path)

    from lituk.web.routes_review import bp as review_bp
    from lituk.web.routes_stats import bp as stats_bp
    app.register_blueprint(review_bp)
    app.register_blueprint(stats_bp)

    @app.get("/")
    def index():
        return send_from_directory(_STATIC, "index.html")

    @app.get("/session")
    def session_page():
        return send_from_directory(_STATIC, "session.html")

    @app.get("/dashboard")
    def dashboard_page():
        return send_from_directory(_STATIC, "dashboard.html")

    @app.get("/missed")
    def missed_page():
        return send_from_directory(_STATIC, "missed.html")

    @app.get("/static/<path:filename>")
    def static_files(filename: str):
        return send_from_directory(_STATIC, filename)

    return app
