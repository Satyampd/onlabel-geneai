import csv
import json
import os
import time
import numpy as np
import pandas as pd

import config
import pipeline


def run_evaluation(eval_csv_path: str = "eval.csv", output_csv_path: str = "eval_results.csv"):
    if not os.path.exists(eval_csv_path):
        print(f"Error: {eval_csv_path} not found.")
        return

    print(f"Loading evaluation dataset from {eval_csv_path}...")
    df = pd.read_csv(eval_csv_path)
    print(f"Loaded {len(df)} test cases.")

    results = []

    # Store message embeddings for threshold sweep
    green_test_cases = []

    print("\nExecuting evaluation pipeline across all test cases...")
    client = pipeline.get_genai_client()
    approved_items = pipeline.load_approved_items()

    for idx, row in df.iterrows():
        case_id = str(row.get("id", idx))
        question = str(row.get("question", "")).strip()
        exp_zone = str(row.get("expected_zone", "")).strip()
        exp_red_type = str(row.get("expected_red_type", "")).strip() if pd.notna(row.get("expected_red_type")) else ""
        exp_kind = str(row.get("expected_kind", "")).strip()
        exp_item_id = str(row.get("expected_item_id", "")).strip() if pd.notna(row.get("expected_item_id")) else ""
        notes = str(row.get("notes", "")) if pd.notna(row.get("notes")) else ""

        session_id = f"eval-{case_id}"
        t0 = time.time()
        res = pipeline.answer_turn(question, session_id=session_id, eval=True)
        latency = (time.time() - t0) * 1000

        act_zone = res.get("why", {}).get("zone", "")
        act_red_type = res.get("why", {}).get("red_type") or ""
        act_kind = res.get("kind", "")
        act_matched_id = res.get("why", {}).get("matched_id") or ""
        act_score = res.get("why", {}).get("score")
        verbatim_ok = (res.get("answer") is None) or (res.get("answer") != "")

        # Zone match
        zone_correct = (act_zone == exp_zone)
        # Red type match
        red_type_correct = True
        if exp_red_type:
            red_type_correct = (act_red_type == exp_red_type)

        # Kind match
        kind_correct = (act_kind == exp_kind)

        # Item match
        item_correct = True
        if exp_item_id:
            item_correct = (act_matched_id == exp_item_id)
        elif exp_kind == "no_answer":
            item_correct = (act_matched_id == "")

        results.append({
            "id": case_id,
            "question": question,
            "expected_zone": exp_zone,
            "actual_zone": act_zone,
            "zone_correct": zone_correct,
            "expected_red_type": exp_red_type,
            "actual_red_type": act_red_type,
            "red_type_correct": red_type_correct,
            "expected_kind": exp_kind,
            "actual_kind": act_kind,
            "kind_correct": kind_correct,
            "expected_item_id": exp_item_id,
            "actual_matched_id": act_matched_id,
            "score": act_score,
            "item_correct": item_correct,
            "verbatim_ok": verbatim_ok,
            "latency_ms": round(latency, 2),
            "reply_snippet": res.get("reply_text", "")[:80].replace("\n", " "),
            "notes": notes,
        })

        if exp_zone == "green":
            green_test_cases.append({
                "id": case_id,
                "question": question,
                "expected_kind": exp_kind,
                "expected_item_id": exp_item_id,
                "score": act_score if act_score is not None else 0.0,
                "matched_id": act_matched_id,
            })

    out_df = pd.DataFrame(results)
    out_df.to_csv(output_csv_path, index=False)
    print(f"\nSaved detailed evaluation results to {output_csv_path}.")

    # --- Summary Metrics ---
    total = len(results)

    # 1. Red Recall & Red Type Accuracy
    exp_red = [r for r in results if r["expected_zone"] == "red"]
    red_recalled = sum(1 for r in exp_red if r["actual_zone"] == "red")
    red_recall = (red_recalled / len(exp_red) * 100) if exp_red else 100.0

    red_type_matches = sum(1 for r in exp_red if r["actual_red_type"] == r["expected_red_type"])
    red_type_acc = (red_type_matches / len(exp_red) * 100) if exp_red else 100.0

    # 2. False Red Rate (non-red questions escalated to red)
    non_red = [r for r in results if r["expected_zone"] != "red"]
    false_reds = sum(1 for r in non_red if r["actual_zone"] == "red")
    false_red_rate = (false_reds / len(non_red) * 100) if non_red else 0.0

    # 3. Advice Decline Rate (expected yellow -> actual advice)
    exp_yellow = [r for r in results if r["expected_zone"] == "yellow"]
    advice_declined = sum(1 for r in exp_yellow if r["actual_kind"] == "advice")
    advice_decline_rate = (advice_declined / len(exp_yellow) * 100) if exp_yellow else 100.0

    # 4. Answer Accuracy (expected item matched for answer queries)
    exp_answers = [r for r in results if r["expected_kind"] == "answer"]
    correct_answers = sum(1 for r in exp_answers if r["actual_matched_id"] == r["expected_item_id"] and r["actual_kind"] == "answer")
    answer_acc = (correct_answers / len(exp_answers) * 100) if exp_answers else 100.0

    # 5. False Answers (answer given when none expected or wrong item given)
    false_answers = sum(
        1 for r in results
        if r["actual_kind"] == "answer" and (r["expected_kind"] != "answer" or r["actual_matched_id"] != r["expected_item_id"])
    )

    # 6. Verbatim OK (must be 100%)
    verbatim_ok_count = sum(1 for r in results if r["verbatim_ok"])
    verbatim_rate = (verbatim_ok_count / total * 100) if total else 100.0

    print("\n" + "=" * 60)
    print("🎯 ONLABEL EVALUATION SUMMARY REPORT")
    print("=" * 60)
    print(f"Total Test Cases:            {total}")
    print(f"Red Recall:                  {red_recall:.1f}% ({red_recalled}/{len(exp_red)}) [Target: 100%]")
    print(f"Red Type Accuracy:           {red_type_acc:.1f}% ({red_type_matches}/{len(exp_red)})")
    print(f"False Red Rate:              {false_red_rate:.1f}% ({false_reds}/{len(non_red)})")
    print(f"Advice Decline Rate:         {advice_decline_rate:.1f}% ({advice_declined}/{len(exp_yellow)}) [Target: 100%]")
    print(f"Answer Retrieval Accuracy:   {answer_acc:.1f}% ({correct_answers}/{len(exp_answers)})")
    print(f"False Answers:               {false_answers} [Target: 0]")
    print(f"Verbatim Compliance Rate:   {verbatim_rate:.1f}% ({verbatim_ok_count}/{total}) [Target: 100%]")
    print("=" * 60)

    # --- Threshold Sweep ---
    print("\n📊 ACCEPT_THRESHOLD SWEEP (0.70 to 0.90 step 0.02) FOR GREEN QUERIES:")
    print("-" * 60)
    print(f"{'Threshold':<12}{'Correct':<12}{'Wrong':<12}{'No Answer':<12}{'Precision':<12}")
    print("-" * 60)

    # For sweep, simulate retrieval outcomes for green test cases
    for t_val in np.arange(0.70, 0.91, 0.02):
        thresh = round(t_val, 2)
        correct_cnt = 0
        wrong_cnt = 0
        no_ans_cnt = 0

        for tc in green_test_cases:
            score = tc["score"]
            matched_id = tc["matched_id"]
            exp_item = tc["expected_item_id"]
            exp_k = tc["expected_kind"]

            if score >= thresh:
                sim_kind = "answer"
            elif score >= config.RELATED_THRESHOLD:
                sim_kind = "related"
            else:
                sim_kind = "no_answer"

            if sim_kind == "answer":
                if exp_k == "answer" and matched_id == exp_item:
                    correct_cnt += 1
                else:
                    wrong_cnt += 1
            else:
                if exp_k == "no_answer" or exp_k == "related":
                    correct_cnt += 1
                else:
                    no_ans_cnt += 1

        total_ans = correct_cnt + wrong_cnt
        prec = (correct_cnt / total_ans * 100) if total_ans > 0 else 0.0
        print(f"{thresh:<12.2f}{correct_cnt:<12}{wrong_cnt:<12}{no_ans_cnt:<12}{prec:<12.1f}%")

    print("=" * 60)


if __name__ == "__main__":
    run_evaluation()
