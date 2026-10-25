"""Unit tests for the summarizer handler, with S3 and Bedrock stubbed out (no AWS calls)."""
import io
import json
import os
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class FakeS3:
    def __init__(self, objects):
        self.objects = objects
        self.puts = []

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}

    def put_object(self, **kwargs):
        self.puts.append(kwargs)


class FakeBedrock:
    def __init__(self):
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "output": {"message": {"content": [{"text": "Document Type and Purpose: NDA."}]}},
            "usage": {"inputTokens": 120, "outputTokens": 8},
        }


def load_handler(max_input_chars="50000"):
    """Import lambda_function with a stub boto3 so module-level clients are fakes."""
    fake_boto3 = types.ModuleType("boto3")
    fake_boto3.client = lambda name: None
    sys.modules["boto3"] = fake_boto3
    os.environ.update(OUTPUT_BUCKET="out-bucket", MAX_INPUT_CHARS=max_input_chars)
    sys.path.insert(0, str(ROOT / "src" / "summarize_function"))
    sys.modules.pop("lambda_function", None)
    import lambda_function
    return lambda_function


class HandlerTest(unittest.TestCase):
    def setUp(self):
        self.event = json.loads((ROOT / "events" / "s3-put-test-event.json").read_text())
        self.bucket = self.event["Records"][0]["s3"]["bucket"]["name"]

    def run_handler(self, document, max_input_chars="50000"):
        fn = load_handler(max_input_chars)
        fn.s3 = FakeS3({(self.bucket, "sample legal document.txt"): document})
        fn.bedrock = FakeBedrock()
        result = fn.lambda_handler(self.event, None)
        return fn, result

    def test_summary_written_to_output_bucket(self):
        fn, result = self.run_handler(b"This Non-Disclosure Agreement is made between ...")
        put = fn.s3.puts[0]
        self.assertEqual(put["Bucket"], "out-bucket")
        self.assertEqual(put["Key"], "summaries/sample legal document-summary.txt")
        self.assertEqual(put["Body"], b"Document Type and Purpose: NDA.")
        self.assertEqual(put["Metadata"]["truncated"], "false")
        self.assertEqual(result, {"summaries": [{
            "source": "sample legal document.txt",
            "summary": "summaries/sample legal document-summary.txt",
        }]})

    def test_document_sent_to_bedrock_with_system_prompt(self):
        fn, _ = self.run_handler(b"Lease agreement text")
        call = fn.bedrock.calls[0]
        self.assertEqual(call["modelId"], "amazon.nova-lite-v1:0")
        self.assertIn("Lease agreement text", call["messages"][0]["content"][0]["text"])
        self.assertIn("Parties", call["system"][0]["text"])

    def test_long_document_is_truncated(self):
        fn, _ = self.run_handler(b"x" * 5000, max_input_chars="1000")
        sent = fn.bedrock.calls[0]["messages"][0]["content"][0]["text"]
        self.assertEqual(sent.count("x"), 1000)
        self.assertEqual(fn.s3.puts[0]["Metadata"]["truncated"], "true")


if __name__ == "__main__":
    unittest.main()
