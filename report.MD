## Vectorless RAG Implementation

### Index Creation [JSON]
Legal corpus ingested into JSON Index (vectorless implementation) [apx. 945 indexed pages]

| S.No. | Legal Corpus | Year | Pages | 
| --- | ------------------ | ---------- |  ----- | 
| 1. | CONSTITUTION OF INDIA |  10<sup>th</sup> September, 2026 | (402 pages) |
| 2. | BHARATIYA NYAYA SANHITA, (BNS) | 2003 | (237 pages) | 
| 3. | BHARATIYA NAGARIK SURAKSHA SANHITA, (BNSS) | 2003 | (249 pages) | 
| 4. | INFORMATION TECHNOLOGY ACT|  2000 |  (36 pages) | 
| 5. | DIGITAL PERSONAL DATA PROTECTION ACT, | 2023 | (21 pages) | 

- Total Legal documents = 5

#### Tool used for Index creation: 
- PageIndex Offline (inbuilt flash function) (without using inbuilt LLM)

- Earlier I tried to implement using Ollama with summary true for all the nodes (it was taking more than 8hrs and just completed around 3 docs). 
- So, I planned not to continue with that method.
- Rather, summary for the root and the next child node (not for all the nodes to save time) is sufficient
  - Only the root nodes and 1 child node will be generating the summary from LLM based on:
  - node title
- node information stores in page.json
- This select summary is generated using `groq/openai/gpt-oss-20b`
- Then merged the 5 trees into a single `merged_tree`

#### 
