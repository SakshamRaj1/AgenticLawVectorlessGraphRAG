import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Literal, TypedDict

import litellm
from dotenv import load_dotenv
from langgraph.graph import END, START, StateGraph
from litellm import Router

load_dotenv()
litellm.drop_params = True  # safely strips reasoning_effort on non-reasoning fallback models

INDEX_DIR = Path("./legal_index") if Path("./legal_index").exists() else Path("../legal_index")

# Actual statutory body start pages (skips ToC and BNS Compare table pp. 20-73)
STATUTE_START_PAGE = {
    "bnsAct2023": 74,
    "constitutionOfIndia1950": 32,
    "itAct2020": 5,
}


# ── 1. Multi-Provider Router with Cooldowns ──────────────────────────────────

LLM_ROUTER = Router(
    model_list=[
        {
            "model_name": "legal-primary",
            "litellm_params": {
                "model": "gemini/gemini-3.5-flash-lite",
                "reasoning_effort": "low",
            },
        },
        {
            "model_name": "legal-groq-fast",
            "litellm_params": {
                "model": "groq/llama-3.3-70b-versatile",
            },
        },
        {
            "model_name": "legal-local-ollama",
            "litellm_params": {
                "model": "ollama_chat/qwen2.5:3b",
                "api_base": "http://localhost:11434",
            },
        },
    ],
    fallbacks=[{"legal-primary": ["legal-groq-fast", "legal-local-ollama"]}],
    num_retries=1,
    allowed_fails=2,     # cool down primary deployment after 2 consecutive errors/429s
    cooldown_time=60,    # route straight to backup for 60s before probing primary again
    set_verbose=False,
)


def call_router_json(prompt: str, step_name: str, max_tokens: int = 300) -> tuple[dict, dict]:
    """Lightweight JSON call strictly for routing and verification flags."""
    t0 = time.perf_counter()
    resp = LLM_ROUTER.completion(
        model="legal-primary",
        temperature=0,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}],
    )
    latency_ms = round((time.perf_counter() - t0) * 1000, 1)
    served_by = getattr(resp, "model", "unknown")
    tokens = getattr(getattr(resp, "usage", None), "total_tokens", 0) or 0

    raw = re.sub(r"<think>.*?</think>", "", resp.choices[0].message.content or "{}", flags=re.S).strip()
    match = re.search(r"\{.*\}", raw, flags=re.S)
    try:
        parsed = json.loads(match.group(0) if match else raw)
    except json.JSONDecodeError:
        parsed = {}

    telemetry = {
        "step": step_name,
        "served_by": served_by,
        "latency_ms": latency_ms,
        "tokens": tokens,
    }
    return parsed, telemetry


