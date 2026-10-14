import json
import numpy as np
import pymupdf
from google import genai
from google.genai import types
import config


def get_embedding(client, text: str) -> np.ndarray:
    resp = client.models.embed_content(
        model=config.MODEL_EMBED,
        contents=text,
        config=types.EmbedContentConfig(task_type="SEMANTIC_SIMILARITY"),
    )
    if hasattr(resp, "embeddings") and resp.embeddings:
        vec = resp.embeddings[0].values
    elif hasattr(resp, "embedding") and resp.embedding:
        vec = resp.embedding.values
    else:
        raise ValueError("No embeddings returned")
    v = np.array(vec, dtype=np.float32)
    norm = np.linalg.norm(v)
    return v / norm if norm > 0 else v


def cosine_sim(v1: np.ndarray, v2: np.ndarray) -> float:
    return float(np.dot(v1, v2))


def main():
    print(f"Connecting to Vertex AI (Project: {config.PROJECT_ID}, Location: {config.LOCATION})...")
    client = genai.Client(vertexai=True, project=config.PROJECT_ID, location=config.LOCATION)

    all_passed = True

    # (a) MODEL_FLASH returns {"ok": true} as JSON
    print("\n--- Check (a): MODEL_FLASH JSON response ---")
    try:
        resp = client.models.generate_content(
            model=config.MODEL_FLASH,
            contents='Return a JSON object: {"ok": true}',
            config=types.GenerateContentConfig(
                temperature=0,
                response_mime_type="application/json",
            ),
        )
        parsed = json.loads(resp.text)
        if parsed.get("ok") is True:
            print(f"PASS: MODEL_FLASH returned valid JSON: {parsed}")
        else:
            print(f"FAIL: Expected {{'ok': true}}, got: {parsed}")
            all_passed = False
    except Exception as e:
        print(f"FAIL: Error during MODEL_FLASH call: {e}")
        all_passed = False

    # (b) Embed two similar sentences and one unrelated one, print cosine scores
    print("\n--- Check (b): Embeddings similarity comparison ---")
    try:
        s1 = "How should I store my KESIMPTA pen?"
        s2 = "What temperature is required to store KESIMPTA in the refrigerator?"
        s3 = "What is the capital city of Australia?"

        v1 = get_embedding(client, s1)
        v2 = get_embedding(client, s2)
        v3 = get_embedding(client, s3)

        sim_similar = cosine_sim(v1, v2)
        sim_unrelated = cosine_sim(v1, v3)

        print(f"Sentence 1: '{s1}'")
        print(f"Sentence 2: '{s2}'")
        print(f"Sentence 3: '{s3}'")
        print(f"Cosine sim (1, 2) [Similar]: {sim_similar:.4f}")
        print(f"Cosine sim (1, 3) [Unrelated]: {sim_unrelated:.4f}")

        if sim_similar > sim_unrelated and (sim_similar - sim_unrelated) >= 0.15:
            print(f"PASS: Similar pair ({sim_similar:.4f}) scored clearly higher than unrelated pair ({sim_unrelated:.4f})")
        else:
            print(f"FAIL: Unexpected scores: similar={sim_similar:.4f}, unrelated={sim_unrelated:.4f}")
            all_passed = False
    except Exception as e:
        print(f"FAIL: Error during embeddings test: {e}")
        all_passed = False

    # (c) Open data/medication_guide.pdf with pymupdf and print the page count
    print("\n--- Check (c): PyMuPDF PDF page count ---")
    try:
        doc = pymupdf.open(config.MEDICATION_GUIDE_PDF)
        page_count = len(doc)
        print(f"Opened {config.MEDICATION_GUIDE_PDF}: page count = {page_count}")
        if page_count == 4:
            print(f"PASS: Medication Guide page count is {page_count}")
        else:
            print(f"FAIL: Expected 4 pages, got {page_count}")
            all_passed = False
    except Exception as e:
        print(f"FAIL: Error reading PDF: {e}")
        all_passed = False

    print("\n" + "=" * 40)
    if all_passed:
        print("OVERALL SMOKE TEST RESULT: ALL CHECKS PASSED")
    else:
        print("OVERALL SMOKE TEST RESULT: CHECKS FAILED")
    print("=" * 40)


if __name__ == "__main__":
    main()
