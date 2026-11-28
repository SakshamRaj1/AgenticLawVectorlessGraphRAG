import json
import re
from pathlib import Path
from typing import Any
from dotenv import load_dotenv
import litellm

load_dotenv()

# Swap easily between Groq, Gemini, or local Ollama via LiteLLM format
DEFAULT_MODEL = "groq/llama-3.3-70b-versatile"

# Clean display names for your 5 indexed statutes
CANONICAL_TITLES = {
    "bnsAct2023": "Bharatiya Nyaya Sanhita, 2023 (BNS)",
    "bnssAct2023": "Bharatiya Nagarik Suraksha Sanhita, 2023 (BNSS)",
    "constitutionOfIndia1950": "Constitution of India, 1950",
    "dpdpAct2023": "Digital Personal Data Protection Act, 2023 (DPDP Act)",
    "itAct2020": "Information Technology Act (IT Act)",
}

# Front-matter titles to hide from statutory retrieval so the LLM doesn't fetch ToC pages
SKIP_TOP_LEVEL_TITLES = {"homepage", "index", "table of contents", "contents"}


# ── 1. Multi-Document Corpus Loader ──────────────────────────────────────────

def _namespace_nodes(
    nodes: list[dict],
    doc_key: str,
    node_index: dict[str, dict],
    skip_front_matter: bool = False,
) -> list[dict]:
    """Attach globally unique IDs (`doc_key::node_id`) and populate an O(1) lookup map."""
    cleaned = []
    for node in nodes:
        title = str(node.get("title", "")).strip()
        if skip_front_matter and title.lower() in SKIP_TOP_LEVEL_TITLES:
            continue

        ns_id = f"{doc_key}::{node['node_id']}"
        new_node = {
            "node_id": ns_id,
            "doc_key": doc_key,
            "title": title,
            "start_index": node.get("start_index"),
            "end_index": node.get("end_index"),
        }
        if node.get("summary"):
            new_node["summary"] = node["summary"]

        children = node.get("nodes", [])
        if children:
            new_node["nodes"] = _namespace_nodes(children, doc_key, node_index, skip_front_matter=False)

        node_index[ns_id] = new_node
        cleaned.append(new_node)
    return cleaned


def load_legal_corpus(index_dir: str = "./legal_index") -> dict[str, Any]:
    """Load all indexed statute trees and verbatim page stores into one unified forest."""
    base = Path(index_dir)
    manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))

    forest: list[dict] = []       # Unified super-tree: [Act 1, Act 2, ...]
    node_index: dict[str, dict] = {}   # "doc_key::0148" -> node dict
    pages_store: dict[str, dict] = {}  # "doc_key" -> {"1": "verbatim text...", ...}

    for doc_key, meta in manifest.items():
        tree_path = Path(meta["tree_file"])
        pages_path = Path(meta["pages_file"])

        raw_tree = json.loads(tree_path.read_text(encoding="utf-8"))
        raw_nodes = raw_tree.get("structure", raw_tree) if isinstance(raw_tree, dict) else raw_tree

        pages_store[doc_key] = json.loads(pages_path.read_text(encoding="utf-8"))

        children = _namespace_nodes(raw_nodes, doc_key, node_index, skip_front_matter=True)
        act_root = {
            "node_id": f"{doc_key}::ROOT",
            "doc_key": doc_key,
            "title": CANONICAL_TITLES.get(doc_key, raw_tree.get("doc_title", doc_key)),
            "start_index": 1,
            "end_index": meta.get("page_count"),
            "nodes": children,
        }
        node_index[act_root["node_id"]] = act_root
        forest.append(act_root)

    return {
        "forest": forest,
        "node_index": node_index,
        "pages": pages_store,
        "manifest": manifest,
    }


# ── 2. Tree Utilities (Matches Your Snippet Interface) ───────────────────────

def count_nodes(tree_or_corpus: Any) -> int:
    """Count total nodes in a single tree OR across the entire multi-doc corpus."""
    if isinstance(tree_or_corpus, dict):
        if "forest" in tree_or_corpus:
            nodes = tree_or_corpus["forest"]
        elif "structure" in tree_or_corpus:
            nodes = tree_or_corpus["structure"]
        else:
            nodes = [tree_or_corpus]
    else:
        nodes = tree_or_corpus

    return sum(1 + count_nodes(n.get("nodes", [])) for n in nodes)


