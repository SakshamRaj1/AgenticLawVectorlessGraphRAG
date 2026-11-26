

Run `build_fast_index.py`
Run all the .py files in tree audit folder to view them.
Run multi_doc_rag.py



#####

Index with Summary
Run `build_root_summary_index.py`

Combine trees using namespace
When you build your retrieval step later, any selected node_id maps directly back to its page file via doc_key = node_id.split("::")[0] → ./legal_index/{doc_key}_pages.json.

Build Index JSON file with Root-Node Summaries for better nodes selection through LLM reasoning.
Uses zero-LLM page_index_flash for structure extraction, then makes 1 LLM call per top-level node in tree["structure"] (child nodes are untouched).