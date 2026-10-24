"""Project glossary application without sample-specific engine rules."""
from __future__ import annotations

import re


def translate_with_glossary(provider, text: str, glossary: dict[str,str]) -> tuple[str,dict]:
    terms=[term for term in sorted(glossary,key=len,reverse=True) if term in text]
    protected=text
    tokens={}
    for index,term in enumerate(terms):
        token=f'ZXQ{index}XZ'
        protected=protected.replace(term,token)
        tokens[token]=glossary[term]
    translated=provider.translate(protected)
    missing=[]
    for token,value in tokens.items():
        pattern=r'\s*'.join(map(re.escape,token))
        translated,count=re.subn(pattern,lambda _m:value,translated,flags=re.I)
        if not count:
            missing.append(token)
    if missing:
        # Preserve every source span and exact term when the model corrupts a
        # marker. Chunked grammar is explicitly unverified, never silently fixed
        # by deleting the surrounding information.
        pattern='('+'|'.join(re.escape(term) for term in terms)+')'
        chunks=re.split(pattern,text)
        translated=' '.join(glossary[chunk] if chunk in glossary else provider.translate(chunk)
            if any('\u3400'<=c<='\u9fff' for c in chunk) else chunk for chunk in chunks if chunk.strip())
    return translated,{'provider':'argos-translate','strategy':'protected-project-glossary',
        'glossary_terms':{k:glossary[k] for k in terms},'unresolved_terms':[],
        'placeholder_failures':missing,'fallback':'literal-terms-with-all-surrounding-spans' if missing else None,
        'review_required':True,'human_approved':False}