def print_tree(tree_or_corpus: Any, max_depth: int = 2, _depth: int = 0) -> None:
    """Pretty-print the unified forest up to `max_depth` levels."""
    if _depth == 0 and isinstance(tree_or_corpus, dict):
        nodes = tree_or_corpus.get("forest") or tree_or_corpus.get("structure") or [tree_or_corpus]
    else:
        nodes = tree_or_corpus

    for n in nodes:
        indent = "  " * _depth
        pp = f"pp. {n.get('start_index')}-{n.get('end_index')}"
        child_count = len(n.get("nodes", []))
        suffix = f" ({child_count} sub-nodes)" if child_count and _depth >= max_depth else ""
        print(f"{indent}├─ [{n['node_id']}] {n['title']} ({pp}){suffix}")
        if _depth < max_depth and n.get("nodes"):
            print_tree(n["nodes"], max_depth=max_depth, _depth=_depth + 1)


def _prune_outline(nodes: list[dict], max_depth: int, _depth: int = 0) -> list[dict]:
    """Create a compact JSON outline capped at `max_depth` to keep routing prompts small."""
    out = []
    for n in nodes:
        item = {
            "node_id": n["node_id"],
            "title": n["title"],
            "pages": f"{n.get('start_index')}-{n.get('end_index')}",
        }
        if n.get("summary"):
            item["summary"] = n["summary"]
        if _depth < max_depth and n.get("nodes"):
            item["nodes"] = _prune_outline(n["nodes"], max_depth, _depth + 1)
        out.append(item)
    return out


# ── 3. LLM JSON Helper & Verbatim Page Fetcher ───────────────────────────────

def _llm_json(prompt: str, model: str) -> dict:
    resp = litellm.completion(
        model=model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}],
    )
    content = resp.choices[0].message.content or "{}"
    match = re.search(r"\{.*\}", content, flags=re.S)
    return json.loads(match.group(0) if match else content)


def _fetch_verbatim_context(
    node_ids: list[str],
    corpus: dict[str, Any],
    max_total_pages: int = 16,
) -> tuple[str, list[dict]]:
    """Deterministically pull verbatim statutory text from *_pages.json for selected nodes."""
    blocks = []
    citations = []
    pages_fetched = 0
    seen_pages: set[tuple[str, int]] = set()

    for nid in node_ids:
        node = corpus["node_index"].get(nid)
        if not node or node.get("start_index") is None:
            continue

        doc_key = node["doc_key"]
        act_name = CANONICAL_TITLES.get(doc_key, doc_key)
        doc_pages = corpus["pages"].get(doc_key, {})
        start_p = int(node["start_index"])
        end_p = int(node.get("end_index") or start_p)

        node_text_parts = []
        used_pages = []
        for p in range(start_p, end_p + 1):
            if pages_fetched >= max_total_pages:
                break
            if (doc_key, p) in seen_pages:
                continue
            page_text = doc_pages.get(str(p))
            if page_text:
                seen_pages.add((doc_key, p))
                pages_fetched += 1
                used_pages.append(p)
                node_text_parts.append(f"[Page {p}]\n{page_text}")

        if node_text_parts:
            citations.append({
                "node_id": nid,
                "act": act_name,
                "title": node["title"],
                "pages": used_pages,
            })
            header = f"=== {act_name} | {node['title']} | Node {nid} (pp. {used_pages[0]}-{used_pages[-1]}) ==="
            blocks.append(header + "\n" + "\n".join(node_text_parts))

    return "\n\n".join(blocks), citations


# ── 4. Multi-Document Vectorless RAG Pipeline ────────────────────────────────

