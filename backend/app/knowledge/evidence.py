"""Persisted source provenance, never model-authored reference metadata."""
import hashlib
from ..quiz_grounding.snapshots import EvidenceSegment


def evidence_from_hit(hit):
    location,source = hit['location'],hit.get('source',{})
    return EvidenceSegment(id='kb-'+hit['chunk_id'],text=hit['text'],title=hit['title'],page=location.get('page'),
        url=source.get('url'),retrieved_at=source.get('retrieved_at'),content_kind='material',supplement=False,
        content_hash=hashlib.sha256(hit['text'].encode()).hexdigest(),acquisition_status='available',
        truncated=bool(source.get('truncated')),knowledge={
            'document_id':hit['document_id'],'revision_id':hit['revision_id'],'chunk_id':hit['chunk_id'],
            'document_title':hit['title'],'source_type':hit['source_type'],'document_version':hit['version'],
            'chunk_position':hit.get('position',0),'header_path':[h[:500] for h in location.get('header_path',[])],
            'start_index':location['start_index'],'end_index':location['end_index'],'block':location.get('block')})


def mark_deleted_sources(session, uid, segments):
    from .database import Document
    for segment in segments:
        knowledge = segment.get('knowledge')
        if not knowledge: continue
        document = session.get(Document,knowledge['document_id'])
        deleted = document is None or document.user_id != uid or document.deleted_at is not None
        segment['knowledge'] = {**knowledge,'deleted':deleted,
            'version_changed':bool(not deleted and document.active_revision_id != knowledge['revision_id'])}
