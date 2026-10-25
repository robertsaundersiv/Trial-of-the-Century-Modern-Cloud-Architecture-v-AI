"""Summarize a legal document uploaded to the input bucket with Amazon Bedrock."""
import os
import urllib.parse

import boto3

s3 = boto3.client("s3")
bedrock = boto3.client("bedrock-runtime")

OUTPUT_BUCKET = os.environ["OUTPUT_BUCKET"]
MODEL_ID = os.environ.get("MODEL_ID", "amazon.nova-lite-v1:0")
MAX_INPUT_CHARS = int(os.environ.get("MAX_INPUT_CHARS", "50000"))
MAX_OUTPUT_TOKENS = int(os.environ.get("MAX_OUTPUT_TOKENS", "1024"))

SYSTEM_PROMPT = (
    "You are a paralegal at ObjectionInspection. Summarize the legal document "
    "for a busy attorney in plain English, under 400 words, using these headings: "
    "Document Type and Purpose; Parties; Key Terms and Obligations; Important "
    "Dates and Deadlines; Termination and Remedies; Risks or Unusual Clauses. "
    "Use only facts in the document. If a section does not apply, write 'None stated.'"
)


def summarize(text):
    response = bedrock.converse(
        modelId=MODEL_ID,
        system=[{"text": SYSTEM_PROMPT}],
        messages=[{
            "role": "user",
            "content": [{"text": f"<document>\n{text}\n</document>\n\nSummarize this document."}],
        }],
        inferenceConfig={"maxTokens": MAX_OUTPUT_TOKENS, "temperature": 0.2},
    )
    summary = response["output"]["message"]["content"][0]["text"]
    return summary, response["usage"]


def lambda_handler(event, context):
    results = []
    for record in event["Records"]:
        bucket = record["s3"]["bucket"]["name"]
        key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])

        body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        text = body.decode("utf-8", errors="replace")
        truncated = len(text) > MAX_INPUT_CHARS
        summary, usage = summarize(text[:MAX_INPUT_CHARS])

        output_key = "summaries/" + key.rsplit(".", 1)[0] + "-summary.txt"
        s3.put_object(
            Bucket=OUTPUT_BUCKET,
            Key=output_key,
            Body=summary.encode("utf-8"),
            ContentType="text/plain; charset=utf-8",
            Metadata={
                "source-bucket": bucket,
                "source-key": urllib.parse.quote(key),
                "model-id": MODEL_ID,
                "input-tokens": str(usage["inputTokens"]),
                "output-tokens": str(usage["outputTokens"]),
                "truncated": str(truncated).lower(),
            },
        )
        print(f"Summarized s3://{bucket}/{key} -> s3://{OUTPUT_BUCKET}/{output_key} "
              f"({usage['inputTokens']} in / {usage['outputTokens']} out tokens, truncated={truncated})")
        results.append({"source": key, "summary": output_key})
    return {"summaries": results}
