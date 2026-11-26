## Vectorless RAG Implementation

### 5 Legal corpus ingested into JSON Index (vectorless implementation) [apx. 945 indexed pages]
| S.No. | Legal Corpus with year | Pages | 
| 1. | Constitution of India, 10th September, 2026 | (402 pages) | 
| 2. | BHARATIYA NYAYA SANHITA, 2023 (BNS) | (237 pages) | 
| 3. | BHARATIYA NAGARIK SURAKSHA SANHITA, 2023 (BNSS) | (249 pages) | 
| 4. | INFORMATION TECHNOLOGY ACT, 2000 | (36 pages) | 
| 5. | DIGITAL PERSONAL DATA PROTECTION ACT, 2023 | (21 pages) | 


#### Tool used: PageIndex Offline (without using LLM)
- Earlier I tried to implement using Ollama with summary true for all the nodes (it was taking more than 8hrs and just completed around 3 docs). 
- So, I planned not to continue with that method.
- Rather, only summary is for the root and the next child node (not for all the nodes to save time) is sufficient
- This select summary is generated using `groq/openai/gpt-oss-20b`



Then merged the 5 trees into a single `merged_tree`
