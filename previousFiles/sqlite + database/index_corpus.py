import json
import os
from pathlib import Path
from dotenv import load_dotenv
from pageindex import PageIndexClient

load_dotenv()
os.environ.setdefault("OLLAMA_API_BASE", "http://localhost:11434")

# Local Ollama for indexing ONLY; zero API calls, zero rate limits
client = PageIndexClient(
    index={
        "model": "ollama_chat/llama3.2:3b",
        # "model": "ollama_chat/qwen2.5:1.5b",
        "storage_path": "./legal_index",
        "optimize": "merge",                # deterministic merge pass (fewer local LLM calls)
        "summary_concurrency": 1,           # prevents Ollama queue timeouts on CPU/laptop GPU
        "summary_max_words": 60,
    }
)

def index_legal_corpus(corpus_dir: str = "./corpus"):
    manifest_dir = Path("./legal_index")
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / "manifest.json"

    response = client.list_documents()
    docs = response.get("documents", []) if isinstance(response, dict) else response
    existing = {
        d.get("name"): d.get("doc_id")
        for d in docs
        if isinstance(d, dict)
    }

    registry = (
        json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.exists()
        else {}
    )

    for pdf_path in sorted(Path(corpus_dir).glob("*.pdf")):
        if pdf_path.name in existing:
            print(f"[SKIP] Already indexed: {pdf_path.name}")
            registry[pdf_path.stem] = existing[pdf_path.name]
            manifest_path.write_text(json.dumps(registry, indent=2), encoding="utf-8")
            continue

        print(f"[INDEXING] {pdf_path.name} (local Ollama) ...")
        result = client.submit_document(str(pdf_path))
        doc_id = result["doc_id"]
        registry[pdf_path.stem] = doc_id

        # Save after every document so progress is never lost
        manifest_path.write_text(json.dumps(registry, indent=2), encoding="utf-8")
        print(f"[DONE] {pdf_path.name} -> {doc_id}")

    print("\nSaved manifest to ./legal_index/manifest.json")

if __name__ == "__main__":
    index_legal_corpus()