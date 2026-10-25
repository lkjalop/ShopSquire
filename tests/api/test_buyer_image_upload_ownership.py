"""Buyer uploads are authenticated evidence proposals, never operator authority."""
import io
import json
import time

import jwt
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from src.app.main import create_app


@pytest.fixture
def upload_client(monkeypatch):
    key='owned-upload-regression-signing-key-never-deploy'
    monkeypatch.setenv('JWT_SIGNING_KEY',key)
    monkeypatch.setenv('BUYER_IDENTITY_MODE','strict')
    monkeypatch.setenv('BUYER_TENANT_BINDINGS_JSON',json.dumps({'upload-a':['default'],'upload-b':['default']}))
    monkeypatch.setenv('CV_OCR_PROVIDER','disabled')
    monkeypatch.setenv('CV_VISION_ENABLED','0')
    monkeypatch.setenv('CV_STEG_DETECT_ENABLED','1')
    out=io.BytesIO()
    Image.new('RGB',(32,32),'white').save(out,format='PNG')
    def token(subject):
        now=int(time.time())
        return jwt.encode(dict(sub=subject,typ='access',role='buyer',iss='shopsquire',
            aud='shopsquire-api',iat=now,exp=now+300),key,algorithm='HS256')
    with TestClient(create_app()) as client:
        yield client,out.getvalue(),token


def submit(fixture,subject='upload-a',artifact='owned-upload-client-001',**kwargs):
    client,raw,token=fixture
    headers={'authorization':'Bearer '+token(subject),**kwargs.pop('headers',{})}
    return client.post('/api/v1/vision/triage',params={'fast':1,'artifact_id':artifact,**kwargs.pop('params',{})},
        files={'image':('clean.png',raw,'image/png')},headers=headers,**kwargs)


def test_verified_buyer_can_submit_without_borrowing_an_operator_key(upload_client):
    response=submit(upload_client)
    assert response.status_code==200,response.text
    body=response.json()
    assert body['artifact']['artifact_id']!='owned-upload-client-001'
    assert body['artifact']['authority']=='blocked'  # fast inspection is incomplete
    assert body['security']['commercial_authority']=='blocked'


def test_repeated_buyer_upload_keeps_its_scoped_id_but_another_buyer_cannot_replace_it(upload_client):
    first=submit(upload_client)
    repeat=submit(upload_client)
    foreign=submit(upload_client,'upload-b')
    assert [r.status_code for r in (first,repeat,foreign)]==[200,200,200]
    first_id=first.json()['artifact']['artifact_id']
    assert repeat.json()['artifact']['artifact_id']==first_id
    assert foreign.json()['artifact']['artifact_id']!=first_id
    forged=submit(upload_client,'upload-b',artifact=first_id)
    assert forged.status_code==200
    assert forged.json()['artifact']['artifact_id']!=first_id
    assert submit(upload_client).json()['artifact']['artifact_id']==first_id


@pytest.mark.parametrize('variation',['anonymous','forged_uid','foreign_tenant','invalid_operator_key'])
def test_upload_admission_rejects_unverified_or_mismatched_authority(upload_client,variation):
    if variation=='anonymous':
        client,raw,_=upload_client
        response=client.post('/api/v1/vision/triage',files={'image':('clean.png',raw,'image/png')})
    else:
        options={'forged_uid':{'params':{'uid':'upload-b'}},
                 'foreign_tenant':{'headers':{'x-tenant-id':'foreign'}},
                 'invalid_operator_key':{'headers':{'x-api-key':'invalid-upload-key'}}}
        response=submit(upload_client,**options[variation])
    assert response.status_code in (401,403),response.text


def test_explicit_operator_upload_keeps_its_existing_artifact_identifier(upload_client):
    client,raw,_=upload_client
    response=client.post('/api/v1/vision/triage',params={'fast':1,'artifact_id':'operator-upload-001'},
        files={'image':('clean.png',raw,'image/png')},headers={'x-api-key':'local-merchant-key'})
    assert response.status_code==200,response.text
    assert response.json()['artifact']['artifact_id']=='operator-upload-001'
