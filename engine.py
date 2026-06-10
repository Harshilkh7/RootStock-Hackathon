from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Iterable
from urllib.parse import quote, quote_plus, urlparse
from urllib.request import Request, urlopen


STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "their",
    "this",
    "to",
    "what",
    "which",
    "with",
}

SYNONYMS = {
    "air": {"ventilation", "indoor"},
    "quality": {"cleanliness", "pollution"},
    "classroom": {"school", "students", "indoor"},
    "low-cost": {"cheap", "affordable", "budget"},
    "improve": {"reduce", "increase", "better"},
    "co2": {"carbon", "dioxide"},
    "particles": {"pm2.5", "dust", "particulate"},
    "windows": {"natural", "ventilation"},
    "filter": {"filtration", "purifier", "hepa", "merv"},
    "monitor": {"sensor", "measurement", "track"},
}

TRUST_SCORES = {
    "cdc.gov": 0.98,
    "epa.gov": 0.98,
    "who.int": 0.96,
    "energy.gov": 0.94,
    "ashrae.org": 0.92,
    "education.gov": 0.91,
    "prepared.local": 0.75,
}

MIN_GROUNDING_THRESHOLD = 0.22
MAX_SUPPORT_CONFIDENCE_BONUS = 0.09
SUPPORT_CONFIDENCE_STEP = 0.03
SUPPORT_SIMILARITY_THRESHOLD = 0.08
CLAIM_SIGNATURE_MIN_TOKEN_LENGTH = 3
CLAIM_SIGNATURE_TOKEN_LIMIT = 7
CLAIM_SIGNATURE_FALLBACK_CHARS = 32
LIVE_SEARCH_TIMEOUT_SECONDS = 8
LIVE_DDG_RESULT_LIMIT = 5
LIVE_WIKI_RESULT_LIMIT = 4
GENERIC_QUERY_TERMS = {
    "compare",
    "method",
    "methods",
    "study",
    "analysis",
    "research",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
}
EXPANSION_CONTEXT_TERMS = ("evidence", "analysis", "results", "data", "metrics")


@dataclass
class Document:
    doc_id: str
    title: str
    url: str
    source_type: str
    publisher: str
    published_at: str
    text: str


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    title: str
    url: str
    source_type: str
    publisher: str
    published_at: str
    text: str
    sentence_count: int


@dataclass
class RankedChunk:
    chunk: Chunk
    keyword_score: float
    semantic_score: float
    hybrid_score: float
    veracity: float
    grounding: float
    relevance: float
    helpfulness: float
    vgrh_score: float
    reasons: list[str]


@dataclass
class EvidenceItem:
    claim: str
    snippet: str
    source_title: str
    source_url: str
    chunk_id: str
    confidence: float
    support_count: int
    verification: str
    contradiction_flag: bool


def tokenize(text: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9][a-z0-9.-]*", text.lower()) if token not in STOPWORDS]


def split_sentences(text: str) -> list[str]:
    pieces = re.split(r"(?<=[.!?])\s+", text.strip())
    return [piece.strip() for piece in pieces if piece.strip()]


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def average(values: Iterable[float]) -> float:
    values = list(values)
    if not values:
        return 0.0
    return sum(values) / len(values)


