import pytest

from backend.app.rag_service import SimpleRAGService


def test_simple_rag_service_requires_settings():
    with pytest.raises(Exception):
        SimpleRAGService(None)


def test_simple_rag_service_init(monkeypatch):
    class FakeDomain:
        class manifest:
            class rag:
                tool_name = "vector_search"
                status_text = "Searching..."
                generating_text = "Generating..."
                index_name_contains = "chunk"
                vector_field = "content_embedding"
                return_fields = ["text"]
                num_results = 3
                answer_system_prompt = "Answer."
                title_fields = ["title"]
                label_fields = ["label"]
                body_fields = ["content"]

    class FakeSettings:
        openai_api_key = "test"
        openai_base_url = None
        openai_embedding_model = "text-embedding-3-small"
        openai_chat_model = "gpt-4.1-mini"

    monkeypatch.setattr("backend.app.rag_service.get_active_domain", lambda s: FakeDomain())
    service = SimpleRAGService(FakeSettings())
    assert service.domain is not None