def call_router_text(prompt: str, step_name: str, max_tokens: int = 1200) -> tuple[str, dict]:
    """Plain-text synthesis call so legal answers never truncate inside JSON."""
    t0 = time.perf_counter()
    resp = LLM_ROUTER.completion(
        model="legal-primary",
        temperature=0,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    latency_ms = round((time.perf_counter() - t0) * 1000, 1)
    served_by = getattr(resp, "model", "unknown")
    tokens = getattr(getattr(resp, "usage", None), "total_tokens", 0) or 0

    text = re.sub(r"<think>.*?</think>", "", resp.choices[0].message.content or "", flags=re.S).strip()
    telemetry = {
        "step": step_name,
        "served_by": served_by,
        "latency_ms": latency_ms,
        "tokens": tokens,
    }
    return text, telemetry


# ── 2. Deterministic Corpus & In-Memory FTS5 Lexical Index ───────────────────

class LegalCorpusStore:
    def __init__(self, index_dir: Path = INDEX_DIR):
        self.merged_tree: list[dict] = json.loads(
            (index_dir / "merged_tree.json").read_text(encoding="utf-8")
        )
        manifest = json.loads((index_dir / "manifest.json").read_text(encoding="utf-8"))
        self.pages: dict[str, dict[str, str]] = {
            doc_key: json.loads((index_dir / Path(meta["pages_file"]).name).read_text(encoding="utf-8"))
            for doc_key, meta in manifest.items()
        }
        self.node_map: dict[str, dict] = {}
        self._index_nodes(self.merged_tree)
        self.fts_conn = self._build_fts5()

    def _index_nodes(self, nodes: list[dict]) -> None:
        for n in nodes:
            self.node_map[n["node_id"]] = n
            if n.get("nodes"):
                self._index_nodes(n["nodes"])

    def _build_fts5(self) -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE VIRTUAL TABLE pages_fts USING fts5(doc_key, page_num UNINDEXED, content);")
        rows = [
            (doc_key, str(p), text)
            for doc_key, doc_pages in self.pages.items()
            for p, text in doc_pages.items()
        ]
        conn.executemany("INSERT INTO pages_fts VALUES (?, ?, ?);", rows)
        conn.commit()
        return conn

    def build_clean_catalog(self) -> list[dict]:
        """Unwrap container nodes ('chapters') and skip 'Compare' so all real chapters are visible."""
        catalog = []
        for act in self.merged_tree:
            chapters = []
            for ch in act.get("nodes", []):
                title_low = ch.get("title", "").strip().lower()
                if title_low == "compare":
                    continue
                routable_nodes = ch.get("nodes", []) if title_low == "chapters" else [ch]
                for node in routable_nodes:
                    entry: dict[str, Any] = {"node_id": node["node_id"], "title": node["title"]}
                    if node.get("summary"):
                        entry["summary"] = node["summary"][:180]
                    elif node.get("nodes"):
                        entry["subtopics"] = [c["title"] for c in node["nodes"][:6]]
                    chapters.append(entry)
            catalog.append({"act": act["title"], "chapters": chapters})
        return catalog

    def lexical_search(
        self,
        query: str,
        preferred_docs: set[str] | None = None,
        top_k: int = 4,
    ) -> list[tuple[str, int]]:
        """BM25 + exact section-number lookup, restricted to real statutory body pages."""
        hits: list[tuple[str, int]] = []

        def is_valid(doc_key: str, p: int) -> bool:
            if p < STATUTE_START_PAGE.get(doc_key, 1):
                return False
            if preferred_docs and doc_key not in preferred_docs:
                return False
            return True

        # 1. Exact section/article header match (e.g., "103." or "38.")
        sec_nums = re.findall(r"\b(?:section|sec\.?|article|art\.?)\s*(\d+[A-Z]?)\b", query, flags=re.I)
        for num in dict.fromkeys(sec_nums):
            cur = self.fts_conn.execute(
                "SELECT doc_key, page_num FROM pages_fts WHERE content MATCH ? LIMIT 8;",
                (f'"{num}."',),
            )
            for doc_key, p in cur.fetchall():
                p_int = int(p)
                if is_valid(doc_key, p_int) and (doc_key, p_int) not in hits:
                    hits.append((doc_key, p_int))

        # 2. Keyword BM25 fallback
        stopwords = {
            "the", "and", "for", "under", "what", "how", "when", "with",
            "that", "from", "section", "sections", "act", "police", "legal",
        }
        tokens = [t for t in re.findall(r"[a-z0-9]{3,}", query.lower()) if t not in stopwords]
        if tokens:
            fts_query = " OR ".join(f'"{t}"' for t in dict.fromkeys(tokens[:10]))
            cur = self.fts_conn.execute(
                "SELECT doc_key, page_num FROM pages_fts WHERE pages_fts MATCH ? ORDER BY bm25(pages_fts) LIMIT 15;",
                (fts_query,),
            )
            for doc_key, p in cur.fetchall():
                p_int = int(p)
                if is_valid(doc_key, p_int) and (doc_key, p_int) not in hits:
                    hits.append((doc_key, p_int))
                if len(hits) >= top_k:
                    break

        return hits[:top_k]

    def zoom_to_leaf_nodes(self, branch_ids: list[str], query: str, max_leaves: int = 3) -> list[str]:
        """Deterministically drill routed chapters down to top matching leaf nodes (0 LLM calls)."""
        stopwords = {"the", "and", "for", "under", "what", "how", "when", "with", "that", "from"}
        q_tokens = {t for t in re.findall(r"[a-z0-9]{3,}", query.lower()) if t not in stopwords}

        def resolve(nid: str) -> list[str]:
            node = self.node_map.get(nid)
            if not node:
                return []
            children = node.get("nodes", [])
            if not children:
                return [nid]

            scored = []
            for c in children:
                haystack = " ".join([c.get("title", ""), c.get("summary", "")] + c.get("key_items", [])).lower()
                c_tokens = set(re.findall(r"[a-z0-9]{3,}", haystack))
                scored.append((len(q_tokens & c_tokens), c["node_id"]))
            scored.sort(key=lambda x: x[0], reverse=True)

            picked = [cid for score, cid in scored[:3] if score > 0] or [children[0]["node_id"]]
            out = []
            for cid in picked:
                out.extend(resolve(cid))
            return out

        leaves = []
        for bid in branch_ids:
            leaves.extend(resolve(bid))
        return list(dict.fromkeys(leaves))[:max_leaves]

    def fetch_balanced_pages(
        self,
        node_ids: list[str],
        extra_doc_pages: list[tuple[str, int]],
        expand_provisos: bool = True,
        max_total_pages: int = 8,
    ) -> tuple[str, list[dict]]:
        """Fetch unclipped leaf pages + reserved FTS5 slots, capped at 8 pages."""
        target_pages: list[tuple[str, int, str]] = []
        seen: set[tuple[str, int]] = set()
        tree_budget = max_total_pages - min(len(extra_doc_pages), 3)

        for nid in node_ids:
            node = self.node_map.get(nid)
            if not node:
                continue
            doc_key = nid.split("::")[0]
            s = int(node.get("start_index") or 1)
            raw_e = int(node.get("end_index") or s)
            e = raw_e if not node.get("nodes") else min(raw_e, s + 3)

            if expand_provisos:
                last_text = self.pages.get(doc_key, {}).get(str(e), "")
                if re.search(r"(Provided that|Explanation\.|Illustration)", last_text[-600:], re.I):
                    if str(e + 1) in self.pages.get(doc_key, {}):
                        e += 1

            for p in range(s, e + 1):
                if (doc_key, p) not in seen and len(target_pages) < tree_budget:
                    seen.add((doc_key, p))
                    target_pages.append((doc_key, p, f"tree:{nid}"))

        for doc_key, p in extra_doc_pages:
            if (doc_key, p) not in seen and len(target_pages) < max_total_pages:
                seen.add((doc_key, p))
                target_pages.append((doc_key, p, "fts5_lexical"))

        blocks, citations = [], []
        for doc_key, p, source_tag in target_pages:
            text = self.pages.get(doc_key, {}).get(str(p), "")
            if text:
                citations.append({"doc_key": doc_key, "page": p, "source": source_tag})
                blocks.append(f"=== [{doc_key} | Page {p} | via {source_tag}] ===\n{text}")

        return "\n\n".join(blocks), citations


# ── 3. LangGraph Cyclic State Machine with Ablation Support ──────────────────

AblationMode = Literal["pure_tree", "hybrid_vectorless", "agentic_cyclic"]


class LegalRAGState(TypedDict):
    query: str
    search_query: str
    ablation_mode: AblationMode
    cycle: int
    max_cycles: int
    selected_nodes: list[str]
    retrieved_context: str
    citations: list[dict]
    missing_gaps: list[str]
    grounded: bool
    final_answer: str
    trace: list[str]
    telemetry: list[dict]


def build_fast_vectorless_agent(store: LegalCorpusStore):
    catalog_json = json.dumps(store.build_clean_catalog(), ensure_ascii=False)

    def retrieve(state: LegalRAGState) -> dict:
        cycle = state["cycle"] + 1
        active_q = state["search_query"]
        mode = state["ablation_mode"]
        step_telemetry = list(state["telemetry"])

        if cycle == 1:
            route, t_route = call_router_json(
                "Select up to 3 chapter node_ids across the Indian statutes below that answer the query.\n"
                f'Return JSON: {{"node_ids": ["..."]}}\n\nQuery: {active_q}\n\nCatalog:\n{catalog_json}',
                step_name="cycle_1_route",
                max_tokens=200,
            )
            step_telemetry.append(t_route)
            branches = [n for n in route.get("node_ids", []) if n in store.node_map][:3]
            new_leaves = store.zoom_to_leaf_nodes(branches, active_q, max_leaves=3)
            route_info = f"{t_route['latency_ms']}ms via {t_route['served_by']}"
        else:
            # Cycle 2+: deterministic gap resolution across all Acts using missing section numbers (0 LLM calls)
            new_leaves = []
            route_info = "0ms (deterministic section lookup)"

        merged_nodes = list(dict.fromkeys(new_leaves + state["selected_nodes"]))
        preferred_docs = ({nid.split("::")[0] for nid in merged_nodes} or None) if cycle == 1 else None
        use_hybrid = mode in {"hybrid_vectorless", "agentic_cyclic"}
        fts_hits = store.lexical_search(active_q, preferred_docs=preferred_docs, top_k=4) if use_hybrid else []
        context, citations = store.fetch_balanced_pages(merged_nodes, fts_hits, expand_provisos=use_hybrid)

        msg = f"Cycle {cycle}: nodes={merged_nodes}, fts={fts_hits}, pages={len(citations)} ({route_info})"
        print(" •", msg)
        return {
            "cycle": cycle,
            "selected_nodes": merged_nodes,
            "retrieved_context": context,
            "citations": citations,
            "trace": state["trace"] + [msg],
            "telemetry": step_telemetry,
        }

    def verify_and_synthesise(state: LegalRAGState) -> dict:
        mode = state["ablation_mode"]
        step_telemetry = list(state["telemetry"])

        if not state["retrieved_context"].strip():
            return {
                "grounded": False,
                "final_answer": "INSUFFICIENT_STATUTORY_GROUNDING: No matching statutory text found in corpus.",
                "trace": state["trace"] + ["Verifier: fail-closed (empty context)"],
            }

        if mode == "agentic_cyclic":
            audit, t_ver = call_router_json(
                "Check if the retrieved statutory pages contain enough law to answer the query.\n"
                'Return JSON: {"grounded": true/false, "missing_references": ["Section X"], "followup_query": "Section X keywords"}\n\n'
                f"Query: {state['query']}\n\nRetrieved Pages:\n{state['retrieved_context']}",
                step_name=f"cycle_{state['cycle']}_verify",
                max_tokens=250,
            )
            step_telemetry.append(t_ver)
            grounded = bool(audit.get("grounded", True))
            missing = audit.get("missing_references", [])
            followup = audit.get("followup_query", "")

            if not grounded and state["cycle"] < state["max_cycles"] and (followup or missing):
                gap_q = f"{' '.join(missing)} {followup}".strip()
                msg = f"Verifier: gap {missing} -> retrying '{gap_q}' ({t_ver['latency_ms']}ms)"
                print(" •", msg)
                return {
                    "grounded": False,
                    "missing_gaps": missing,
                    "search_query": gap_q,
                    "trace": state["trace"] + [msg],
                    "telemetry": step_telemetry,
                }

            if not grounded:
                answer, t_syn = call_router_text(
                    "Write a concise fail-closed response starting with 'INSUFFICIENT_STATUTORY_GROUNDING', "
                    f"listing what is missing ({missing}) and summarizing only what is verified below:\n\n"
                    f"Query: {state['query']}\n\nRetrieved Pages:\n{state['retrieved_context']}",
                    step_name=f"cycle_{state['cycle']}_failclosed_synth",
                    max_tokens=1024,
                )
                step_telemetry.append(t_syn)
                return {
                    "grounded": False,
                    "missing_gaps": missing,
                    "final_answer": answer,
                    "trace": state["trace"] + [f"Verifier: fail-closed ({t_syn['latency_ms']}ms)"],
                    "telemetry": step_telemetry,
                }

        answer, t_syn = call_router_text(
            "You are an Indian legal reasoning system. Answer the query concisely and accurately using ONLY the "
            "verbatim statutory excerpts below. Cite exact Act names, Section/Article numbers, and Page numbers.\n\n"
            f"Query: {state['query']}\n\nRetrieved Verbatim Statutory Text:\n{state['retrieved_context']}",
            step_name=f"cycle_{state['cycle']}_synth",
            max_tokens=1200,
        )
        step_telemetry.append(t_syn)
        msg = f"Synthesis complete ({t_syn['latency_ms']}ms via {t_syn['served_by']})"
        print(" •", msg)
        return {
            "grounded": True,
            "missing_gaps": [],
            "final_answer": answer,
            "trace": state["trace"] + [msg],
            "telemetry": step_telemetry,
        }

    def route_after_verify(state: LegalRAGState) -> str:
        if (
            state["ablation_mode"] == "agentic_cyclic"
            and not state["grounded"]
            and state["cycle"] < state["max_cycles"]
            and state.get("missing_gaps")
        ):
            return "retrieve"
        return END

    graph = StateGraph(LegalRAGState)
    graph.add_node("retrieve", retrieve)
    graph.add_node("verify", verify_and_synthesise)
    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "verify")
    graph.add_conditional_edges("verify", route_after_verify, {"retrieve": "retrieve", END: END})
    return graph.compile()


def run_legal_query(
    agent,
    query: str,
    ablation_mode: AblationMode = "agentic_cyclic",
    max_cycles: int = 2,
) -> dict:
    return agent.invoke({
        "query": query,
        "search_query": query,
        "ablation_mode": ablation_mode,
        "cycle": 0,
        "max_cycles": max_cycles if ablation_mode == "agentic_cyclic" else 1,
        "selected_nodes": [],
        "retrieved_context": "",
        "citations": [],
        "missing_gaps": [],
        "grounded": False,
        "final_answer": "",
        "trace": [],
        "telemetry": [],
    })


if __name__ == "__main__":
    store = LegalCorpusStore()
    agent = build_fast_vectorless_agent(store)

    q = (
        "Under BNS 2023, what is the punishment for murder, and under what circumstances "
        "does the right of private defence of the body extend to causing death?"
    )
    out = run_legal_query(agent, q, ablation_mode="agentic_cyclic")
    print("\n=== FINAL ANSWER ===\n")
    print(out["final_answer"])