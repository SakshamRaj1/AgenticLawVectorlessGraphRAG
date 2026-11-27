## Expert guided Vectorless RAG Implementation

### Index Creation [JSON]
Legal corpus ingested into JSON Index (vectorless implementation) [apx. 945 indexed pages]

| S.No. | Legal Corpus | Year | Pages | 
| --- | --- | --- |  --- | 
| 1. | CONSTITUTION OF INDIA |  10<sup>th</sup> September, 2026 | (402 pages) |
| 2. | BHARATIYA NYAYA SANHITA, (BNS) | 2023 | (237 pages) | 
| 3. | BHARATIYA NAGARIK SURAKSHA SANHITA, (BNSS) | 2023 | (249 pages) | 
| 4. | INFORMATION TECHNOLOGY ACT|  2000 |  (36 pages) | 
| 5. | DIGITAL PERSONAL DATA PROTECTION ACT, | 2023 | (21 pages) | 

- Total Legal documents = 5


---


### Tool used for Index creation: 
- PageIndex Offline: `page_index_flash(pdf, summary=False, optimize="merge")` from `pageindex.flash` (without using inbuilt LLM)
  - Builds the hierarchical tree purely from the PDF layout and bookmarks in seconds: zero LLM calls, zero API rate limits.
- For every PDF the indexer writes:
  - `<doc>_tree.json` - hierarchical tree
  - `<doc>_pages.json` - verbatim, 1-indexed page text extracted with PyMuPDF (`page.get_text("text")`)
  - one shared `manifest.json` - source PDF, `page_count`, `tree_file`, `pages_file` for every document

- Earlier I tried to implement using Ollama with summary true for all the nodes (it was taking more than 8hrs and just completed around 3 docs). 
- So, I planned not to continue with that method.
- Rather, summary for the root and the next child node (not for all the nodes to save time) is sufficient


---


### Summary Generation (select nodes only)

**Which nodes get a summary**
- Top-level nodes of each tree.
- If a top-level node has children, spans more than 40 pages and is not titled "compare", its (non-skipped) child nodes are summarized instead of the outer wrapper (e.g. BNS "chapters" pp. 74-237 → its individual chapters).
- Skipped: titles containing homepage / index / table of contents / contents / preface / abbreviations, BNSS "Form No." schedule forms, and Constitution nodes that start before the body page (32).

**How the summary is generated**
- Input: the node's sub-section titles and `key_items` (max 1,200 chars) + the opening text of the node from `*_pages.json`, truncated to 2,500 chars - so long chapters are not summarized from their first pages alone.
- Output: a concise 1-2 sentence plain-text summary.
- Model: `groq/openai/gpt-oss-20b` called through LiteLLM (`litellm.completion`, `temperature=0`, `max_tokens=512`, `reasoning_effort="low"`, `num_retries=5`) with a 6.5 s pause between calls to respect the Groq free tier (30 RPM, 8K TPM, 1K RPD).
- `DRY_RUN=True` first prints the number of targets; generation is resumable - empty or unfinished summaries (not ending with ".") are regenerated, finished ones are kept.
- After merging, `rollup_summaries` gives parent nodes without their own summary a roll-up: "Covers <first 6 child titles>." + the first two child summaries.

**Summary targets per document (all pending at generation time)**

- bnsAct2023: 20 targets 
- bnssAct2023: 26 targets 
- constitutionOfIndia1950: 43 targets 
- dpdpAct2023: 9 targets 
- itAct2020: 12 targets


---


### Tree Combining

Combining all five of the indexed Acts (bnsAct2023, bnssAct2023, constitutionOfIndia1950, dpdpAct2023, and itAct2020) required solving two issues:   
- node_id collisions: Every *_tree.json starts at "0000". Merging them without namespacing (doc_key::node_id, e.g., bnsAct2023::0148) causes cross-Act lookup collisions.
- Token overflow: Passing all five complete trees into one LLM call blows past free-tier context/TPM limits. 

The solution:
- Implementing namespace while merging the trees (`doc_key::node_id`) under one `<doc_key>::ROOT` node per Act, saved as a single `merged_tree.json` (489 nodes in total, including the 5 Act roots).
- Compressed tree view (`compress`): the router sees only two levels (top-level nodes + their direct children), each with `node_id`, title, page range and its summary (or up to 10 `key_items` when no summary exists). Wrapper nodes ("Chapters", the Act/Constitution title nodes) are flattened away.
- Corpus Hygiene (EXCLUDED_CONTAINERS & MIN_BODY_PAGE): Stripping homepage, index, compare, arrangement of sections, BNSS Form No. schedules and bare `p.X` page nodes, plus all nodes before each Act's body start page, removes non-substantive nodes before any LLM sees the tree.
- (An earlier two-stage coarse-to-fine traversal, `max_depth=1 → max_depth=3`, was replaced by the single-call routing described below.)


