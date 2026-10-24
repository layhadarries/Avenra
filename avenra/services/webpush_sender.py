"""Encrypted neutral Web Push; no redirects, retries, SMS fallback or PII payload."""
import json
from avenra.services.push_service import validate_subscription

class WebPushSender:
    def __init__(self,settings,transport=None):self.settings,self.transport=settings,transport
    def __repr__(self):return '<WebPushSender secrets=redacted>'
    def send(self,subscription,url='/contact-push/'):
        subscription=validate_subscription(subscription)
        import re
        if url!='/contact-push/' and not re.fullmatch(r'/contact-push/#ack=[A-Za-z0-9_-]{43}',url):
            return {'outcome':'failed','reason':'invalid_message'}
        payload=json.dumps({'title':'Notification','body':'You have a new notification.','url':url})
        from pywebpush import webpush,WebPushException
        import requests
        class BoundedSession(requests.Session):
            def __init__(self):super().__init__();self.trust_env=False
            def post(self,*args,**kwargs):
                kwargs['allow_redirects']=False;kwargs['stream']=True
                response=super().post(*args,**kwargs)
                try:
                    data=response.raw.read(65537,decode_content=True)
                    if len(data)>65536:raise OSError('response_too_large')
                    response._content=data
                finally:response.close()
                return response
        transport=self.transport or webpush
        try:
            with BoundedSession() as client:
                response=transport(subscription_info=subscription,data=payload,
                    vapid_private_key=str(self.settings.private),vapid_claims={'sub':self.settings.subject},
                    ttl=300,timeout=10,requests_session=client)
            status=response.status_code
        except WebPushException as error:
            status=error.response.status_code if error.response is not None else None
        except (requests.RequestException,TimeoutError,OSError):
            return {'outcome':'unknown','reason':'transport_uncertain'}
        if status in (404,410):return {'outcome':'failed','reason':'provider_rejected','expired':True}
        if status is not None and 200<=status<300:return {'outcome':'accepted','reason':'provider_accepted'}
        if status in (400,401,403,413):return {'outcome':'failed','reason':'provider_rejected'}
        return {'outcome':'unknown','reason':'provider_uncertain'}
