"""Retrieves the policy rules relevant to a given invoice, instead of stuffing the entire
rulebook into every LLM prompt (N5).

Pure-Python TF-IDF + cosine similarity — no embedding model or vector DB. The policy handbook
here is 9 rules, but the retrieval scales the same way a real, much larger handbook would: the
prompt only grows with how specific an invoice is, not with how big the policy document is.
Deterministic and offline, so it needs no extra dependency and works the same in CI (stub LLM
provider) as it does with a real one.
"""
import math
import re
from collections import Counter

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _build_documents(policy: dict) -> dict[str, str]:
    """One retrievable passage per rule: id + description + any structured fields, so a rule
    matches on its id/category vocabulary even when its prose description doesn't repeat it."""
    documents = {}
    for rule_id, rule in policy.get("rules", {}).items():
        if not isinstance(rule, dict):
            documents[rule_id] = f"{rule_id} {rule}"
            continue
        parts = [rule_id, rule.get("description", "")]
        if "limit" in rule:
            parts.append(f"limit {rule['limit']}")
        if rule.get("fields"):
            parts.append("requires " + " ".join(rule["fields"]))
        if rule.get("action"):
            parts.append(str(rule["action"]))
        if rule.get("reimbursable") is False:
            parts.append("not reimbursable")
        documents[rule_id] = " ".join(str(p) for p in parts)
    return documents


def _invoice_query_text(invoice: dict) -> str:
    parts = [invoice.get("category", ""), invoice.get("notes") or ""]
    for item in invoice.get("lineItems", []) or []:
        parts.append(item.get("description", ""))
    return " ".join(parts)


def _tfidf_vectors(documents: dict[str, str]) -> tuple[dict[str, Counter], dict[str, float]]:
    tokenized = {doc_id: _tokenize(text) for doc_id, text in documents.items()}

    document_frequency = Counter()
    for tokens in tokenized.values():
        document_frequency.update(set(tokens))

    n_docs = len(tokenized) or 1
    idf = {
        term: math.log((n_docs + 1) / (count + 1)) + 1
        for term, count in document_frequency.items()
    }

    vectors = {
        doc_id: Counter({term: freq * idf.get(term, 0.0) for term, freq in Counter(tokens).items()})
        for doc_id, tokens in tokenized.items()
    }
    return vectors, idf


def _cosine(a: Counter, b: Counter) -> float:
    common_terms = set(a) & set(b)
    numerator = sum(a[term] * b[term] for term in common_terms)
    norm_a = math.sqrt(sum(value * value for value in a.values()))
    norm_b = math.sqrt(sum(value * value for value in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return numerator / (norm_a * norm_b)


def retrieve_relevant_rules(invoice: dict, policy: dict, top_k: int = 4) -> list[dict]:
    """Top-`top_k` policy rules most relevant to this invoice, ranked by TF-IDF cosine
    similarity against the invoice's category/notes/line-item text."""
    documents = _build_documents(policy)
    if not documents:
        return []

    vectors, idf = _tfidf_vectors(documents)

    query_tf = Counter(_tokenize(_invoice_query_text(invoice)))
    query_vector = Counter({term: freq * idf.get(term, 0.0) for term, freq in query_tf.items()})

    scored = sorted(
        ((rule_id, _cosine(query_vector, vectors[rule_id])) for rule_id in documents),
        key=lambda pair: pair[1],
        reverse=True,
    )
    top = scored[:top_k]

    # An invoice whose vocabulary doesn't overlap any rule's (e.g. a category/description that
    # shares no words with the handbook) must still get the full policy, not an empty prompt —
    # an under-informed LLM has no way to comply with a rule it was never shown.
    if not any(score > 0 for _, score in top):
        top = [(rule_id, 0.0) for rule_id in documents]

    return [{"rule_id": rule_id, "score": round(score, 4)} for rule_id, score in top]