def vectorless_rag(
    query: str,
    corpus: dict[str, Any],
    model: str = DEFAULT_MODEL,
    max_stage1_nodes: int = 4,
    max_leaf_nodes: int = 5,
    max_total_pages: int = 16,
) -> dict[str, Any]:
    """
    2-Stage Multi-Document Vectorless RAG over all indexed Indian statutes:
      Stage 1: Route query across all Acts & top-level chapters.
      Stage 2: Drill into selected subtrees to pick exact section/leaf nodes.
      Stage 3: Deterministic verbatim page lookup + grounded legal synthesis (fail-closed).
    """
    # --- Stage 1: Coarse routing across ALL 5 Acts (depth=1: Act -> Parts/Chapters) ---
    coarse_outline = _prune_outline(corpus["forest"], max_depth=1)
    stage1_prompt = f"""You are an Indian legal statutory router.
Given the user's legal query and the table of contents of ALL indexed Indian statutes below, select up to {max_stage1_nodes} most relevant branch node_ids (chapters/parts across one or multiple Acts) that are likely to contain the controlling statutory text.

Return STRICT JSON:
{{
  "reasoning": "brief legal issue breakdown",
  "selected_nodes": ["doc_key::node_id", ...]
}}

Query: {query}

Statutes Outline:
{json.dumps(coarse_outline, ensure_ascii=False)}
"""
    s1 = _llm_json(stage1_prompt, model)
    s1_ids = [nid for nid in s1.get("selected_nodes", []) if nid in corpus["node_index"]][:max_stage1_nodes]

    if not s1_ids:
        return {
            "answer": "INSUFFICIENT STATUTORY GROUNDING: No relevant Act or chapter matched the query in the indexed corpus.",
            "status": "fail_closed",
            "citations": [],
            "trace": {"stage1": s1, "stage2": None},
        }

    # --- Stage 2: Fine-grained node selection inside the routed subtrees ---
    expanded_subtrees = []
    for nid in s1_ids:
        node = corpus["node_index"][nid]
        expanded_subtrees.extend(_prune_outline([node], max_depth=3))

    stage2_prompt = f"""You are a deterministic statutory tree navigator.
From the expanded subtrees below, select up to {max_leaf_nodes} MOST SPECIFIC leaf/section node_ids that contain the verbatim statutory provisions (including provisos, exceptions, or punishments) needed to answer the query.
Prefer narrow page ranges over broad parent chapters. Do NOT invent node_ids.

Return STRICT JSON:
{{
  "reasoning": "why these exact nodes answer the query",
  "selected_nodes": ["doc_key::node_id", ...]
}}

Query: {query}

Expanded Subtrees:
{json.dumps(expanded_subtrees, ensure_ascii=False)}
"""
    s2 = _llm_json(stage2_prompt, model)
    leaf_ids = [nid for nid in s2.get("selected_nodes", []) if nid in corpus["node_index"]][:max_leaf_nodes]
    if not leaf_ids:
        leaf_ids = s1_ids  # fallback to stage-1 selections if already leaf-level

    # --- Stage 3: Deterministic verbatim retrieval + fail-closed synthesis ---
    context, citations = _fetch_verbatim_context(leaf_ids, corpus, max_total_pages=max_total_pages)

    if not context.strip():
        return {
            "answer": "INSUFFICIENT STATUTORY GROUNDING: Selected nodes had no retrievable statutory pages.",
            "status": "fail_closed",
            "citations": [],
            "trace": {"stage1": s1, "stage2": s2},
        }

    synth_prompt = f"""You are an Indian legal reasoning engine operating under strict fail-closed rules.
Answer the query using ONLY the verbatim statutory excerpts provided below.
Rules:
1. Cite the exact Act, Article/Section number, and page number for every legal claim.
2. Quote key operative phrases, provisos, or exceptions verbatim where relevant.
3. If the provided excerpts do NOT contain enough information to answer any part of the query, explicitly state what is missing instead of guessing or relying on outside memory.

Query: {query}

Retrieved Verbatim Statutory Text:
{context}
"""
    final_resp = litellm.completion(
        model=model,
        temperature=0,
        messages=[{"role": "user", "content": synth_prompt}],
    )

    return {
        "answer": final_resp.choices[0].message.content,
        "status": "grounded",
        "citations": citations,
        "trace": {"stage1": s1, "stage2": s2},
    }


# ── 5. Run Across All 5 Statutes at Once ─────────────────────────────────────

if __name__ == "__main__":
    corpus = load_legal_corpus("./legal_index")
    print(f"Unified Legal Forest loaded: {len(corpus['forest'])} Acts | {count_nodes(corpus)} total nodes\n")
    print_tree(corpus, max_depth=1)

    # Cross-statute query spanning Constitution + DPDP Act / IT Act
    query = (
        "How does the DPDP Act 2023 regulate consent and legitimate uses for processing personal data, "
        "and which Fundamental Right under the Constitution of India protects personal liberty?"
    )
    print(f"\nQuery: {query}\n")
    result = vectorless_rag(query, corpus)

    print("=== ANSWER ===\n")
    print(result["answer"])
    print("\n=== VERIFIED RETRIEVAL TRACE ===")
    for c in result["citations"]:
        print(f" - [{c['node_id']}] {c['act']} | {c['title']} | pp. {c['pages']}")