---


### LLM Access Layer (LiteLLM Router)

All LLM calls in the retrieval pipeline go through one LiteLLM `Router`; `llm_tree_search_with_expert` and `generate_answer` call `router.completion(...)` directly. The Gemini SDK (`google-genai`) is no longer used.

| Router alias | Used by | Primary | Fallback chain (in order) |
| --- | --- | --- | --- |
| `tree-search` | Step 1 - expert routing (LLM Call 1) | `gemini/gemini-3.5-flash-lite` (timeout 5 s) | `tree-search-fb1`: `openrouter/nvidia/nemotron-3-ultra-550b-a55b:free` (timeout 8 s, `reasoning_effort="low"`) |
| `answer` | Step 3 - answer synthesis (LLM Call 2) | `gemini/gemini-3.5-flash-lite` (timeout 4 s) | `answer-fb1`: `groq/openai/gpt-oss-20b` (timeout 4 s, `reasoning_effort="low"`) → `answer-fb2`: OpenRouter Nemotron (timeout 8 s, `reasoning_effort="low"`) |

- The function default `model="tree-search"` / `model="answer"` is a router alias, not a provider model name - providers can be swapped in `model_list` without touching the functions.
- Groq is deliberately **not** in the `tree-search` chain: the routing prompt (expert rules + compressed tree, ~20K+ tokens) is too large for Groq's free tier (8K TPM).
- Router settings: `num_retries=0` (fail over to the next model instead of retrying the same provider), `allowed_fails=1`, `cooldown_time=30` (a deployment that keeps failing is put on a 30 s cooldown so later queries do not wait for its timeout again).
- Every deployment: `max_tokens=2048`; every call: `temperature=0`; routing call additionally uses JSON mode (`response_format={"type": "json_object"}`).
- `litellm.drop_params=True` drops parameters a provider does not support (e.g. `response_format`) instead of raising an error.
- `<think>...</think>` tags that some fallback models emit are stripped from both the routing and the answer output.
- API keys are read from `.env`: `GOOGLE_API_KEY` (Gemini), `GROQ_API_KEY`, `OPENROUTER_API_KEY`.
- The last notebook cell times the full pipeline on the normal path and forces a Gemini failure (`mock_testing_fallbacks=True`) on each chain to show which fallback answers and how long it takes.


---


### Retrieval Engine & Expert Guidance

* **LLM Used for Retrieval & Synthesis:** LiteLLM Router (see above) - Gemini `gemini-3.5-flash-lite` as primary with OpenRouter / Groq fallbacks; `temperature=0`, JSON mode for routing.
* **Baseline `vectorless_rag` Limitation (earlier experiments, not part of this notebook):** Unguided tree traversal relies purely on surface keywords in the query, causing semantic misrouting (e.g., routing a train theft FIR-refusal query to **BNSS Chapter XIV § 203** trial jurisdiction instead of **BNSS Chapter XIII § 173(1)** Zero FIR).
* **Unified Domain Routing (`MASTER_EXPERT_RULES`):**
* Combines statute-specific routing rules for all 5 Acts (`INDIAN_CONSTITUTION_EXPERT_RULES`, `BNS_EXPERT_RULES`, `BNSS_EXPERT_RULES`, `DPDP_EXPERT_RULES`, `IT_ACT_EXPERT_RULES`) with `SHARED_LEGAL_INTERPRETATION_RULES`.
* Eliminates manual per-query statute selection; the prompt asks the model to break the query into ALL distinct legal issues and map each to exact Act + Section/Article numbers (e.g., the social-media takedown-noncompliance sample query is mapped to **IT Act §§ 79 and 69A** in a single call).
* Non-legal queries and greetings are returned as an empty result (see short-circuiting below).



---

### Latency & Accuracy Optimizations (2-LLM-Call Pipeline)

Initial two-stage expert routing (`Stage 1 Chapters` → `Stage 2 Leaves` → `Answer Generation`) took **~10s** per query due to 3 sequential LLM calls, verbose reasoning strings, and redundant parent chapter retrieval. The optimized `expert_rag` reduces execution to **2 LLM calls total** without auxiliary wrapper functions:

