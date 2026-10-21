"""Read-only retrieval of reviewed numeric observations, never instructions or effects.

Model extraction is a proposal. Trusted review binds the exact claim and source
bytes; retrieval rank cannot promote an unreviewed, stale or conflicting claim.
"""
from datetime import datetime,timezone
import hashlib
import json
import math
import os
import re


def _digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def _time(value):
    parsed=datetime.fromisoformat(str(value).replace('Z','+00:00'))
    if parsed.tzinfo is None:raise ValueError('timezone_required')
    return parsed.astimezone(timezone.utc)


def _binding(document,claims):
    return _digest({key:document.get(key) for key in ('id','tenant_id','sku','source_id','text','observed_at','expires_at','simulation_only')}|{'claims':claims})


def extract_proposals(document, model_output):
    raw=json.loads(model_output) if isinstance(model_output,str) else model_output
    if not isinstance(raw,dict) or set(raw)!={'claims'} or not isinstance(raw['claims'],list) or len(raw['claims'])>20:
        raise ValueError('bounded_claim_proposals_required')
    claims=[]
    for claim in raw['claims']:
        if not isinstance(claim,dict) or set(claim)!={'field','value','unit','quote'}:
            raise ValueError('claim_shape_invalid')
        if not isinstance(claim['field'],str) or not re.fullmatch('[a-z][a-z0-9_]{0,79}',claim['field']):
            raise ValueError('claim_field_invalid')
        if type(claim['value']) not in (int,float) or not math.isfinite(claim['value']):
            raise ValueError('numeric_observation_required')
        if not isinstance(claim['unit'],str) or not 1<=len(claim['unit'])<=40:
            raise ValueError('claim_unit_required')
        quote=claim['quote']
        if not isinstance(quote,str) or not 1<=len(quote)<=500 or quote not in document['text']:
            raise ValueError('exact_source_quote_required')
        if not re.search(r'(?<![\d.])'+re.escape(str(claim['value']))+r'(?![\d.])',quote):
            raise ValueError('numeric_value_not_in_quote')
        claims.append(dict(claim))
    return dict(status='review_required',claims=claims,source_binding=_binding(document,claims),commerce_authority='none')


def review_document(document,proposals,*,expected_claims,reviewer):
    # Internal review entry, never called with a model-supplied reviewer/expected set.
    if (not reviewer or not expected_claims or proposals.get('claims')!=expected_claims
            or proposals.get('source_binding')!=_binding(document,expected_claims)):
        raise ValueError('independent_exact_review_required')
    return {**document,'claims':expected_claims,'review':{'reviewer':reviewer,
        'binding':_binding(document,expected_claims),'status':'reviewed'},'commerce_authority':'none'}


def _admission(document,tenant_id,sku,now):
    if document.get('tenant_id')!=tenant_id or document.get('sku')!=sku:return 'scope_mismatch'
    if not document.get('id') or not document.get('source_id'):return 'source_missing'
    if document.get('revoked'):return 'revoked'
    review=document.get('review') or {}
    if (review.get('status')!='reviewed' or not review.get('reviewer') or not document.get('claims')
            or review.get('binding')!=_binding(document,document['claims'])):return 'review_not_current'
    try:
        if not _time(document['observed_at'])<=now<_time(document['expires_at']):return 'not_current'
    except (KeyError,ValueError,TypeError):return 'invalid_validity'
    return None


def _dense_rank(query,rows):
    # Source embeddings are prepared once during ingestion. A read performs at
    # most one bounded local query embedding, never N provider calls per source.
    from urllib.parse import urlsplit
    from src.app.services.embeddings import embed_text_ollama,cosine_dense
    indexed=[d for d in rows if isinstance(d.get('embedding'),dict)
        and d['embedding'].get('text_hash')==_digest(d['search_text'])]
    if not indexed:return [],'unavailable'
    model=os.getenv('MERCHANT_EMBED_MODEL','nomic-embed-text:latest')
    endpoint=os.getenv('MERCHANT_EMBED_URL','http://127.0.0.1:11435')
    parsed=urlsplit(endpoint)
    if parsed.scheme!='http' or parsed.hostname not in ('127.0.0.1','::1') or parsed.username or parsed.password:
        return [],'unavailable'
    vector=embed_text_ollama(query,model=model,base_url=endpoint,timeout=3)
    if not vector:return [],'unavailable'
    ranked=[]
    for doc in indexed:
        embedding=doc['embedding']
        if embedding.get('model')!=model or len(embedding.get('vector',[]))!=len(vector):continue
        score=cosine_dense(vector,embedding['vector'])
        if score>0:ranked.append((score,doc['id']))
    return [key for _,key in sorted(ranked,reverse=True)],'ollama:'+model


def retrieve(*,query,documents,tenant_id,sku,now,dense_ranker=None):
    from src.app.services.embeddings import SimpleEmbeddings
    from src.app.services.candidate_retriever import merge_rrf
    if not isinstance(query,str) or not 1<=len(query.strip())<=200 or len(documents)>100:
        raise ValueError('bounded_retrieval_required')
    now=_time(now.isoformat())
    accepted=[];withheld=[]
    for document in documents:
        reason=_admission(document,tenant_id,sku,now)
        if reason:
            # Wrong-scope documents must not leak their source IDs or text.
            if reason!='scope_mismatch':withheld.append({'id':document.get('id'),'reason':reason})
            continue
        accepted.append({**document,'search_text':' '.join(c['quote'] for c in document['claims'])})
    result=dict(status='empty',hits=[],withheld=withheld,commerce_authority='none',decision_use_allowed=False,
        retrieval={'method':'lexical+dense reciprocal-rank fusion','dense_provider':'not_called'})
    if not accepted:return result
    embedder=SimpleEmbeddings();q=embedder.embed_text(query)
    lexical=sorted(((embedder.cosine(q,embedder.embed_text(d['search_text'])),d) for d in accepted),key=lambda p:p[0],reverse=True)
    lexical=[d for score,d in lexical if score>0]
    try:
        dense_ids,provider=(dense_ranker or _dense_rank)(query,accepted)
    except Exception:
        dense_ids,provider=[],'unavailable'
    by_id={d['id']:d for d in accepted}
    dense=[by_id[key] for key in dict.fromkeys(dense_ids) if key in by_id]
    hits=merge_rrf(lexical,dense,identity_key='id',top_n=5)
    values={}
    for doc in accepted:
        for claim in doc['claims']:values.setdefault((claim['field'],claim['unit']),set()).add(claim['value'])
    conflicts=[{'field':key[0],'unit':key[1],'values':sorted(vals)} for key,vals in values.items() if len(vals)>1]
    result.update(status='conflicting' if conflicts else 'retrieved' if hits else 'empty',
        hits=[{k:v for k,v in d.items() if k not in ('search_text','text','embedding')} for d in hits],conflicts=conflicts,
        decision_use_allowed=bool(hits) and not conflicts,
        retrieval={**result['retrieval'],'dense_provider':provider,'degraded':provider in ('bow','unavailable','unknown')})
    return result
