"""Image triage yields while a sandbox publisher waits for its transport."""
import asyncio
import base64
import threading

import httpx
import pytest

from src.app.main import create_app


@pytest.mark.asyncio
async def test_sandbox_publication_does_not_block_request_event_loop(monkeypatch):
    from src.app.routers import vision
    from src.app.services import sandbox_queue
    entered=threading.Event()
    released=threading.Event()
    observation={}
    async def labels(self,blob,mode='visual_search'):
        return ['laptop'],'',None
    def triage(self,labels,text):
        return {'damage_type':'unknown','severity':'undetermined','confidence':0.2}
    def payload(*args,**kwargs):
        return {'attack_hypothesis':'lolbin_command_sequence','claim_status':'possible',
            'finding_group':'unconfirmed_higher_order_hypotheses',
            'runtime_confirmation_required':True,'runtime_evidence_required':['sandbox process tree'],
            'runtime_evidence_present':[],'possible_mitre_attack':['T1218'],'mitre_attack':[],
            'signal_labels':{},'signals_updated':{}}
    def publish(**kwargs):
        observation.update(kwargs)
        entered.set()
        observation['loop_resumed_during_publication']=released.wait(timeout=2)
        return {'queued':False,'reason':'owned_transport_unavailable'}
    monkeypatch.setattr(vision.ManagedCVProvider,'get_labels_and_text',labels)
    monkeypatch.setattr(vision.BasicCVTriage,'analyze',triage)
    monkeypatch.setattr(vision,'classify_passive_payload',payload)
    monkeypatch.setattr(sandbox_queue,'queue_sandbox_detonation',publish)
    async def resume_loop():
        deadline=asyncio.get_running_loop().time()+20
        while not entered.is_set():
            assert asyncio.get_running_loop().time()<deadline,'Triage did not reach the selected publisher'
            await asyncio.sleep(0.001)
        released.set()
    image=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAAWgmWQ0AAAAASUVORK5CYII=')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()),base_url='http://testserver') as client:
        response,_=await asyncio.gather(client.post('/api/v1/vision/triage',
            headers={'x-api-key':'local-merchant-key'},files={'image':('inert.png',image,'image/png')}),resume_loop())
    assert response.status_code==200,response.text
    assert observation['loop_resumed_during_publication'] is True
    assert observation['tenant_id']=='default'
    security=response.json()['security']
    assert security['claim_status']=='possible'
    assert security['mitre_attack']==[]
