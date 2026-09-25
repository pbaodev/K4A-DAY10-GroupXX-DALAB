from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langchain.tools import tool

from core.config import Settings, normalized_provider
from core.utils import write_json
from retrieval.index import LocalEmbeddingIndex
from retrieval.llm import build_llm


def build_agent(settings: Settings, index: LocalEmbeddingIndex):
    @tool
    def semantic_search_papers(query: str, top_k: int = 4) -> str:
        """Search the local paper corpus with embeddings and return the most relevant papers."""
        results = index.search(query, top_k=top_k)
        lines = []
        for result in results:
            lines.append(
                f"paper_id: {result.paper_id}\n"
                f"title: {result.title}\n"
                f"score: {result.score:.4f}\n"
                f"{result.content}"
            )
        return "\n\n".join(lines)

    @tool
    def lookup_paper(paper_id_or_title: str) -> str:
        """Look up a paper by exact paper_id or exact title from the local corpus."""
        record = index.lookup(paper_id_or_title)
        if not record:
            return "No exact paper match found."
        return (
            f"paper_id: {record['paper_id']}\n"
            f"title: {record['title']}\n"
            f"{record['content']}"
        )

    llm = build_llm(settings=settings, temperature=0.0)
    return create_agent(
        model=llm,
        tools=[semantic_search_papers, lookup_paper],
        system_prompt=(
            "You answer questions about the indexed scholarly paper corpus sourced from Crossref. "
            "Use tools before answering factual questions. "
            "If the indexed corpus does not support the answer, say so clearly."
        ),
        name="paper_corpus_agent",
    )


def run_agent_question(agent: Any, question: str) -> str:
    result = agent.invoke({"messages": [{"role": "user", "content": question}]})
    messages = result.get("messages", [])
    if not messages:
        return ""
    final_message = messages[-1]
    return getattr(final_message, "content", str(final_message))


def run_agent_demo(
    settings: Settings,
    index: LocalEmbeddingIndex,
    questions: list[str],
    output_path,
) -> list[dict[str, Any]]:
    """Run the tool-calling agent on a few questions; never fail the pipeline, record why instead."""
    provider = normalized_provider(settings)

    def describe(exc: Exception) -> str:
        detail = str(exc) or ("the mock LLM cannot call tools" if provider == "mock" else "no error message")
        return f"{type(exc).__name__}: {detail}"

    rows: list[dict[str, Any]] = []
    try:
        agent = build_agent(settings, index)
        build_error = None
    except Exception as exc:
        agent = None
        build_error = describe(exc)

    for question in questions:
        row = {"question": question, "provider": provider, "model": settings.model_name}
        if agent is None:
            row.update(status="skipped", answer="", reason=f"Agent unavailable: {build_error}")
        else:
            try:
                answer = run_agent_question(agent, question)
                row.update(status="ok", answer=answer if isinstance(answer, str) else str(answer), reason="")
            except Exception as exc:
                row.update(status="skipped", answer="", reason=describe(exc))
        rows.append(row)

    write_json(Path(output_path), rows)
    return rows
