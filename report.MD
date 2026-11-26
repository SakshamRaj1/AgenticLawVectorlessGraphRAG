## Vectorless RAG Implementation

### Index Creation [JSON]
Legal corpus ingested into JSON Index (vectorless implementation) [apx. 945 indexed pages]

| S.No. | Legal Corpus | Year | Pages | 
| --- | --- | --- |  --- | 
| 1. | CONSTITUTION OF INDIA |  10<sup>th</sup> September, 2026 | (402 pages) |
| 2. | BHARATIYA NYAYA SANHITA, (BNS) | 2003 | (237 pages) | 
| 3. | BHARATIYA NAGARIK SURAKSHA SANHITA, (BNSS) | 2003 | (249 pages) | 
| 4. | INFORMATION TECHNOLOGY ACT|  2000 |  (36 pages) | 
| 5. | DIGITAL PERSONAL DATA PROTECTION ACT, | 2023 | (21 pages) | 

- Total Legal documents = 5


---


### Tool used for Index creation: 
- PageIndex Offline (inbuilt flash function) (without using inbuilt LLM)

- Earlier I tried to implement using Ollama with summary true for all the nodes (it was taking more than 8hrs and just completed around 3 docs). 
- So, I planned not to continue with that method.
- Rather, summary for the root and the next child node (not for all the nodes to save time) is sufficient
  - Only the root nodes and 1 child node will be generating the summary from LLM based on:
  - node title
- node information stores in page.json
- This select summary is generated using `groq/openai/gpt-oss-20b`
- Then merged the 5 trees into a single `merged_tree`


---


### Summary Generated for nodes in each document:

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
- Implementing namespace while merging the trees to solve lookup collisions
- Two-Stage Coarse-to-Fine Traversal (max_depth=1 → max_depth=3): Stage 1 exposes only top-level Chapters/Parts (~2,500–3,500 tokens) to pick up to 4 branches, and Stage 2 expands only those chosen subtrees (~500–1,200 tokens) to pick exact leaves.
- Corpus Hygiene (EXCLUDED_CONTAINERS & MIN_BODY_PAGE): Stripping homepage, index, arrangement of sections, BNSS Form No. schedules, removes non-substantive nodes before any LLM sees the tree.


---


### Retrieval Engine & Expert Guidance

* **LLM Used for Retrieval & Synthesis:** `gemini-3.5-flash-lite` (`temperature=0`, `response_mime_type="application/json"` for routing)
* **Baseline `vectorless_rag` Limitation:** Unguided tree traversal relies purely on surface keywords in the query, causing semantic misrouting (e.g., routing a train theft FIR-refusal query to **BNSS Chapter XIV § 203** trial jurisdiction instead of **BNSS Chapter XIII § 173(1)** Zero FIR).
* **Unified Domain Routing (`MASTER_EXPERT_RULES`):**
* Combines statute-specific routing rules for all 5 Acts (`INDIAN_CONSTITUTION_EXPERT_RULES`, `BNS_EXPERT_RULES`, `BNSS_EXPERT_RULES`, `DPDP_EXPERT_RULES`, `IT_ACT_EXPERT_RULES`) with `SHARED_LEGAL_INTERPRETATION_RULES`.
* Eliminates manual per-query statute selection and forces multi-issue query decomposition (e.g., mapping social media takedown noncompliance across **IT Act §§ 79, 69A** and **BNS § 356** simultaneously).



---

### Latency & Accuracy Optimizations (2-LLM-Call Pipeline)

Initial two-stage expert routing (`Stage 1 Chapters` → `Stage 2 Leaves` → `Answer Generation`) took **~10s** per query due to 3 sequential LLM calls, verbose reasoning strings, and redundant parent chapter retrieval. The optimized `expert_rag` reduces execution to **2 LLM calls total** without auxiliary wrapper functions:

* **Single-Call Routing + Deterministic Leaf Resolution (LLM Call 1):**
* `llm_tree_search_with_expert` makes one compact JSON call (`{"sections": [...], "node_list": [...]}`) to extract exact `Act + Section/Article` citations alongside top-level `node_id`s.
* Matched section/article numbers are resolved in memory (`0 ms`) directly against `PAGES_STORE` and `merged_tree` to pinpoint the deepest leaf/chapter `node_id`, removing the Stage-2 LLM call.


* **Ancestor Node Pruning:** Automatically drops broad parent chapter `node_id`s whenever a child leaf `node_id` within the same branch is selected, preventing multi-page chapter bloat in the synthesis prompt.
* **Out-of-Scope Short-Circuiting:** Non-legal queries or greetings return `{"sections": [], "node_list": []}` on Call 1 and exit immediately without invoking `generate_answer` (**1 LLM call total**).

---

### Section-Aware Page Hydration (`find_nodes_by_ids`)

* **In-Memory Page Store (`PAGES_STORE`):** Preloads all five `*_pages.json` files at startup via `manifest.json` for zero-disk-I/O page lookup.
* **Front-Matter & TOC Guard (`MIN_BODY_PAGE`):**
* Clamps page scans to actual statutory body start pages (`constitutionOfIndia1950: 32`, `bnsAct2023: 21`, `bnssAct2023: 21`, `itAct2020: 5`, `dpdpAct2023: 2`) and strips bare `p.X` TOC nodes.
* Prevents section-number regexes from matching *Arrangement of Sections* / index entries instead of substantive provisions.


* **Targeted Slicing & Boundary Guard:**
* Locates the exact page(s) where target section/article headers appear within a chapter's `start_index..end_index` span (`[p, p+1]`).
* Extends slicing by `+1` page whenever `Provided that`, `Explanation.`, or `Illustration` appears near the end of the final retrieved page so statutory exceptions are never truncated.



---

### Grounded Answer Synthesis (`generate_answer`)

* **Closed-World Grounding (LLM Call 2):** Generates answers strictly from hydrated statutory excerpts (`[Section: '<Act> — <Title>' | Page <X>]`) at `temperature=0`.
* **Mandatory Inline Citations:** Every legal claim is cited inline with `(Act, Section/Article, Page)`.
* **Fail-Closed Behavior:** Explicitly reports insufficient statutory context when a queried provision is absent from the retrieved excerpts or outside the 5-Act corpus.

---

### Pipeline Evolution Summary

| Pipeline Version | LLM Calls / Query | Routing Mechanism | Key Characteristics |
| --- | --- | --- | --- |
| **Baseline `vectorless_rag`** | 2–3 | Unguided tree traversal | Prone to keyword distraction across overlapping statutes |
| **Two-Stage `expert_rag`** | 3 | `MASTER_EXPERT_RULES` + Stage 1/2 LLM drill-down | High accuracy, ~10s latency, redundant parent chapter context |
| **Optimized `expert_rag`** | **2** (1 on non-legal) | Single-pass expert routing + deterministic `PAGES_STORE` leaf resolution | Ancestor pruning, TOC/proviso guards, minimal latency |






