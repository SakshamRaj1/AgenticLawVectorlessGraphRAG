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

### Summary Generated for nodes in each document:

- bnsAct2023: 20 targets 
- bnssAct2023: 26 targets 
- constitutionOfIndia1950: 43 targets 
- dpdpAct2023: 9 targets 
- itAct2020: 12 targets

### Tree Combining

Combining all five of the indexed Acts (bnsAct2023, bnssAct2023, constitutionOfIndia1950, dpdpAct2023, and itAct2020) required solving two issues:   
- node_id collisions: Every *_tree.json starts at "0000". Merging them without namespacing (doc_key::node_id, e.g., bnsAct2023::0148) causes cross-Act lookup collisions.
- Token overflow: Passing all five complete trees into one LLM call blows past free-tier context/TPM limits. 

The solution:
- Implementing namespace while merging the trees to solve lookup collisions
- Two-Stage Coarse-to-Fine Traversal (max_depth=1 → max_depth=3): Stage 1 exposes only top-level Chapters/Parts (~2,500–3,500 tokens) to pick up to 4 branches, and Stage 2 expands only those chosen subtrees (~500–1,200 tokens) to pick exact leaves.
- Corpus Hygiene (EXCLUDED_CONTAINERS & MIN_BODY_PAGE): Stripping homepage, index, arrangement of sections, BNSS Form No. schedules, removes non-substantive nodes before any LLM sees the tree.









