"""Survivor-only trusted-contact API with masked read responses."""
import sqlite3
from flask import request,jsonify
from avenra.repositories.contact_repository import ContactRepository
from avenra.repositories.audit_repository import AuditRepository
from avenra.security import device_user
from avenra.services.contact_service import ContactService,ContactValidationError

class ContactsController:
    def __init__(self,contact_repo=None,audit_repo=None):
        self.contact_repo=contact_repo or ContactRepository()
        self.audit_repo=audit_repo or AuditRepository()
    def list_contacts(self):
        survivor=device_user()
        if survivor is None:return jsonify({'error':'bad_device_token'}),401
        rows=self.contact_repo.get_for_user(survivor.id)
        return jsonify({'contacts':[{'id':r['id'],'name':r['name'],
            'phone_masked':'••••'+r['phone'][-4:]} for r in rows]})
    def save_contacts(self):
        survivor=device_user()
        if survivor is None:return jsonify({'error':'bad_device_token'}),401
        data=request.get_json(silent=True)
        if not isinstance(data,dict):return jsonify({'error':'contacts_object_required'}),400
        if 'contacts' not in data:
            if 'name' in data or 'phone' in data:
                return self.add_contact(survivor,data)
            return jsonify({'error':'contacts_list_required'}),400
        conn=self.contact_repo.conn
        try:
            with conn:
                conn.execute('BEGIN IMMEDIATE')
                items=data['contacts']
                if not isinstance(items,list):raise ContactValidationError('Contacts must be a list.')
                current={r['id']:r for r in self.contact_repo.get_for_user(survivor.id)}
                expanded=[]; used=set()
                for item in items:
                    if not isinstance(item,dict):raise ContactValidationError('Each contact must be an object.')
                    value=dict(item)
                    if 'id' in value:
                        key=value['id']
                        if type(key) is not int or key not in current or key in used:
                            raise ContactValidationError('Invalid or duplicate contact identifier.')
                        used.add(key)
                        if 'phone' not in value:value['phone']=current[key]['phone']
                    expanded.append(value)
                cleaned=ContactService.clean_contacts(expanded)
                self.contact_repo.replace_contacts(survivor.id,cleaned)
                self.audit_repo.log(f'survivor {survivor.case_code}','contacts_updated',survivor.case_code,
                    f'{len(cleaned)} contact(s) saved',commit=False)
        except ContactValidationError as error:
            return jsonify({'error':'invalid_contacts','message':str(error)}),400
        except sqlite3.Error:
            return jsonify({'error':'contact_storage_unavailable'}),503
        return self.list_contacts()

    def add_contact(self,survivor,data):
        conn=self.contact_repo.conn
        try:
            with conn:
                conn.execute('BEGIN IMMEDIATE')
                existing=self.contact_repo.get_for_user(survivor.id)
                if len(existing)>=ContactService.MAX_CONTACTS:
                    return jsonify({'error':'contact_limit'}),400
                name,phone=ContactService.clean_contacts([data])[0]
                if any(r['name']==name or r['phone']==phone for r in existing):
                    raise ContactValidationError('Contact name and number must be distinct.')
                self.contact_repo.add_contact(survivor.id,name,phone)
                self.audit_repo.log(f'survivor {survivor.case_code}','contact_added',
                    survivor.case_code,'Trusted contact added',commit=False)
        except ContactValidationError as error:
            return jsonify({'error':'invalid_contacts','message':str(error)}),400
        except sqlite3.Error:
            return jsonify({'error':'contact_storage_unavailable'}),503
        return self.list_contacts(),201

    def delete_contact(self,contact_id):
        survivor=device_user()
        if survivor is None:return jsonify({'error':'bad_device_token'}),401
        conn=self.contact_repo.conn
        try:
            with conn:
                conn.execute('BEGIN IMMEDIATE')
                if not self.contact_repo.delete_contact(survivor.id,contact_id):
                    return jsonify({'error':'not_found'}),404
                self.audit_repo.log(f'survivor {survivor.case_code}','contact_removed',
                    survivor.case_code,'Trusted contact removed',commit=False)
        except sqlite3.Error:
            return jsonify({'error':'contact_storage_unavailable'}),503
        return self.list_contacts()