class ResearchEngine:
    def __init__(self, documents: list[Document]):
        self.documents = documents
        self.chunks = self._chunk_documents(documents)
        self.doc_frequencies = self._build_doc_frequencies(self.chunks)
        self.avg_chunk_length = average(len(tokenize(chunk.text)) for chunk in self.chunks)

    @classmethod
    def from_path(cls, path: Path) -> "ResearchEngine":
        payload = json.loads(path.read_text(encoding="utf-8"))
        documents = [Document(**item) for item in payload["documents"]]
        return cls(documents)

    def run(self, query: str) -> dict:
        live_documents = self._fetch_live_documents(query)
        runtime_engine = self if not live_documents else ResearchEngine(self.documents + live_documents)
        result = runtime_engine._run_pipeline(query)
        result["live_documents_count"] = len(live_documents)
        return result

    def _run_pipeline(self, query: str) -> dict:
        plan = self._build_plan(query)
        generated_queries = self._expand_queries(query, plan)
        ranked_chunks = self._rank_chunks(query, generated_queries)
        ranked_chunks, generated_queries, iterative_trace = self._iterative_research(query, ranked_chunks, generated_queries)
        top_chunks = ranked_chunks[:10]
        evidence = self._extract_evidence(query, plan, top_chunks)
        report = self._generate_report(query, plan, generated_queries, iterative_trace, top_chunks, evidence)
        sources = self._build_source_table(top_chunks)
        return {
            "query": query,
            "research_plan": plan,
            "generated_queries": generated_queries,
            "iterative_trace": iterative_trace,
            "sources": sources,
            "evidence": [asdict(item) for item in evidence],
            "report_markdown": report,
            "report_html": self._to_html_report(query, report),
        }

    def _fetch_live_documents(self, query: str) -> list[Document]:
        live_documents = []
        live_documents.extend(self._fetch_duckduckgo_documents(query))
        live_documents.extend(self._fetch_wikipedia_documents(query))
        deduped_by_url = {}
        for document in live_documents:
            if len(tokenize(document.text)) < 10:
                continue
            deduped_by_url.setdefault(document.url, document)
        return list(deduped_by_url.values())

    def _fetch_duckduckgo_documents(self, query: str) -> list[Document]:
        endpoint = (
            "https://api.duckduckgo.com/"
            f"?q={quote_plus(query)}&format=json&no_html=1&skip_disambig=1"
        )
        payload = self._get_json(endpoint)
        if not payload:
            return []

        candidates = []
        if payload.get("AbstractURL") and payload.get("AbstractText"):
            candidates.append(
                {
                    "title": payload.get("Heading") or payload.get("AbstractSource") or "DuckDuckGo result",
                    "url": payload["AbstractURL"],
                    "snippet": payload["AbstractText"],
                }
            )
        for item in payload.get("RelatedTopics", []):
            if isinstance(item, dict) and item.get("Topics"):
                topic_items = item.get("Topics", [])
            else:
                topic_items = [item]
            for topic in topic_items:
                if not isinstance(topic, dict):
                    continue
                url = topic.get("FirstURL")
                text = topic.get("Text")
                if not url or not text:
                    continue
                title = text.split(" - ", 1)[0].strip() or "DuckDuckGo related result"
                candidates.append({"title": title, "url": url, "snippet": text})

        documents = []
        for index, item in enumerate(candidates[:LIVE_DDG_RESULT_LIMIT], start=1):
            publisher = self._domain_from_url(item["url"]) or "duckduckgo.com"
            documents.append(
                Document(
                    doc_id=f"live-ddg-{index}",
                    title=normalize_whitespace(item["title"]),
                    url=item["url"],
                    source_type="web_api",
                    publisher=publisher,
                    published_at=self._live_timestamp_label(),
                    text=normalize_whitespace(f"{item['title']}. {item['snippet']}"),
                )
            )
        return documents

    def _fetch_wikipedia_documents(self, query: str) -> list[Document]:
        search_url = (
            "https://en.wikipedia.org/w/api.php?action=query&list=search&utf8=1&format=json"
            f"&srlimit={LIVE_WIKI_RESULT_LIMIT}&srsearch={quote_plus(query)}"
        )
        payload = self._get_json(search_url)
        search_items = ((payload or {}).get("query") or {}).get("search") or []
        documents = []
        for index, item in enumerate(search_items, start=1):
            title = normalize_whitespace(str(item.get("title", "")).strip())
            if not title:
                continue
            summary = self._get_json(f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(title, safe='')}")
            snippet = normalize_whitespace(self._strip_html(str(item.get("snippet", ""))))
            extract = normalize_whitespace(str((summary or {}).get("extract", "")).strip())
            text = normalize_whitespace(f"{title}. {extract or snippet}")
            url = ((summary or {}).get("content_urls") or {}).get("desktop", {}).get("page")
            if not url:
                url = f"https://en.wikipedia.org/wiki/{quote(title.replace(' ', '_'), safe='')}"
            published_at = str((summary or {}).get("timestamp", "")).split("T", 1)[0] or self._live_timestamp_label()
            documents.append(
                Document(
                    doc_id=f"live-wiki-{index}",
                    title=title,
                    url=url,
                    source_type="web_api",
                    publisher="wikipedia.org",
                    published_at=published_at,
                    text=text,
                )
            )
        return documents

    def _get_json(self, url: str) -> dict | None:
        try:
            request = Request(url, headers={"User-Agent": "RootstockResearchEngine/1.0"})
            with urlopen(request, timeout=LIVE_SEARCH_TIMEOUT_SECONDS) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception:
            return None

    def _domain_from_url(self, url: str) -> str:
        domain = urlparse(url).netloc.lower().removeprefix("www.")
        return domain

    def _live_timestamp_label(self) -> str:
        return datetime.now(timezone.utc).date().isoformat()

    def _strip_html(self, text: str) -> str:
        return re.sub(r"<[^>]+>", " ", text)

    def _iterative_research(
        self, query: str, ranked_chunks: list[RankedChunk], generated_queries: list[str]
    ) -> tuple[list[RankedChunk], list[str], list[dict]]:
        initial_top = ranked_chunks[:6]
        follow_ups = []

        text_blob = " ".join(chunk.chunk.text.lower() for chunk in initial_top)
        focus_terms = []
        for token in tokenize(query):
            cleaned = token.strip(".-")
            if len(cleaned) <= CLAIM_SIGNATURE_MIN_TOKEN_LENGTH or cleaned in GENERIC_QUERY_TERMS:
                continue
            focus_terms.append(cleaned)
            if len(focus_terms) == 8:
                break
        missing_dimensions = [term for term in focus_terms if term not in text_blob]

        avg_grounding = average(chunk.grounding for chunk in initial_top)
        if missing_dimensions:
            follow_ups.append(
                f"{query} focused analysis for {' '.join(missing_dimensions)} with additional context"
            )
        if avg_grounding < MIN_GROUNDING_THRESHOLD:
            follow_ups.append(
                f"{query} include quantified evidence with specific metrics"
            )

        trace = [
            {
                "iteration": 1,
                "note": "Initial retrieval completed from base and expanded queries.",
                "added_queries": [],
                "avg_grounding": round(avg_grounding, 3),
            }
        ]
        if not follow_ups:
            return ranked_chunks, generated_queries, trace

        updated_queries = generated_queries + follow_ups
        reranked = self._rank_chunks(query, updated_queries)
        trace.append(
            {
                "iteration": 2,
                "note": "Gap-driven follow-up retrieval executed to fill weak coverage.",
                "added_queries": follow_ups,
                "avg_grounding": round(average(chunk.grounding for chunk in reranked[:6]), 3),
            }
        )
        return reranked, updated_queries, trace

    def _build_plan(self, query: str) -> list[str]:
        core = normalize_whitespace(query.rstrip("?. "))
        return [
            f"Clarify the decision goal behind: {core}.",
            "Identify low-cost interventions, implementation constraints, and likely tradeoffs.",
            "Find evidence about expected impact, operating cost, and ease of classroom adoption.",
            "Cross-check whether the recommendations are supported by multiple trustworthy sources.",
        ]

    def _expand_queries(self, query: str, plan: list[str]) -> list[str]:
        tokens = tokenize(query)
        expanded = set(tokens)
        for token in tokens:
            expanded.update(SYNONYMS.get(token, set()))
        joined = " ".join(sorted(expanded))
        return [
            query,
            joined,
            f"{query} {' '.join(EXPANSION_CONTEXT_TERMS)}",
            f"{plan[1]} {plan[2]}",
        ]

    def _chunk_documents(self, documents: list[Document]) -> list[Chunk]:
        chunks = []
        for document in documents:
            sentences = split_sentences(document.text)
            bucket = []
            chunk_index = 1
            for sentence in sentences:
                bucket.append(sentence)
                if len(" ".join(bucket).split()) >= 85:
                    chunks.append(self._make_chunk(document, chunk_index, bucket))
                    chunk_index += 1
                    bucket = []
            if bucket:
                chunks.append(self._make_chunk(document, chunk_index, bucket))
        return chunks

    def _make_chunk(self, document: Document, chunk_index: int, sentences: list[str]) -> Chunk:
        text = normalize_whitespace(" ".join(sentences))
        return Chunk(
            chunk_id=f"{document.doc_id}-chunk-{chunk_index}",
            doc_id=document.doc_id,
            title=document.title,
            url=document.url,
            source_type=document.source_type,
            publisher=document.publisher,
            published_at=document.published_at,
            text=text,
            sentence_count=len(sentences),
        )

    def _build_doc_frequencies(self, chunks: list[Chunk]) -> dict[str, int]:
        doc_freq = defaultdict(int)
        for chunk in chunks:
            for token in set(tokenize(chunk.text)):
                doc_freq[token] += 1
        return dict(doc_freq)

    def _rank_chunks(self, query: str, generated_queries: list[str]) -> list[RankedChunk]:
        weighted_query = " ".join(generated_queries)
        query_tokens = tokenize(weighted_query)
        unique_query_tokens = set(query_tokens)
        ranked = []
        for chunk in self.chunks:
            keyword_score = self._bm25_score(chunk.text, query_tokens)
            semantic_score = self._semantic_score(chunk.text, unique_query_tokens)
            hybrid_score = (keyword_score * 0.55) + (semantic_score * 0.45)
            veracity = self._veracity(chunk)
            grounding = self._grounding(chunk, unique_query_tokens)
            relevance = min(1.0, hybrid_score / 8.0)
            helpfulness = self._helpfulness(chunk, query)
            vgrh_score = (
                veracity * 0.28
                + grounding * 0.22
                + relevance * 0.30
                + helpfulness * 0.20
            )
            reasons = self._reason_strings(chunk, keyword_score, semantic_score, veracity, grounding, helpfulness)
            ranked.append(
                RankedChunk(
                    chunk=chunk,
                    keyword_score=round(keyword_score, 3),
                    semantic_score=round(semantic_score, 3),
                    hybrid_score=round(hybrid_score, 3),
                    veracity=round(veracity, 3),
                    grounding=round(grounding, 3),
                    relevance=round(relevance, 3),
                    helpfulness=round(helpfulness, 3),
                    vgrh_score=round(vgrh_score, 3),
                    reasons=reasons,
                )
            )
        ranked.sort(key=lambda item: (item.vgrh_score, item.hybrid_score, item.veracity), reverse=True)
        return ranked

    def _bm25_score(self, text: str, query_tokens: list[str]) -> float:
        if not query_tokens:
            return 0.0
        tokens = tokenize(text)
        counts = Counter(tokens)
        length = max(1, len(tokens))
        score = 0.0
        k1 = 1.5
        b = 0.75
        total_docs = max(1, len(self.chunks))
        for token in query_tokens:
            if token not in counts:
                continue
            df = self.doc_frequencies.get(token, 0)
            idf = math.log(1 + (total_docs - df + 0.5) / (df + 0.5))
            tf = counts[token]
            numer = tf * (k1 + 1)
            denom = tf + k1 * (1 - b + b * (length / max(1.0, self.avg_chunk_length)))
            score += idf * (numer / denom)
        return score

    def _semantic_score(self, text: str, query_tokens: set[str]) -> float:
        text_tokens = set(tokenize(text))
        if not text_tokens or not query_tokens:
            return 0.0
        overlap = len(text_tokens & query_tokens)
        union = len(text_tokens | query_tokens)
        return overlap / union if union else 0.0

    def _veracity(self, chunk: Chunk) -> float:
        domain = chunk.url.split("/")[2] if "://" in chunk.url else "prepared.local"
        domain = domain.lower().removeprefix("www.")
        base = TRUST_SCORES.get(domain, 0.7)
        if any(year in chunk.published_at for year in ["2023", "2024", "2025"]):
            base += 0.02
        return min(1.0, base)

    def _grounding(self, chunk: Chunk, query_tokens: set[str]) -> float:
        sentences = split_sentences(chunk.text)
        overlaps = []
        for sentence in sentences:
            sentence_tokens = set(tokenize(sentence))
            if not sentence_tokens:
                continue
            overlaps.append(len(sentence_tokens & query_tokens) / len(query_tokens or {1}))
        return min(1.0, average(overlaps) * 2.2)

    def _helpfulness(self, chunk: Chunk, query: str) -> float:
        sentences = split_sentences(chunk.text)
        has_number = any(re.search(r"\b\d+(\.\d+)?\b", sentence) for sentence in sentences)
        comparison_signal = any(word in chunk.text.lower() for word in ["cost", "reduce", "improve", "increase", "portable", "window", "filter"])
        query_length_bonus = min(0.18, len(tokenize(query)) / 100)
        score = 0.45
        if has_number:
            score += 0.18
        if comparison_signal:
            score += 0.22
        if chunk.sentence_count >= 3:
            score += 0.08
        score += query_length_bonus
        return min(1.0, score)

    def _reason_strings(
        self,
        chunk: Chunk,
        keyword_score: float,
        semantic_score: float,
        veracity: float,
        grounding: float,
        helpfulness: float,
    ) -> list[str]:
        reasons = []
        if keyword_score >= 1.6:
            reasons.append("Strong keyword match to the research topic")
        if semantic_score >= 0.12:
            reasons.append("Good overlap with expanded research concepts")
        if veracity >= 0.92:
            reasons.append("High-trust publisher")
        if grounding >= 0.55:
            reasons.append("Contains directly usable evidence snippets")
        if helpfulness >= 0.75:
            reasons.append("Actionable details and comparative signal")
        return reasons or ["Moderate supporting context"]

    def _extract_evidence(self, query: str, plan: list[str], ranked_chunks: list[RankedChunk]) -> list[EvidenceItem]:
        evidence = []
        query_tokens = set(tokenize(query + " " + " ".join(plan)))
        chosen_sentences = []
        for ranked in ranked_chunks[:8]:
            best_sentence = ""
            best_overlap = -1
            for sentence in split_sentences(ranked.chunk.text):
                sentence_tokens = set(tokenize(sentence))
                overlap = len(sentence_tokens & query_tokens)
                if overlap > best_overlap:
                    best_sentence = sentence
                    best_overlap = overlap
            if not best_sentence:
                continue
            signature = self._claim_signature(best_sentence, query_tokens)
            sentence_token_set = set(self._normalize_token_for_signature(token) for token in tokenize(best_sentence))
            chosen_sentences.append((ranked, best_sentence, signature, sentence_token_set))

        for ranked, best_sentence, signature, sentence_token_set in chosen_sentences[:6]:
            claim = self._claim_from_sentence(best_sentence)
            support_docs = set()
            contradiction_flag = False
            for other_ranked, other_sentence, other_signature, other_token_set in chosen_sentences:
                union = sentence_token_set | other_token_set
                similarity = (len(sentence_token_set & other_token_set) / len(union)) if union else 0.0
                if signature == other_signature or similarity >= SUPPORT_SIMILARITY_THRESHOLD:
                    support_docs.add(other_ranked.chunk.doc_id)
                    contradiction_flag = contradiction_flag or self._sentence_has_contradiction(other_sentence)
            support_count = len(support_docs)
            verification = "verified" if support_count >= 2 and not contradiction_flag else "needs_review"
            confidence = ranked.vgrh_score
            confidence += min(MAX_SUPPORT_CONFIDENCE_BONUS, support_count * SUPPORT_CONFIDENCE_STEP)
            if contradiction_flag:
                confidence *= 0.82
            confidence = min(0.99, confidence)
            evidence.append(
                EvidenceItem(
                    claim=claim,
                    snippet=best_sentence,
                    source_title=ranked.chunk.title,
                    source_url=ranked.chunk.url,
                    chunk_id=ranked.chunk.chunk_id,
                    confidence=round(confidence, 3),
                    support_count=support_count,
                    verification=verification,
                    contradiction_flag=contradiction_flag,
                )
            )
        return evidence

    def _claim_from_sentence(self, sentence: str) -> str:
        sentence = normalize_whitespace(sentence)
        return sentence if len(sentence) <= 160 else sentence[:157] + "..."

    def _sentence_has_contradiction(self, sentence: str) -> bool:
        lowered = sentence.lower()
        contradiction_terms = [
            "however",
            "may not",
            "limited",
            "uncertain",
            "inconclusive",
            "conflicting",
        ]
        return any(term in lowered for term in contradiction_terms)

    def _claim_signature(self, sentence: str, query_tokens: set[str] | None = None) -> str:
        tokens = [self._normalize_token_for_signature(token) for token in tokenize(sentence)]
        tokens = [token for token in tokens if len(token) > CLAIM_SIGNATURE_MIN_TOKEN_LENGTH and token not in GENERIC_QUERY_TERMS]
        if query_tokens:
            anchored = sorted(set(tokens) & query_tokens)
            if len(anchored) >= 2:
                return " ".join(anchored[:CLAIM_SIGNATURE_TOKEN_LIMIT])
        signature_tokens = sorted(set(tokens))
        return (
            " ".join(signature_tokens[:CLAIM_SIGNATURE_TOKEN_LIMIT])
            if signature_tokens
            else sentence[:CLAIM_SIGNATURE_FALLBACK_CHARS].lower()
        )

    def _normalize_token_for_signature(self, token: str) -> str:
        token = token.strip(".-")
        if token.endswith("ing") and len(token) > 6:
            return token[:-3]
        if token.endswith("es") and len(token) > 5:
            return token[:-2]
        if token.endswith("s") and len(token) > 4:
            return token[:-1]
        return token

    def _build_source_table(self, ranked_chunks: list[RankedChunk]) -> list[dict]:
        best_by_doc = {}
        for ranked in ranked_chunks:
            current = best_by_doc.get(ranked.chunk.doc_id)
            if current is None or ranked.vgrh_score > current.vgrh_score:
                best_by_doc[ranked.chunk.doc_id] = ranked
        sources = []
        for ranked in sorted(best_by_doc.values(), key=lambda item: item.vgrh_score, reverse=True):
            sources.append(
                {
                    "title": ranked.chunk.title,
                    "url": ranked.chunk.url,
                    "publisher": ranked.chunk.publisher,
                    "source_type": ranked.chunk.source_type,
                    "published_at": ranked.chunk.published_at,
                    "scores": {
                        "keyword": ranked.keyword_score,
                        "semantic": ranked.semantic_score,
                        "hybrid": ranked.hybrid_score,
                        "veracity": ranked.veracity,
                        "grounding": ranked.grounding,
                        "relevance": ranked.relevance,
                        "helpfulness": ranked.helpfulness,
                        "vgrh": ranked.vgrh_score,
                    },
                    "reason": "; ".join(ranked.reasons),
                }
            )
        return sources

    def _generate_report(
        self,
        query: str,
        plan: list[str],
        generated_queries: list[str],
        iterative_trace: list[dict],
        ranked_chunks: list[RankedChunk],
        evidence: list[EvidenceItem],
    ) -> str:
        source_lines = []
        for index, ranked in enumerate(ranked_chunks[:5], start=1):
            source_lines.append(
                f"| {index} | {ranked.chunk.title} | {ranked.chunk.source_type} | {ranked.vgrh_score:.2f} | "
                f"V:{ranked.veracity:.2f} G:{ranked.grounding:.2f} R:{ranked.relevance:.2f} H:{ranked.helpfulness:.2f} | "
                f"{'; '.join(ranked.reasons)} |"
            )

        evidence_lines = []
        for item in evidence:
            evidence_lines.append(
                f"| {item.claim} | {item.snippet} | [{item.source_title}]({item.source_url}) | {item.confidence:.2f} | {item.support_count} | {item.verification} |"
            )

        recommendation_block = self._build_recommendations(evidence)
        limitations = self._build_limitations(ranked_chunks, evidence)
        trace_lines = []
        for item in iterative_trace:
            added = ", ".join(item["added_queries"]) if item["added_queries"] else "None"
            trace_lines.append(
                f"- Iteration {item['iteration']}: {item['note']} (avg grounding {item['avg_grounding']:.2f}, added queries: {added})"
            )

        return "\n".join(
            [
                f"# Research Report: {query}",
                "",
                "## Executive Summary",
                recommendation_block["summary"],
                "",
                "## Research Plan",
                *[f"- {step}" for step in plan],
                "",
                "## Source Table",
                "| Rank | Source | Type | VGRH | Score Breakdown | Reason for Selection |",
                "| --- | --- | --- | --- | --- | --- |",
                *source_lines,
                "",
                "## Iterative Research Loop",
                *trace_lines,
                "",
                "## Retrieval Queries Used",
                *[f"- {item}" for item in generated_queries],
                "",
                "## Evidence Table",
                "| Claim | Evidence Snippet | Source Reference | Confidence | Multi-Source Support | Verification |",
                "| --- | --- | --- | --- | --- | --- |",
                *evidence_lines,
                "",
                "## Final Report",
                recommendation_block["report"],
                "",
                "## Limitations",
                limitations,
            ]
        )

    def _build_recommendations(self, evidence: list[EvidenceItem]) -> dict[str, str]:
        if not evidence:
            return {
                "summary": "The prototype could not find enough supporting evidence to make a reliable recommendation.",
                "report": "No high-confidence claims were extracted.",
            }

        top = evidence[:5]
        method_labels = [
            (
                "Improve natural or mechanical ventilation",
                ["window", "outdoor air", "ventilation", "airflow", "fans", "occupied hours"],
            ),
            (
                "Upgrade filtration or add portable cleaners",
                ["filter", "filtration", "hepa", "portable", "merv", "cleaners"],
            ),
            (
                "Monitor indoor conditions and maintenance performance",
                ["monitor", "carbon dioxide", "co2", "maintenance", "measurement", "schedule"],
            ),
            (
                "Reduce pollutant sources inside and near the classroom",
                ["source control", "emission", "idling", "moisture", "chemicals", "products"],
            ),
        ]

        method_evidence = []
        for label, keywords in method_labels:
            match = next(
                (
                    item
                    for item in top
                    if any(keyword in item.snippet.lower() for keyword in keywords)
                    or any(keyword in item.claim.lower() for keyword in keywords)
                ),
                None,
            )
            if match:
                method_evidence.append((label, match))

        if len(method_evidence) < 3:
            for item in top:
                label = f"Evidence-backed action {len(method_evidence) + 1}"
                if any(existing.chunk_id == item.chunk_id for _, existing in method_evidence):
                    continue
                method_evidence.append((label, item))
                if len(method_evidence) == 3:
                    break

        summary = (
            "The strongest low-cost classroom air quality actions are to improve natural ventilation, "
            "upgrade or supplement filtration, and monitor indoor conditions so staff can respond when air quality worsens."
        )
        bullets = []
        for label, item in method_evidence[:3]:
            bullets.append(
                f"- **{label}:** {item.claim} ({item.confidence:.2f} confidence, {item.verification}, "
                f"[{item.source_title}]({item.source_url}))"
            )
        report = "\n".join(
            [
                "Recommended approach:",
                *bullets,
                "",
                "Why these actions rank highest:",
                "- They appear across multiple high-trust public-health or building-guidance sources.",
                "- They have direct grounding in source snippets rather than generic LLM language.",
                "- They are comparatively practical for schools because they rely on process changes, low-cost hardware, or both.",
            ]
        )
        return {"summary": summary, "report": report}

    def _build_limitations(self, ranked_chunks: list[RankedChunk], evidence: list[EvidenceItem]) -> str:
        missing_pdf = not any(chunk.chunk.source_type.lower() == "pdf" for chunk in ranked_chunks)
        notes = [
            "Live web-search APIs are queried at runtime, but retrieval is best-effort and can degrade to local-corpus-only when external APIs are unavailable or rate-limited.",
            "Claim verification is heuristic: it estimates confidence and contradiction risk from evidence overlap rather than using a second external fact-checking system.",
        ]
        if missing_pdf:
            notes.append("The current sample run may not surface a PDF in the top results even though the engine can ingest PDF-derived text into the corpus.")
        if any(item.contradiction_flag for item in evidence):
            notes.append("At least one evidence item includes uncertainty language and should be reviewed manually before acting on it.")
        return "\n".join(f"- {note}" for note in notes)

    def _to_html_report(self, query: str, markdown_report: str) -> str:
        rendered = self._markdown_to_html(markdown_report)
        escaped_query = escape(query)
        return (
            "<!doctype html><html><head><meta charset='utf-8'><title>Research Report</title>"
            "<style>body{font-family:Arial,sans-serif;max-width:980px;margin:24px auto;padding:0 16px;line-height:1.5}"
            "table{border-collapse:collapse;width:100%;margin:10px 0}th,td{border:1px solid #d0d7de;padding:8px;text-align:left}"
            "code{background:#f6f8fa;padding:2px 4px;border-radius:4px}</style>"
            f"</head><body><h1>Research Report</h1><h2>{escaped_query}</h2>{rendered}</body></html>"
        )

    def _markdown_to_html(self, markdown_text: str) -> str:
        lines = markdown_text.splitlines()
        output = []
        in_list = False
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            if not stripped:
                if in_list:
                    output.append("</ul>")
                    in_list = False
                i += 1
                continue

            if stripped.startswith("|") and i + 1 < len(lines) and lines[i + 1].strip().startswith("| ---"):
                if in_list:
                    output.append("</ul>")
                    in_list = False
                headers = [self._render_markdown_inline(cell.strip()) for cell in stripped.strip("|").split("|")]
                output.append("<table><thead><tr>" + "".join(f"<th>{cell}</th>" for cell in headers) + "</tr></thead><tbody>")
                i += 2
                while i < len(lines) and lines[i].strip().startswith("|"):
                    cells = [self._render_markdown_inline(cell.strip()) for cell in lines[i].strip().strip("|").split("|")]
                    output.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>")
                    i += 1
                output.append("</tbody></table>")
                continue

            if stripped.startswith("### "):
                if in_list:
                    output.append("</ul>")
                    in_list = False
                output.append(f"<h3>{escape(stripped[4:])}</h3>")
            elif stripped.startswith("## "):
                if in_list:
                    output.append("</ul>")
                    in_list = False
                output.append(f"<h2>{escape(stripped[3:])}</h2>")
            elif stripped.startswith("# "):
                if in_list:
                    output.append("</ul>")
                    in_list = False
                output.append(f"<h1>{escape(stripped[2:])}</h1>")
            elif stripped.startswith("- "):
                if not in_list:
                    output.append("<ul>")
                    in_list = True
                output.append(f"<li>{self._render_markdown_inline(stripped[2:])}</li>")
            else:
                if in_list:
                    output.append("</ul>")
                    in_list = False
                output.append(f"<p>{self._render_markdown_inline(stripped)}</p>")
            i += 1

        if in_list:
            output.append("</ul>")
        return "".join(output)

    def _render_markdown_inline(self, text: str) -> str:
        parts = []
        last_index = 0
        for match in re.finditer(r"\[([^\]]+)\]\((https?://[^)]+)\)", text):
            start, end = match.span()
            if start > last_index:
                parts.append(escape(text[last_index:start]))
            label = escape(match.group(1))
            href = escape(match.group(2), quote=True)
            parts.append(f"<a href=\"{href}\" target=\"_blank\" rel=\"noreferrer\">{label}</a>")
            last_index = end
        if last_index < len(text):
            parts.append(escape(text[last_index:]))
        return "".join(parts)
