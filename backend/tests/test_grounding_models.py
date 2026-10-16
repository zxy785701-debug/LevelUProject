from copy import deepcopy
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.materials.api import LinkBody
from app.models import GenerateRequest, Quiz
from app.quiz_grounding.models import (
    ExtractParameters, GenerationOperation, Preparation, PrepareRequest,
    QuestionReview, QuizDraftResult, ScopeContent, SearchParameters,
)
from app.quiz_grounding.snapshots import EvidenceSegment, QuizSource
from tests.helpers import quiz_payload


def confirmation(**changes):
    return dict(preparation_id="prep1", scope_version=1, candidate_id="ai", focus_id="use", scope_point_ids=["p1"], **changes)


def scope():
    return ScopeContent(candidates=[{
        "id": "ai", "topic": "Harness Engineering", "domain": "AI", "description": "AI 领域",
        "focuses": [{"id": "use", "name": "应用", "description": "实践", "points": [
            {"id": "p1", "name": "环境", "evidence_ids": ["s1"], "evidence_status": "available"},
        ]}, {"id": "base", "name": "基础", "description": "定义", "points": [{"id": "p2", "name": "定义"}]}],
    }])


def old_quiz():
    return {**quiz_payload(), "id": "quiz1", "created_at": "2026-10-13T00:00:00Z", "source_text": "HTTP", "difficulty": "easy"}


def test_confirmed_topic_is_background_and_old_input_remains_parseable():
    assert GenerateRequest(**confirmation()).execution == "background"
    assert GenerateRequest(text="HTTP").preparation_id is None
    assert GenerateRequest(material_id="m1", point_ids=["s1"]).execution == "sync"
    assert GenerateRequest(material_id="m1", execution="background").execution == "background"
    assert PrepareRequest(text=" ＨＴＴＰ\r\n基础\x00 ").text == "HTTP\n基础"


@pytest.mark.parametrize("payload", [
    {}, {"text": "x", "material_id": "m"}, {**confirmation(), "text": "x"},
    {**confirmation(), "material_id": "m"}, {**confirmation(), "scope_version": None},
    {**confirmation(), "scope_point_ids": []}, {**confirmation(), "scope_point_ids": ["p1", "p1"]},
    {**confirmation(), "scope_version": True}, {**confirmation(), "supplement": True},
    {"material_id": "m", "candidate_id": "ai"}, {"text": "x", "scope_point_ids": ["p1"]},
])
def test_generation_rejects_mixed_missing_or_forged_confirmation(payload):
    with pytest.raises(ValidationError):
        GenerateRequest(**payload)


def test_scope_selection_checks_parentage_and_real_evidence():
    content = scope()
    candidate, focus, points = content.selected("ai", "use", ["p1"])
    assert candidate.domain == "AI" and focus.id == "use" and points[0].name == "环境"
    content.check_evidence(["s1"])
    for selection in [("other", "use", ["p1"]), ("ai", "base", ["p1"]), ("ai", "use", ["p2"])]:
        with pytest.raises(ValueError):
            content.selected(*selection)
    with pytest.raises(ValueError):
        content.check_evidence([])
    payload = content.model_dump()
    payload["candidates"].append(deepcopy(payload["candidates"][0]))
    with pytest.raises(ValidationError):
        ScopeContent.model_validate(payload)


@pytest.mark.parametrize("changes", [
    {"max_results": 11}, {"max_results": True}, {"city": "Shanghai"},
    {"api_key": "never-client-controlled"}, {"topic": "news", "country": "china"},
    {"time_range": "day", "start_date": "2026-01-01"},
    {"start_date": "2026-10-13", "end_date": "2026-01-01"},
    {"include_domains": ["https://example.com/path"]},
    {"include_domains": ["example.com"], "exclude_domains": ["example.com"]},
])
def test_search_parameter_boundary(changes):
    with pytest.raises(ValidationError):
        SearchParameters(query="learning", **changes)


def test_summary_full_and_focused_contracts_are_distinct():
    assert SearchParameters(query="HTTP").content_mode == "summary"
    assert SearchParameters(query="complex", content_mode="full", max_results=8).max_results == 8
    full = ExtractParameters(urls=["https://example.com/article"])
    assert full.query is None and full.chunks_per_source is None
    focused = ExtractParameters(urls=full.urls, content_mode="focused", query="HTTP", chunks_per_source=3)
    assert focused.content_mode == "focused"
    for payload in [
        {"urls": full.urls, "query": "HTTP"}, {"urls": full.urls, "chunks_per_source": 3},
        {"urls": full.urls, "content_mode": "focused"},
        {"urls": ["file:///local"]}, {"urls": ["https://user:password@example.com"]},
        {"urls": ["https://example.com/" + str(i) for i in range(4)]},
    ]:
        with pytest.raises(ValidationError):
            ExtractParameters(**payload)


def test_evidence_requires_actual_retrieval_metadata_without_inventing_dates():
    payload = {"id": "s1", "text": "正文", "content_kind": "full_extract", "url": "https://example.com", "retrieved_at": datetime.now(timezone.utc), "truncated": True}
    item = EvidenceSegment(**payload)
    assert item.published_at is None and item.truncated
    payload.pop("retrieved_at")
    with pytest.raises(ValidationError):
        EvidenceSegment(**payload)
    with pytest.raises(ValidationError):
        QuestionReview(question_id="q1", status="supported", reason="缺少引用")


@pytest.mark.parametrize("count", [3, 5])
def test_valid_draft_and_explicit_insufficient_knowledge(count):
    assert QuizDraftResult(status="ready", quiz=quiz_payload(count)).quiz is not None
    assert QuizDraftResult(status="insufficient_knowledge", reason="可用知识不足").quiz is None
    with pytest.raises(ValidationError):
        QuizDraftResult(status="insufficient_knowledge", quiz=quiz_payload(count), reason="不足")
    bad = quiz_payload(5)
    bad["questions"].pop(0)
    with pytest.raises(ValidationError):
        QuizDraftResult(status="ready", quiz=bad)


def test_legacy_quiz_and_material_sources_load_with_missing_new_fields():
    payload = old_quiz()
    quiz = Quiz.model_validate(payload)
    assert quiz.grounding is None and quiz.learning_scope is None
    assert all(q.grounding is None for q in quiz.questions)
    payload["source"] = {"type": "pdf", "material_id": "m1", "title": "旧 PDF", "url": None, "segments": [{"id": "s1", "text": "旧正文", "page": 2}]}
    quiz = Quiz.model_validate(payload)
    assert quiz.source.segments[0].page == 2
    assert QuizSource(type="topic", title="新主题").material_id is None
    with pytest.raises(ValidationError):
        QuizSource(type="topic", title="新主题", material_id="fake")


def test_url_learning_instruction_and_operation_are_not_sessions():
    body = LinkBody(url="https://example.com/article", learning_instruction="学习其中的应用案例")
    assert body.learning_instruction == "学习其中的应用案例"
    operation = GenerationOperation(key="k1", status="running", stage="retrieving", deadline=datetime.now(timezone.utc))
    assert operation.kind == "generation_operation"
    with pytest.raises(ValidationError):
        GenerationOperation.model_validate({"id": "session1", "quiz": old_quiz()})
    with pytest.raises(ValidationError):
        Preparation(id="p1", input_text="HTTP", status="ready", stage="ready", created_at=datetime.now(timezone.utc), expires_at=datetime.now(timezone.utc))
