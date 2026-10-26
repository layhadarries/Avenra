"""Establish real server vault grants for synthetic test owners, never forge grants."""
import os

PHRASE='Cedar! private river vault 826'


def unlock_test_vault(client, headers=None):
    origin=os.environ.get('PUBLIC_BASE_URL','http://localhost').rstrip('/')
    headers=dict(headers or {})
    status=client.get('/api/vault',headers=headers,base_url=origin)
    assert status.status_code==200, 'Fictional owner must authenticate before fixture vault setup'
    configured=status.json['configured']
    body={'passphrase':PHRASE}
    if not configured: body['confirmation']=PHRASE
    response=client.post('/api/vault/'+('unlock' if configured else 'setup'),json=body,
        headers={**headers,'Origin':origin},base_url=origin)
    assert response.status_code in (200,201), 'Fictional vault authorization failed'
    client.environ_base['HTTP_X_VAULT_UNLOCK']=response.json['unlock_token']
    return response.json['unlock_token']
