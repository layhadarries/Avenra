"""Operator-approved logical deletion with explicit, truthful media cleanup."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import re
from avenra.models.identifiers import valid_identifier
from avenra.repositories.retention_repository import RetentionRepository
from avenra.repositories.audit_repository import AuditRepository
from avenra.repositories.user_repository import UserRepository
from avenra.repositories.diary_repository import DiaryRepository
from avenra.repositories.case_access_repository import CaseAccessRepository
from avenra.services.diary_service import DiaryService, LocalDiaryStorage


class RetentionService:
    def __init__(self, conn, uploads_dir):
        self.conn=conn
        self.repo=RetentionRepository(conn)
        self.uploads_dir=uploads_dir

    def _scope(self, actor, case):
        if not valid_identifier(actor.id): raise PermissionError('active_admin_required')
        current=UserRepository(self.conn).get_by_id(actor.id)
        if current is None or not current.is_active or current.role!='admin': raise PermissionError('active_admin_required')
        if not isinstance(case,str) or not 1<=len(case)<=64: raise ValueError('invalid_case')
        owner=UserRepository(self.conn).get_survivor_by_case(case)
        if owner is None: raise ValueError('case_not_found')
        if not CaseAccessRepository(self.conn).assigned(actor.id,owner.id): raise PermissionError('case_assignment_required')
        return owner

    @staticmethod
    def _reference(value):
        if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9._:-]{8,120}',value):
            raise ValueError('approved_non_sensitive_ticket_reference_required')

    def _plan(self, owner, kind, before, entry_ids):
        if (before is None)==(entry_ids is None): raise ValueError('choose_cutoff_or_exact_ids')
        if kind not in {'diary','alert-location'}: raise ValueError('unsupported_retention_kind')
        if entry_ids is not None:
            if not isinstance(entry_ids,(list,tuple)) or not 1<=len(entry_ids)<=100 or any(not valid_identifier(value) for value in entry_ids):
                raise ValueError('invalid_exact_ids')
            entry_ids=sorted(set(entry_ids))
        else:
            if not isinstance(before,str) or len(before)>64: raise ValueError('invalid_cutoff')
            try:
                time=datetime.fromisoformat(before.replace('Z','+00:00'))
                if time.tzinfo is None or time>datetime.now(timezone.utc): raise ValueError()
                before=time.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')
            except (ValueError,OverflowError): raise ValueError('invalid_cutoff') from None
        # A broad SQL bound includes explicit offsets; the actual age comparison
        # happens on timezone-aware datetimes, never lexicographic client strings.
        search_upper=(time.astimezone(timezone.utc)+timedelta(days=1)).isoformat(timespec='seconds').replace('+00:00','Z') if entry_ids is None else before
        rows=self.repo.rows(owner.id,kind,search_upper,entry_ids)
        if len(rows)>100: raise ValueError('retention_scope_too_large_use_exact_ids')
        invalid_times=0
        if entry_ids is None:
            eligible=[]
            for row in rows:
                value=row['received_at' if kind=='diary' else 'created_at']
                try:
                    if not isinstance(value,str) or len(value)>64: raise ValueError()
                    parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
                    if parsed.tzinfo is None: raise ValueError()
                    parsed=parsed.astimezone(timezone.utc)
                except (ValueError,TypeError,AttributeError,OverflowError):
                    invalid_times+=1; continue
                if parsed<time: eligible.append(row)
            rows=eligible
        source={'owner':owner.id,'kind':kind,'before':before,'ids':entry_ids,'rows':rows,'hold_epoch':self.repo.epoch(owner.case_code)}
        plan=hashlib.sha256(json.dumps(source,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        return rows,{'plan':plan,'eligible':len(rows),'unknown_receipt_time':self.repo.unknown_times(owner.id)+invalid_times if kind=='diary' else invalid_times,
                     'blocked_by_hold':self.repo.held(owner.id)}

    def preview(self, actor, case, kind, before=None, entry_ids=None):
        owner=self._scope(actor,case)
        return self._plan(owner,kind,before,entry_ids)[1]

    def set_hold(self, actor, case, enabled, reference):
        self._reference(reference)
        if type(enabled) is not bool: raise ValueError('invalid_hold')
        with self.conn:
            self.conn.execute('BEGIN IMMEDIATE')
            owner=self._scope(actor,case)
            if enabled:
                self.conn.execute('INSERT INTO retention_holds(user_id,reference) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET reference=excluded.reference',(owner.id,reference))
            else:
                self.conn.execute('DELETE FROM retention_holds WHERE user_id=?',(owner.id,))
            AuditRepository(self.conn).log(f'user:{actor.id}','retention_hold_set' if enabled else 'retention_hold_released',owner.case_code,reference,commit=False)

    def apply(self, actor, case, kind, plan, reference, before=None, entry_ids=None):
        self._reference(reference)
        with self.conn:
            self.conn.execute('BEGIN IMMEDIATE')
            owner=self._scope(actor,case)
            previous=self.repo.run(plan)
            if previous:
                if previous['user_id']!=owner.id or previous['kind']!=kind: raise ValueError('invalid_plan')
                return {'removed':previous['removed'],'already_applied':True,'media_pending':self.repo.media_pending(owner.id)}
            rows,preview=self._plan(owner,kind,before,entry_ids)
            if preview['blocked_by_hold']: raise ValueError('retention_hold_active')
            if not rows or plan!=preview['plan']: raise ValueError('empty_or_stale_retention_plan')
            for row in rows: self.repo.remove(owner.id,kind,row,reference)
            self.repo.record_run(owner.id,kind,plan,len(rows),reference)
            AuditRepository(self.conn).log(f'user:{actor.id}','retention_applied',owner.case_code,
                f'{kind}; count={len(rows)}; plan={plan}; approval={reference}',commit=False)
            return {'removed':len(rows),'already_applied':False,'media_pending':self.repo.media_pending(owner.id)}

    def cleanup_media(self, actor, case, apply=False, reference=None):
        owner=self._scope(actor,case)
        result={'pending':self.repo.media_pending(owner.id),'deleted':0,'absent':0,'failed':0,'blocked':0}
        if not apply: return result
        self._reference(reference)
        storage=DiaryService(diary_repo=DiaryRepository(self.conn))._storage_for(self.uploads_dir)
        for job in self.repo.media_jobs(owner.id):
            with self.conn:
                self.conn.execute('BEGIN IMMEDIATE')
                self._scope(actor,case)
                name=job['object_name']; outcome='blocked'; reason='unsupported_storage'
                if not re.fullmatch(r'diary_[A-Za-z0-9_-]+\.jpg',name):
                    reason='unsafe_object_name'
                elif self.repo.media_blocked(name):
                    reason='hold_or_remaining_reference'
                else:
                    try:
                        if getattr(storage,'database_backed',False):
                            exists=self.conn.execute('SELECT 1 FROM diary_objects WHERE object_name=?',(name,)).fetchone()
                            if not exists: outcome,reason='absent','already_absent'
                            elif storage.verify_object(name,job['expected_sha256']):
                                storage.delete_object(name); outcome,reason='deleted','removed'
                            else: reason='integrity_requires_review'
                        elif isinstance(storage,LocalDiaryStorage):
                            try: raw=storage.get_object(name)
                            except FileNotFoundError: outcome,reason='absent','already_absent'
                            else:
                                if hashlib.sha256(raw).hexdigest()!=job['expected_sha256']: reason='integrity_requires_review'
                                else:
                                    os.unlink(storage._target_path(name)); outcome,reason='deleted','removed'
                            if outcome in {'deleted','absent'} and os.name=='posix':
                                descriptor=os.open(storage.uploads_dir,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
                                try: os.fsync(descriptor)
                                finally: os.close(descriptor)
                    except OSError:
                        outcome,reason='failed','storage_unavailable'
                status='deleted' if outcome in {'deleted','absent'} else outcome
                self.repo.finish_media(owner.id,name,status,reason)
                AuditRepository(self.conn).log(f'user:{actor.id}','retention_media_'+outcome,owner.case_code,
                    f'approval={reference}; reason={reason}',commit=False)
                result[outcome]+=1
        result['pending']=self.repo.media_pending(owner.id)
        return result
