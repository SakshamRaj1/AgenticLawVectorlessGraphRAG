import json
from pathlib import Path
import fitz
import litellm
from dotenv import load_dotenv
from pageindex.flash import page_index_flash

load_dotenv()

MODEL = "ollama_chat/qwen2.5:3b"

def summarize_root(title: str, text: str) -> str:
    resp = litellm.completion(
        model=MODEL,
        temperature=0,
        max_tokens=90,
        num_retries=3,
        messages=[{
            "role": "user",
            "content": (
                f"Summarize this Indian legal document section ('{title}') in 1-2 concise sentences "
                f"highlighting key topics, offences, or rights covered:\n\n{text[:4000]}"
            ),
        }],
    )
    return resp.choices[0].message.content.strip()

def build_index(corpus_dir: str = "./corpus", out_dir: str = "./legal_index"):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    manifest = {}

    for pdf_path in sorted(Path(corpus_dir).glob("*.pdf")):
        print(f"[INDEXING] {pdf_path.name}")
        tree = page_index_flash(str(pdf_path), summary=False, optimize="merge")

        doc = fitz.open(pdf_path)
        pages = {str(i + 1): page.get_text("text") for i, page in enumerate(doc)}
        doc.close()

        # Summarize ONLY top-level root nodes in structure (skip children)
        for root in tree.get("structure", []):
            s = int(root.get("start_index") or 1)
            e = int(root.get("end_index") or s)
            snippet = "\n".join(pages.get(str(p), "") for p in range(s, e + 1))
            if snippet.strip():
                root["summary"] = summarize_root(root.get("title", ""), snippet)

        tree_file = out / f"{pdf_path.stem}_tree.json"
        pages_file = out / f"{pdf_path.stem}_pages.json"
        tree_file.write_text(json.dumps(tree, indent=2, ensure_ascii=False), encoding="utf-8")
        pages_file.write_text(json.dumps(pages, indent=2, ensure_ascii=False), encoding="utf-8")

        manifest[pdf_path.stem] = {
            "source_pdf": pdf_path.name,
            "page_count": len(pages),
            "tree_file": str(tree_file),
            "pages_file": str(pages_file),
        }
        print(f"[DONE] {pdf_path.name} ({len(tree.get('structure', []))} root nodes summarized)")

    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

if __name__ == "__main__":
    build_index()

# Too few summaries generated (around 3 to 5) which were mostly the content and later pages and not the specific acts.