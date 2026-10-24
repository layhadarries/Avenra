"""Trusted-contact input policy. Validate the complete submission before saving."""
import re
class ContactValidationError(ValueError):
    pass
class ContactService:
    MAX_CONTACTS=5
    MAX_NAME_LENGTH=60
    @staticmethod
    def clean_contacts(items):
        if not isinstance(items,list): raise ContactValidationError('Contacts must be a list.')
        if len(items)>5: raise ContactValidationError('A maximum of five contacts is allowed.')
        cleaned=[]; names=set(); numbers=set()
        for item in items:
            if not isinstance(item,dict):raise ContactValidationError('Each contact must be an object.')
            name,phone=item.get('name'),item.get('phone')
            if not isinstance(name,str):raise ContactValidationError('Contact names must be text.')
            name=name.strip()
            if not name or len(name)>60 or any(not c.isprintable() for c in name):
                raise ContactValidationError('Contact names must contain 1–60 printable characters.')
            if not isinstance(phone,str) or len(phone)>40:raise ContactValidationError('Invalid phone number.')
            phone=re.sub(r'[ ()-]','',phone.strip())
            if re.fullmatch(r'0[1-9][0-9]{8}',phone):phone='+27'+phone[1:]
            elif not re.fullmatch(r'\+27[1-9][0-9]{8}',phone):raise ContactValidationError('Invalid South African phone number.')
            if phone in numbers:raise ContactValidationError('Duplicate contact phone number.')
            if name in names:raise ContactValidationError('Contact names must be distinct.')
            numbers.add(phone);names.add(name);cleaned.append((name,phone))
        return cleaned
