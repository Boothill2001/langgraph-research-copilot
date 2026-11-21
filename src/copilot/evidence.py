"""Fail-closed evidence revalidation. Credentials and dates never come from source text."""
import os
import requests
from .security import USERS, issue


def validate_refs(evidence, owner, context=None):
    if not evidence:
        return {'valid': True, 'evidence': []}
    if any(not e.get('generation') or not e.get('chunk_uid') for e in evidence):
        return {'valid': False, 'status': 'missing_provenance', 'evidence': []}
    contexts = [e.get('retrieval_context', {}) for e in evidence]
    context = context or contexts[0]
    if any(c != context for c in contexts):
        return {'valid': False, 'status': 'context_conflict', 'evidence': []}
    try:
        response = requests.post(os.getenv('RAG_API_URL', 'http://127.0.0.1:8011') + '/research/validate',
            headers={'Authorization': 'Bearer ' + issue(USERS[owner])},
            json={'evidence': [{'chunk_uid': e['chunk_uid'], 'generation': e['generation']} for e in evidence], 'context': context}, timeout=(3,15))
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError):
        return {'valid': False, 'status': 'validation_unavailable', 'evidence': []}

def state_evidence(state):
    """Every search observation is potential model context, not just the last result."""
    refs = list(state.get('evidence', []))
    for observation in state.get('observations', []):
        refs.extend(observation.get('evidence', []))
    unique = {}
    import json
    for ref in refs:
        key = (ref.get('generation'), ref.get('chunk_uid'), json.dumps(ref.get('retrieval_context', {}), sort_keys=True))
        unique[key] = ref
    return list(unique.values())


def validate_bound(evidence, owner, context=None):
    """Validate each trusted retrieval context separately; mixed searches stay scoped."""
    import json
    groups = {}
    for ref in evidence:
        ctx = ref.get('retrieval_context', context or {})
        key = json.dumps(ctx,sort_keys=True)
        groups.setdefault(key,[]).append(ref)
    for key, refs in groups.items():
        checked = validate_refs(refs,owner,json.loads(key))
        if not checked.get('valid'):
            return {'valid':False,'status':'stale_evidence','evidence':[]}
    return {'valid':True}
