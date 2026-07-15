import argparse
import os

from darial_sdk import TaktClient


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-key", default=os.getenv("TAKT_API_KEY") or os.getenv("DARIAL_API_KEY"))
    parser.add_argument("--product-id", default=os.getenv("TAKT_PRODUCT_ID") or os.getenv("DARIAL_PRODUCT_ID"))
    parser.add_argument(
        "--agent-name",
        default="Legal Contract Agent",
    )
    parser.add_argument(
        "--base-url",
        default=(
            os.getenv("TAKT_BASE_URL")
            or os.getenv("DARIAL_BASE_URL", "http://localhost:8000")
        ),
    )
    args = parser.parse_args()

    if not args.api_key:
        raise SystemExit("Передай --api-key или TAKT_API_KEY")

    client = TaktClient(args.base_url, args.api_key, batch_size=10)

    with client.run(
        "contract_review",
        agent_name=args.agent_name,
        product_id=args.product_id,
    ) as run:
        run.record_tool_call(
            tool_name="s3_document_reader",
            latency_ms=180,
        )
        run.record_llm_call(
            model_name="qwen-72b-demo",
            provider="internal",
            input_tokens=4200,
            output_tokens=630,
            estimated_cost=1.71,
            latency_ms=6100,
        )
        run.record_outcome(
            outcome_type="contract_review_completed",
            success=True,
            quality_score=0.94,
            human_accepted=True,
            time_saved_minutes=24,
            estimated_business_value=850,
        )

    print("Demo telemetry отправлена")
    print("trace_id:", run.trace_id)


if __name__ == "__main__":
    main()
