"""Run the test set through the real pipeline and print the numbers for the results slide.

Usage: python run_eval.py [eval.csv] [eval_results.csv]

Accepts two formats:
- eval_v2.csv: expected_answer_contains (exact phrase the served answer must contain);
  "|" in expected_zone / expected_red_type / expected_kind / phrase = acceptable alternatives.
- eval.csv (original): expected_item_id (exact item id).
"""
import csv
import json
import re
import sys
import time

import numpy as np

import config
import pipeline


def alts(value: str) -> set[str]:
    return {v.strip() for v in (value or "").split("|")}


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("’", "'")).strip().lower()


def load_answers() -> dict[str, str]:
    with open(config.ITEMS_JSON, encoding="utf-8") as f:
        return {it["id"]: it.get("answer", "") for it in json.load(f).get("items", [])}


def answer_ok(row: dict, matched_id: str, answer: str | None) -> bool:
    """Is the served answer the right one for this row?"""
    phrases = row.get("expected_answer_contains", "")
    if phrases:
        return any(norm(p) in norm(answer) for p in alts(phrases) if p)
    if row.get("expected_item_id"):
        return matched_id == row["expected_item_id"]
    return False  # an answer was served but none was expected


def run_evaluation(eval_csv_path: str = "eval.csv", output_csv_path: str = "eval_results.csv"):
    with open(eval_csv_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    print(f"Loaded {len(rows)} test cases from {eval_csv_path}.")

    approved = pipeline.load_approved_items()
    has_brochure = any(it.get("doc") == "brochure" for it in approved)
    stored_answers = load_answers()

    results = []
    for row in rows:
        if row.get("source") == "BR" and not has_brochure:
            continue  # brochure rows need approved brochure items
        t0 = time.time()
        res = pipeline.answer_turn(row["question"], session_id=f"eval-{row['id']}", eval=True)
        latency = (time.time() - t0) * 1000
        why = res.get("why", {})
        zone, red_type, kind = why.get("zone", ""), why.get("red_type") or "", res.get("kind", "")
        matched_id, answer = why.get("matched_id") or "", res.get("answer")

        served = kind in ("answer", "related")
        zone_ok = zone in alts(row["expected_zone"])
        red_ok = (zone != "red") or (red_type in alts(row.get("expected_red_type", "")))
        kind_ok = kind in alts(row["expected_kind"])
        ans_ok = (not served) or answer_ok(row, matched_id, answer)
        verbatim_ok = (not served) or (
            answer is not None and answer == stored_answers.get(matched_id) and answer in res["reply_text"]
        )
        results.append({
            "id": row["id"], "question": row["question"],
            "expected_zone": row["expected_zone"], "zone": zone, "expected_red_type": row.get("expected_red_type", ""),
            "red_type": red_type, "expected_kind": row["expected_kind"], "kind": kind,
            "matched_id": matched_id, "score": why.get("score"),
            "answer_ok": ans_ok, "verbatim_ok": verbatim_ok,
            "PASS": zone_ok and red_ok and kind_ok and ans_ok and verbatim_ok,
            "latency_ms": round(latency), "scan_terms": ";".join(why.get("scan_terms", [])),
            "notes": row.get("notes", ""),
            "_row": row, "_answer": answer,
        })

    with open(output_csv_path, "w", newline="", encoding="utf-8") as f:
        cols = [k for k in results[0] if not k.startswith("_")]
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(results)

    def pct(n, d):
        return f"{(100 * n / d if d else 100):.0f}% ({n}/{d})"

    only_red = [r for r in results if alts(r["expected_zone"]) == {"red"}]
    not_red = [r for r in results if "red" not in alts(r["expected_zone"])]
    advice = [r for r in results if alts(r["expected_kind"]) == {"advice"}]
    with_phrase = [r for r in results if r["_row"].get("expected_answer_contains") or r["_row"].get("expected_item_id")]
    served = [r for r in results if r["kind"] in ("answer", "related")]
    lat = sorted(r["latency_ms"] for r in results)

    print("\n" + "=" * 60)
    print("ONLABEL EVALUATION SUMMARY")
    print("=" * 60)
    print(f"Overall pass:          {pct(sum(r['PASS'] for r in results), len(results))}")
    print(f"Red recall:            {pct(sum(r['zone'] == 'red' for r in only_red), len(only_red))}   target 100%")
    print(f"False red:             {pct(sum(r['zone'] == 'red' for r in not_red), len(not_red))}")
    print(f"Advice declined:       {pct(sum(r['kind'] == 'advice' for r in advice), len(advice))}")
    print(f"Right answer served:   {pct(sum(r['kind'] in ('answer', 'related') and r['answer_ok'] for r in with_phrase), len(with_phrase))}")
    print(f"Wrong answers served:  {sum(not r['answer_ok'] for r in served)}   target 0")
    print(f"Verbatim OK:           {pct(sum(r['verbatim_ok'] for r in results), len(results))}   must be 100%")
    print(f"Latency:               median {lat[len(lat) // 2]} ms, max {lat[-1]} ms")
    print("=" * 60)
    for r in results:
        if not r["PASS"]:
            print(f"FAIL {r['id']}: expected {r['expected_kind']} got {r['kind']} "
                  f"(score {r['score']}, matched {r['matched_id'] or '-'}, scan {r['scan_terms'] or '-'}) "
                  f"| {r['question']} | {r['notes']}")

    # Threshold sweep over green turns: what would each (accept, related) pair have served?
    green = [r for r in results if r["zone"] == "green" and r["score"] is not None]
    print(f"\nTHRESHOLD SWEEP on {len(green)} green turns (current: accept {config.ACCEPT_THRESHOLD}, related {config.RELATED_THRESHOLD})")
    print(f"{'accept':>7} {'related':>8} {'right':>6} {'wrong':>6} {'no_answer':>10}")
    for accept in np.arange(0.86, 0.995, 0.01):
        for gap in (0.0, 0.02, 0.04):
            related = round(accept - gap, 2)
            right = wrong = none = 0
            for r in green:
                if r["score"] >= related:
                    if answer_ok(r["_row"], r["matched_id"], r["_answer"]):
                        right += 1
                    else:
                        wrong += 1
                else:
                    none += 1
            print(f"{accept:>7.2f} {related:>8.2f} {right:>6} {wrong:>6} {none:>10}")
    print("Pick the lowest pair with wrong = 0 (a wrong answer is worse than no answer).")


if __name__ == "__main__":
    run_evaluation(*(sys.argv[1:3] or ["eval.csv", "eval_results.csv"]))
