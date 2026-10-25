"""Account details require an existing authenticated survivor device."""
from flask import jsonify, request
import db

from avenra.security import device_user
from avenra.services.onboarding_service import OnboardingService


def register_onboarding(app):
    @app.get('/api/onboarding')
    def survivor_onboarding_details():
        survivor = device_user()
        if survivor is None:
            return jsonify(error='device_pairing_required'), 401
        return jsonify(OnboardingService(db.get_db()).details(survivor))

    @app.post('/api/onboarding')
    def complete_survivor_onboarding():
        survivor = device_user()
        if survivor is None:
            return jsonify(error='device_pairing_required'), 401
        body, status = OnboardingService(db.get_db()).save(survivor, request.get_json(silent=True))
        return jsonify(body), status
