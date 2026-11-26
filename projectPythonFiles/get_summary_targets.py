# Count the total no. of summaries that will be generated before actually generating it. (to save time)
# To actually generate summaries for nodes
# For long sections, it was using only the few page from start, but that summary will be incomplete.
# tree nodes already contain all sub-section titles inside node["nodes"] and node["key_items"]. 
# Feeding those sub-headings plus the opening page text gives the LLM visibility across all 25 pages while staying well within Groq's 8,000 TPM limit


import json
import re
import time
from pathlib import Path
import litellm
from dotenv import load_dotenv

load_dotenv()

MODEL = "groq/openai/gpt-oss-20b"   # Free tier: 30 RPM, 8K TPM, 1K RPD
DRY_RUN = False                     # 1) Run True to check counts, 2) Set False to generate
CONSTITUTION_BODY_START = 32        # actual start

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

def get_summary_targets(structure: list, doc_key: str) -> list:
    targets = []
    for node in structure:
        if should_skip(node, doc_key):
            continue
        title = node.get("title", "").strip().lower()
        span = int(node.get("end_index") or 1) - int(node.get("start_index") or 1)
        if node.get("nodes") and span > 40 and title != "compare":
            targets.extend(c for c in node["nodes"] if not should_skip(c, doc_key))
        else:
            targets.append(node)
    return targets


litellm.drop_params = True

def summarize(title: str, text: str) -> str:
    resp = litellm.completion(
        model=MODEL,
        temperature=0,
        max_tokens=512,
        reasoning_effort="low",
        num_retries=5,
        messages=[{
            "role": "user",
            "content": (
                f"Write a concise 1-2 sentence plain-text summary of this Indian legal section ('{title}'), "
                f"listing key topics, offences, procedures, or rights:\n\n{text[:2500]}"
            ),
        }],
    )
    out = (resp.choices[0].message.content or "").strip()
    return re.sub(r"<think>.*?</think>", "", out, flags=re.S).strip()

def build_summary_context(node: dict, pages: dict, max_chars: int = 2500) -> str:
    # Collect immediate child titles / key_items so long chapters aren't blind to later sections
    subtopics = []
    for c in node.get("nodes", []):
        if c.get("title") and not c["title"].startswith("p."):
            subtopics.append(c["title"])
        subtopics.extend(k for k in c.get("key_items", []) if not k.startswith("p."))
    subtopics.extend(k for k in node.get("key_items", []) if not k.startswith("p."))

    header = f"Sub-sections in this chapter: {'; '.join(dict.fromkeys(subtopics))[:1200]}\n\n" if subtopics else ""

    s = int(node.get("start_index") or 1)
    e = int(node.get("end_index") or s)
    body = "\n".join(pages.get(str(p), "") for p in range(s, e + 1))
    return (header + body)[:max_chars]

def add_summaries(index_dir: str = "./legal_index"):
    base = Path(index_dir)
    manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))

    for doc_key, meta in manifest.items():
        tree_path = Path(meta["tree_file"])
        tree = json.loads(tree_path.read_text(encoding="utf-8"))
        pages = json.loads(Path(meta["pages_file"]).read_text(encoding="utf-8"))

        targets = get_summary_targets(tree.get("structure", []), doc_key)
        for n in targets:
            s = n.get("summary", "").strip()
            if not s or not s.endswith("."):
                n.pop("summary", None)

        pending = [n for n in targets if not n.get("summary")]
        print(f"{doc_key}: {len(targets)} targets ({len(pending)} remaining)")

        if DRY_RUN or not pending:
            continue

        for i, node in enumerate(pending, 1):
            s = int(node.get("start_index") or 1)
            e = int(node.get("end_index") or s)
            # snippet = "\n".join(pages.get(str(p), "") for p in range(s, e + 1))
            snippet = build_summary_context(node, pages) # every chapter summary will then cover all topics from its first page to its last page
            if snippet.strip():
                node["summary"] = summarize(node.get("title", ""), snippet)
                print(f"  [{i}/{len(pending)}] {node['node_id']}: {node['summary'][:80]}...")
                time.sleep(6.5)

        tree_path.write_text(json.dumps(tree, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  -> Saved {tree_path.name}")

if __name__ == "__main__":
    add_summaries()

# Output:

# bnsAct2023: 20 summary targets
# bnssAct2023: 84 summary targets
# constitutionOfIndia1950: 68 summary targets
# dpdpAct2023: 10 summary targets
# itAct2020: 13 summary targets

# bnsAct2023: 20 targets (20 remaining)
# bnssAct2023: 26 targets (26 remaining)
# constitutionOfIndia1950: 43 targets (43 remaining)
# dpdpAct2023: 9 targets (9 remaining)
# itAct2020: 12 targets (12 remaining)