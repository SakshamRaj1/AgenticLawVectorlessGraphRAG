import json
from pathlib import Path

tree_path = Path("./legal_index/itActAct2020_tree.json")
data = json.loads(tree_path.read_text(encoding="utf-8"))

print(f"Doc: {data.get('doc_name')} | Title: {data.get('doc_title')}\n")
print("=== TOP-LEVEL NODES ===")
for node in data.get("structure", []):
    children = node.get("nodes", [])
    print(
        f"[{node['node_id']}] pp. {node['start_index']}-{node['end_index']} "
        f"| children={len(children)} | {node['title']}"
    )
    # Preview first 3 children of each non-empty top-level section
    for child in children[:]:
        print(
            f"    └─ [{child['node_id']}] pp. {child['start_index']}-{child['end_index']} "
            f"| {child['title']}"
        )
        