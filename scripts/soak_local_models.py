"""Bounded text/image/text gateway soak; no product-quality claim is inferred."""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--endpoint', default='http://127.0.0.1:11435')
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--cycles', type=int, default=3)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    os.environ.update(OLLAMA_URL=args.endpoint, OLLAMA_CONTEXT_LENGTH='4096',
                      OLLAMA_KEEP_ALIVE='2m', LOCAL_MODEL_MAX_CONCURRENCY='1')
    tags = requests.get(args.endpoint+'/api/tags', timeout=5).json()['models']
    digests = {r['name']:r['digest'] for r in tags}
    from src.app.services.local_model_roles import execute_local_model_role, last_local_model_schedule_metrics
    from src.app.services.model_transports import make_ollama_generate_transport
    blob = args.image.read_bytes()
    from src.app.cv.image_normalizer import normalize_image_bytes
    image = normalize_image_bytes(blob, max_dim=512)
    if not image.meta.get('ok'):
        raise ValueError('mixed_soak_requires_decodable_image')
    image64 = base64.b64encode(image.image_bytes).decode()
    rows = []
    for cycle in range(args.cycles):
        for mode in ('text_before', 'image', 'text_after'):
            model = 'qwen3-vl:8b' if mode == 'image' else 'qwen3.5:9b-q4_K_M'
            started = time.perf_counter()
            row = dict(cycle=cycle, mode=mode, model=model, digest=digests[model])
            try:
                answer = execute_local_model_role(
                    'Describe the main object in this image in one short sentence.' if mode == 'image'
                    else 'In one sentence, explain why laptop RAM capacity matters.',
                    role='product_identity' if mode == 'image' else 'recommendation_turn_router',
                    purpose='roadmap_mixed_model_soak', prompt_id='mixed-soak-v1',
                    model=model, digest=digests[model], timeout_s=60, max_output_tokens=160,
                    context_hash=hashlib.sha256(blob).hexdigest() if mode == 'image' else None,
                    transport=make_ollama_generate_transport(images=[image64] if mode == 'image' else [],
                        keep_alive='2m', options={'num_ctx':4096,'temperature':0}))
                row.update(ok=bool(answer.strip()), response=answer)
            except Exception as exc:
                row.update(ok=False, failure_code=getattr(exc,'failure_code',type(exc).__name__))
            row.update(elapsed_ms=round((time.perf_counter()-started)*1000),
                       schedule=last_local_model_schedule_metrics(),
                       resident_models=[r['name'] for r in requests.get(args.endpoint+'/api/ps',timeout=5).json()['models']])
            rows.append(row)
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_text(json.dumps({'image_sha256':hashlib.sha256(blob).hexdigest(),
                'model_image_sha256':hashlib.sha256(image.image_bytes).hexdigest(), 'image_normalization':image.meta,
                'context_length':4096,'rows':rows,'passed':all(x['ok'] and len(x['resident_models'])<=1 for x in rows),
                'scope':'gateway transport and residency; not image identification accuracy or browser image flow'},indent=2),encoding='utf-8')
            print(json.dumps({k:row[k] for k in ('cycle','mode','ok','elapsed_ms','resident_models')}),flush=True)
            if not row['ok']:
                return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
