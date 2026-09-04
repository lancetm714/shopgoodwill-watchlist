import logging

from flask import Flask


def create_app():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    app = Flask(__name__)

    from .routes import bp
    app.register_blueprint(bp)

    from . import notifier
    notifier.start()

    return app
