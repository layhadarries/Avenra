"""Existing paired-device authority plus owner header and exact-origin middleware."""
from flask import jsonify, request
import db
from avenra.security import device_user
from avenra.services.alert_location_service import AlertLocationService, LocationPermission


def register_alert_locations(app):
    @app.get('/api/alerts/location-permission')
    def alert_location_permission():
        survivor=device_user() if request.cookies.get('avenra_device') else None
        if survivor is None: return jsonify(error='device_pairing_required'),401
        return jsonify(LocationPermission(db.get_db()).issue(survivor))

    @app.post('/api/alerts/by-client/<client_id>/location')
    def update_alert_location(client_id):
        survivor=device_user() if request.cookies.get('avenra_device') else None
        if survivor is None: return jsonify(error='device_pairing_required'),401
        if request.headers.get('X-Queue-Owner')!=str(survivor.id): return jsonify(error='queue_owner_mismatch'),409
        if request.content_length and request.content_length>2048: return jsonify(error='request_too_large'),413
        def reauthorize():
            current=device_user()
            return current is not None and current.id==survivor.id
        body,status=AlertLocationService(db.get_db()).update(survivor,client_id,request.get_json(silent=True),reauthorize)
        return jsonify(body),status
