"""Build consent-aware case views independently of HTTP and templates."""
from avenra.repositories.portal_repository import PortalRepository
from avenra.repositories.case_access_repository import CaseAccessRepository
from avenra.repositories.user_repository import UserRepository
from avenra.repositories.consent_repository import ConsentRepository
from avenra.repositories.shelter_repository import ShelterRepository
from avenra.repositories.referral_repository import ReferralRepository
from avenra.repositories.diary_repository import DiaryRepository
from avenra.repositories.audit_repository import AuditRepository


class CaseService:
    def __init__(self, repository=None):
        self.repo = repository or PortalRepository()

    def view(self, user, case_code):
        conn = self.repo.conn
        survivor = UserRepository(conn).get_survivor_by_case(case_code)
        if survivor is None or not CaseAccessRepository(conn).allows(user.id, survivor.id):
            return None
        consents = ConsentRepository(conn).get_consents_map(survivor.id)
        diary_active = consents['diary_sharing']['active']
        location_active = consents['location_sharing']['active']
        alerts = [dict(r) for r in self.repo.case_rows(survivor.id)]
        for alert in alerts:
            if not location_active:
                alert['lat'] = alert['lng'] = None
            alert.update(self.repo.workflow(alert['id']))
            alert['history'] = self.repo.history(alert['id'])
        diary = DiaryRepository(conn).list_shared_for_case(survivor.id) if diary_active else []
        AuditRepository(conn).log(f'user:{user.id}', 'case_viewed', case_code)
        if diary:
            AuditRepository(conn).log(f'user:{user.id}', 'diary_viewed', case_code)
        access_repo = CaseAccessRepository(conn)
        return dict(survivor=survivor, case_code=case_code, alerts=alerts,
                    referrals=ReferralRepository(conn).get_for_case(case_code) if consents['shelter_referral_sharing']['active'] else [],
                    shelters=ShelterRepository(conn).get_all(), contacts=[], consents=consents,
                    location_consent_active=location_active, diary_consent_active=diary_active,
                    diary_entries=diary, responders=access_repo.candidates(survivor.id),
                    case_grants=access_repo.list_grants(survivor.id),
                    available_staff=access_repo.available_staff(survivor.id))

    def manage_grant(self, admin_user, case_code: str, action: str, staff_id: int):
        if admin_user.role != 'admin':
            return {'error': 'forbidden'}, 403
        conn = self.repo.conn
        with conn:
            survivor = UserRepository(conn).get_survivor_by_case(case_code)
            if survivor is None:
                return {'error': 'not_found'}, 404
            target_user = UserRepository(conn).get_by_id(staff_id)
            if target_user is None or target_user.role not in ('responder', 'admin') or not target_user.is_active:
                return {'error': 'invalid_staff'}, 400

            access_repo = CaseAccessRepository(conn)
            if action == 'grant':
                access_repo.grant(staff_id, survivor.id)
                AuditRepository(conn).log(
                    f'user:{admin_user.id}',
                    'case_access_granted',
                    case_code,
                    f'granted to {target_user.name} (#{staff_id})'
                )
            elif action == 'revoke':
                access_repo.revoke(staff_id, survivor.id)
                AuditRepository(conn).log(
                    f'user:{admin_user.id}',
                    'case_access_revoked',
                    case_code,
                    f'revoked from {target_user.name} (#{staff_id})'
                )
            else:
                return {'error': 'invalid_action'}, 400
        return {'ok': True, 'action': action, 'staff_id': staff_id}, 200
