import json
import time
from pathlib import Path
import fitz
import pymupdf
from pageindex.flash import page_index_flash


def build_fast_legal_index(corpus_dir: str = "./corpus", output_dir: str = "./legal_index",):
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    manifest = {}

    for pdf_path in sorted(Path(corpus_dir).glob("*.pdf")):
        t0 = time.perf_counter()
        print(f"[INDEXING] {pdf_path.name} (zero-LLM Flash mode) ...")

        # Pure deterministic layout/bookmark tree - zero LLM calls
        tree = page_index_flash(
            str(pdf_path),
            summary=False,
            optimize="merge",  # use optimize=False if raw unmerged nodes is needed
        )

        # Save hierarchical tree JSON
        tree_file = out / f"{pdf_path.stem}_tree.json"
        tree_file.write_text(json.dumps(tree, indent=2, ensure_ascii=False), encoding="utf-8")

        # Extract & cache 1-indexed verbatim pages once for <5ms retrieval in LangGraph
        doc = fitz.open(pdf_path)
        pages = {str(i + 1): page.get_text("text") for i, page in enumerate(doc)}
        doc.close()

        pages_file = out / f"{pdf_path.stem}_pages.json"
        pages_file.write_text(json.dumps(pages, indent=2, ensure_ascii=False), encoding="utf-8")

        manifest[pdf_path.stem] = {
            "source_pdf": pdf_path.name,
            "page_count": len(pages),
            "tree_file": str(tree_file),
            "pages_file": str(pages_file),
        }
        print(f"[DONE] {pdf_path.name} ({len(pages)} pages) in {time.perf_counter() - t0:.2f}s")

    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nAll statutes indexed. Manifest saved to {out / 'manifest.json'}")


if __name__ == "__main__":
    build_fast_legal_index()