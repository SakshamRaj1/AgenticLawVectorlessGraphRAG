# Merge all the index json files 

import json
from pathlib import Path
import re
from pyFiles.get_summary_targets import should_skip

def prefix_ids(nodes: list, doc_key: str) -> list:
    out = []
    for node in nodes:
        if should_skip(node, doc_key):
            continue
        node["node_id"] = f"{doc_key}::{node['node_id']}"
        if node.get("nodes"):
            node["nodes"] = prefix_ids(node["nodes"], doc_key)
        out.append(node)
    return out

CONSTITUTION_BODY_START = 32       # actual start

SKIP_KEYWORDS = ("homepage", "index", "table of contents", "contents", "preface", "abbreviations")
MIN_BODY_PAGE = {"constitutionOfIndia1950": CONSTITUTION_BODY_START}

def should_skip(node: dict, doc_key: str) -> bool:
    title = node.get("title", "").strip().lower()
    start_p = int(node.get("start_index") or 1)
    if any(k in title for k in SKIP_KEYWORDS):
        return True
    if re.match(r"^form\s+no\.?", title):  # Skip BNSS Second Schedule forms
        return True
    return start_p < MIN_BODY_PAGE.get(doc_key, 1)


def merge_trees(index_dir: str = "./legal_index"):
    base = Path(index_dir)
    manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
    merged = []

    for doc_key, meta in manifest.items():
        tree = json.loads(Path(meta["tree_file"]).read_text(encoding="utf-8"))
        merged.append({
            "node_id": f"{doc_key}::ROOT",
            "title": tree.get("doc_title") or doc_key,
            "start_index": 1,
            "end_index": meta["page_count"],
            "nodes": prefix_ids(tree.get("structure", []), doc_key),
        })

    out_path = base / "merged_tree.json"
    out_path.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Merged {len(merged)} Acts -> {out_path}")

if __name__ == "__main__":
    merge_trees()