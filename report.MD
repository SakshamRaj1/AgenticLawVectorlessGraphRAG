## Vectorless RAG Implementation

### 5 Legal corpus ingested into JSON Index (vectorless implementation)
- Constitution of India (402 pages) 10th September, 2026
- BHARATIYA NYAYA SANHITA, 2023 (BNS) (237 pages)
- BHARATIYA NAGARIK SURAKSHA SANHITA, 2023 (BNSS) (249 pages)
- INFORMATION TECHNOLOGY ACT, 2000 (36 pages)
- DIGITAL PERSONAL DATA PROTECTION ACT, 2023 (21 pages)
-- (apx. 945 indexed pages)

#### Tool used: PageIndex Offline (without using LLM)
- Earlier I tried to implement using Ollama with summary true for all the nodes (it was taking more than 8hrs and just completed around 3 docs). 
- So, I planned not to continue with that method.
- Rather, only summary is for the root and the next child node (not for all the nodes to save time) is sufficient
- This select summary is generated using `groq/openai/gpt-oss-20b`



Then merged the 5 trees into a single `merged_tree`
