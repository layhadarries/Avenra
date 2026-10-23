"""Survivor PWA static files controller."""
from flask import send_from_directory
from avenra.config import Config


class SurvivorController:
    """Delivers client PWA bundle, assets, and service worker."""

    def survivor_index(self):
        return send_from_directory(Config.SURVIVOR_DIR, "index.html")

    def survivor_file(self, filename: str):
        resp = send_from_directory(Config.SURVIVOR_DIR, filename)
        if filename == "service-worker.js":
            resp.headers["Cache-Control"] = "no-cache"
            resp.headers["Service-Worker-Allowed"] = "/survivor/"
        if filename == "manifest.json":
            resp.mimetype = "application/manifest+json"
        return resp