* **Single-Call Routing (LLM Call 1):**
* `llm_tree_search_with_expert` makes one compact JSON call (`{"sections": [...], "node_list": [...]}`) to extract exact `Act + Section/Article` citations alongside up to 5 Chapter/Part `node_id`s.
* Returned `node_id`s are validated against the set of IDs present in the compressed tree (hallucinated IDs are dropped); the extracted section strings are returned as `thinking` ("Matched provisions: ...") and reused as the hint for section-aware page selection in `find_nodes_by_ids`.

* **Deterministic Leaf Resolution & Ancestor Pruning (implemented in the same function):**
* Each section/article number is mapped to its Act (regex on the Act name), searched in `PAGES_STORE` (pages ≥ `MIN_BODY_PAGE`, section number at the start of a line), and resolved in memory to the deepest matching node (`find_deepest`) - no Stage-2 LLM call.
* Python-resolved nodes are merged ahead of the LLM nodes (max 5), and a broad parent `node_id` is dropped whenever a more specific child inside it is selected (`final_ids`), preventing multi-page chapter bloat in the synthesis prompt.
* > **Current behaviour (V0_2):** the function computes `final_ids` but its return statement still returns the validated LLM-selected `llm_ids`. Leaf resolution and ancestor pruning take effect downstream once the return value is switched to `final_ids`.

* **Out-of-Scope Short-Circuiting:** Non-legal queries or greetings return `{"sections": [], "node_list": []}` from the model; the function returns "No applicable Indian statutory provisions." with an empty `node_list`, `find_nodes_by_ids` returns nothing, and `generate_answer` immediately returns "⚠️ No relevant sections found in the document." without calling the LLM (**1 LLM call total**).

---

### Section-Aware Page Hydration (`find_nodes_by_ids`)

* **In-Memory Page Store (`PAGES_STORE`):** Preloads all five `*_pages.json` files at startup via `manifest.json` for zero-disk-I/O page lookup.
* **Front-Matter & TOC Guard (`MIN_BODY_PAGE`):**
* Clamps page scans to actual statutory body start pages (`constitutionOfIndia1950: 32`, `bnsAct2023: 21`, `bnssAct2023: 21`, `itAct2020: 5`, `dpdpAct2023: 2`) and strips bare `p.X` TOC nodes.
* Prevents section-number regexes from matching *Arrangement of Sections* / index entries instead of substantive provisions.


* **Targeted Slicing:**
* Used when section/article numbers were extracted from the hint and the node spans more than 5 pages: locates the page(s) where the target section/article header appears within the node's `start_index..end_index` span and keeps each hit page plus the next one (`[p, p+1]`), up to 6 pages.
* **Fallback + Boundary Guard:** If no header page is found, the first 6 pages of the node are used, extended by `+1` page when `Provided that`, `Explanation.`, or `Illustration` appears in the last 600 characters of the final page so statutory exceptions are not truncated.
* Each hydrated node carries the Act title prefix, its `page_index` range and verbatim page text marked `[Page N]`.



---

### Grounded Answer Synthesis (`generate_answer`)

* **Closed-World Grounding (LLM Call 2, router alias `answer`):** The prompt instructs the model to answer using ONLY the provided statutory excerpts (`[Section: '<Act> — <Title>' | Page <X>]`) at `temperature=0`, concisely and in at least 4 sentences.
* **Mandatory Inline Citations:** Every claim is cited inline with the Act, section/article number and page number in parentheses.
* **Fail-Closed Behavior:** When no node is retrieved, a fixed "⚠️ No relevant sections found in the document." message is returned without an LLM call; when excerpts are retrieved but do not contain the queried provision, the ONLY-the-context instruction leads the model to report that the provided text does not contain it (as seen in the notebook's sample runs).

---

### Pipeline Evolution Summary

| Pipeline Version | LLM Calls / Query | Routing Mechanism | Key Characteristics |
| --- | --- | --- | --- |
| **Baseline `vectorless_rag`** (earlier iteration) | 2–3 | Unguided tree traversal | Prone to keyword distraction across overlapping statutes |
| **Two-Stage `expert_rag`** (earlier iteration) | 3 | `MASTER_EXPERT_RULES` + Stage 1/2 LLM drill-down | High accuracy, ~10s latency, redundant parent chapter context |
| **Optimized `expert_rag` + LiteLLM Router** (current, V0_2) | **2** (1 on non-legal) | Single-pass expert routing (`tree-search` alias) + section-aware `PAGES_STORE` page hydration, answer via `answer` alias | Gemini primary with OpenRouter / Groq fallbacks, provider-agnostic functions, TOC/proviso guards, minimal latency |
