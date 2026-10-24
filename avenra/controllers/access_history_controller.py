"""Survivor access-history endpoint."""
from flask import jsonify, request

from avenra.security import device_user
from avenra.services.access_history_service import AccessHistoryService


class AccessHistoryController:
    def __init__(self, service=None):
        self.service = (
            service if service is not None else AccessHistoryService()
        )

    def my_access(self):
        survivor = device_user()

        if survivor is None:
            response = jsonify({"error": "bad_device_token"})
            response.headers["Cache-Control"] = "no-store"
            return response, 401

        body, status = self.service.list_history(
            survivor,
            request.args,
        )

        response = jsonify(body)
        response.headers["Cache-Control"] = "no-store"
        return response, status