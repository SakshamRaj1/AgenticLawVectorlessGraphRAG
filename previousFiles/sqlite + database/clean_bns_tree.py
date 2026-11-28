import json
import re
from pathlib import Path

RAW_TREE_PATH = Path("./legal_index/bnsAct2023_tree.json")
OUT_DIR = Path("./legal_index")

# Canonical fallback titles in case the PDF index merges or nests a chapter
BNS_CHAPTER_TITLES = {
    "I": "CHAPTER I - PRELIMINARY",
    "II": "CHAPTER II - OF PUNISHMENTS",
    "III": "CHAPTER III - GENERAL EXCEPTIONS",
    "IV": "CHAPTER IV - OF ABETMENT, CRIMINAL CONSPIRACY AND ATTEMPT",
    "V": "CHAPTER V - OF OFFENCES AGAINST WOMAN AND CHILD",
    "VI": "CHAPTER VI - OF OFFENCES AFFECTING THE HUMAN BODY",
    "VII": "CHAPTER VII - OF OFFENCES AGAINST THE STATE",
    "VIII": "CHAPTER VIII - OF OFFENCES RELATING TO THE ARMY, NAVY AND AIR FORCE",
    "IX": "CHAPTER IX - OF OFFENCES RELATING TO ELECTIONS",
    "X": "CHAPTER X - OF OFFENCES RELATING TO COIN, CURRENCY-NOTES, BANK-NOTES, AND GOVERNMENT STAMPS",
    "XI": "CHAPTER XI - OF OFFENCES AGAINST THE PUBLIC TRANQUILLITY",
    "XII": "CHAPTER XII - OF OFFENCES BY OR RELATING TO PUBLIC SERVANTS",
    "XIII": "CHAPTER XIII - OF CONTEMPTS OF THE LAWFUL AUTHORITY OF PUBLIC SERVANTS",
    "XIV": "CHAPTER XIV - OF FALSE EVIDENCE AND OFFENCES AGAINST PUBLIC JUSTICE",
    "XV": "CHAPTER XV - OF OFFENCES AFFECTING THE PUBLIC HEALTH, SAFETY, CONVENIENCE, DECENCY AND MORALS",
    "XVI": "CHAPTER XVI - OF OFFENCES RELATING TO RELIGION",
    "XVII": "CHAPTER XVII - OF OFFENCES AGAINST PROPERTY",
    "XVIII": "CHAPTER XVIII - OF OFFENCES RELATING TO DOCUMENTS AND TO PROPERTY MARKS",
    "XIX": "CHAPTER XIX - OF CRIMINAL INTIMIDATION, INSULT, ANNOYANCE, DEFAMATION, ETC.",
    "XX": "CHAPTER XX - REPEAL AND SAVING",
}

def extract_index_titles(node: dict, found: dict):
    """Recursively harvest 'CHAPTER <ROMAN> <DESCRIPTION>' titles from the index subtree."""
    for text in [node.get("title", "")] + node.get("key_items", []):
        for roman, desc in re.findall(r"CHAPTER\s+([IVX]+)\s+([^;]+)", text, flags=re.I):
            roman = roman.upper()
            desc = re.sub(r"\s+", " ", desc).strip(" -–—")
            if desc and roman not in found:
                found[roman] = f"CHAPTER {roman} - {desc}"
    for child in node.get("nodes", []):
        extract_index_titles(child, found)

def enrich_chapter_titles(nodes: list, title_map: dict):
    """Replace bare 'CHAPTER VI ' labels with descriptive titles."""
    for node in nodes:
        raw_title = node.get("title", "").strip()
        if raw_title.lower().startswith("short title"):
            node["title"] = title_map["I"]
            continue
        m = re.match(r"^CHAPTER\s+([IVX]+)\b(.*)$", raw_title, flags=re.I)
        if m:
            roman = m.group(1).upper()
            rest = m.group(2).strip(" -–—")
            if not rest and roman in title_map:
                node["title"] = title_map[roman]

data = json.loads(RAW_TREE_PATH.read_text(encoding="utf-8"))
top_nodes = {n["title"].strip().lower(): n for n in data.get("structure", [])}

# 1. Build merged title map (harvested from PDF index + canonical fallback)
title_map = dict(BNS_CHAPTER_TITLES)
if "index" in top_nodes:
    harvested = {}
    extract_index_titles(top_nodes["index"], harvested)
    title_map.update(harvested)

# 2. Clean & save verbatim statutory tree (pp. 74-237)
statute_nodes = top_nodes["chapters"]["nodes"]
enrich_chapter_titles(statute_nodes, title_map)
statute_tree = {
    "doc_id": "bns_2023",
    "doc_title": "The Bharatiya Nyaya Sanhita, 2023 (BNS)",
    "source_pdf": data["doc_name"],
    "structure": statute_nodes,
}
(OUT_DIR / "bns_statute_tree.json").write_text(
    json.dumps(statute_tree, indent=2, ensure_ascii=False), encoding="utf-8"
)

# 3. Clean & save IPC <-> BNS comparison tree (pp. 20-74)
compare_nodes = top_nodes["compare"]["nodes"]
enrich_chapter_titles(compare_nodes, title_map)
compare_tree = {
    "doc_id": "bns_ipc_compare",
    "doc_title": "BNS 2023 vs Repealed IPC 1860 — Corresponding Section Table",
    "source_pdf": data["doc_name"],
    "structure": compare_nodes,
}
(OUT_DIR / "bns_ipc_compare_tree.json").write_text(
    json.dumps(compare_tree, indent=2, ensure_ascii=False), encoding="utf-8"
)

print("Saved bns_statute_tree.json and bns_ipc_compare_tree.json\n")

# 4. Inspect nested children inside Chapter VI and Chapter XIX
for ch in statute_nodes:
    if ch["node_id"] in {"0148", "0304"}:
        children = ch.get("nodes", [])
        print(f"=== {ch['title']} [{ch['node_id']}] (pp. {ch['start_index']}-{ch['end_index']}, children={len(children)}) ===")
        for c in children[:8]:
            print(f"  └─ [{c['node_id']}] pp. {c['start_index']}-{c['end_index']} | {c['title']}")
        if len(children) > 8:
            print(f"  ... ({len(children) - 8} more nodes)")