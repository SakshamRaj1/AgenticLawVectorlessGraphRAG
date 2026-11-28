# SawLaw: Agent Oriented Pipeline for Indian Legal Knowledge Graph

- Current Notebook: `notebook\litellmexpertfastmain_V0.4`
  

- Built an agent-oriented robust vectorless pipeline over a hierarchical Indian Legal Knowledge JSON Tree, covering the Constitution and 4
statutes; (∼945 pages), using deterministic document-tree indexing to ensure zero-hallucination extraction with page-level citations in 3s.
- Architecting a Legal Knowlegde Graph wherein a dispute analyzer maps each case to the relevant provisions and domain-scoped web-search
agents retrieve judicial precedents; a cyclic state machine cross-synthesizes statutes with case law and re-runs incomplete lookups.
- Enforcing multi-hop reasoning on Legal Knowledge Graph to completely and accurately answer the query and autonomous feedback loop for
semantic query optimization, dynamically rewriting failed queries to ensure high-fidelity data continuity for downstream modeling.


