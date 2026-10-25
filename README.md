# Trial of the Century: Modern Cloud Architecture v. AI

Udacity AWS Cloud Architect project (*Modernizing and Optimizing Architecture*). In this project, I work as a solution architect at **ObjectionInspection**, a fictional legal software startup. The task is to build a serverless pipeline that summarizes legal documents with a foundation model on **Amazon Bedrock**.

A plaintext document uploaded to a private, encrypted S3 bucket triggers a Lambda function. The function sends the document to Amazon Nova Lite through the Bedrock Converse API and stores the summary in a second private, encrypted bucket. All of it runs under a least-privilege IAM role.

![Architecture diagram: a user uploads a .txt legal document to the encrypted, private S3 input bucket; the ObjectCreated event invokes a Lambda function, which reads the document, sends it with a summarization prompt to Amazon Nova Lite through the Bedrock Converse API, and writes the summary to the encrypted, private S3 output bucket; the function runs under a least-privilege IAM role and logs to CloudWatch](docs/architecture.svg)

## Deliverables

| Requirement | Where |
| --- | --- |
| Architecture diagram | [`docs/architecture.svg`](docs/architecture.svg) / [`.png`](docs/architecture.png) |
| Screenshots (bucket configs, Lambda execution, stored summary, deployment) | [`docs/screenshots/`](docs/screenshots/) |
| Part 2: cost-optimization answers | [`project_answers.md`](project_answers.md) |
| Part 3: validated CloudFormation template | [`cloudformation.yaml`](cloudformation.yaml) |
| Clean-up confirmation | [`project_answers.md`](project_answers.md#clean-up-confirmation) |

## Repository layout

```text
cloudformation.yaml               Validated template: 2 buckets, bucket policies, IAM role, Lambda, log group, S3 trigger
project_answers.md                Part 1 summary, Part 2 answers, Part 3 template notes
src/summarize_function/
  lambda_function.py              Lambda handler (same code is inlined in the template)
events/s3-put-test-event.json     Lambda console test event (edit bucket + key)
infra/deploy.sh                   validate-template + deploy, optional end-to-end test
infra/teardown.sh                 empty both buckets, delete the stack
docs/console-walkthrough.md       Step-by-step console build, screenshot list, IaC generator steps
docs/architecture.svg / .png      Architecture diagram
docs/screenshots/                 Submission screenshots
samples/                          Put the sample legal document from the project Downloads tab here
tests/                            Unit tests (stdlib only, no AWS calls)
```

## How it works

1. A `.txt` document lands in the **input bucket**, and S3 sends an `ObjectCreated` event to the function.
2. The **Lambda function** reads the object and truncates it to `MAX_INPUT_CHARS`. It then calls `bedrock-runtime:Converse` with a summarization system prompt, using temperature 0.2 and a `MAX_OUTPUT_TOKENS` cap.
3. The summary is written to `summaries/<name>-summary.txt` in the **output bucket**. The object metadata records the model ID, the token counts, and whether the input was truncated.

Security: both buckets have SSE-S3 (AES-256) encryption, all four Block Public Access settings on, ACLs disabled, and TLS-only bucket policies. The execution role can only read the input bucket, write `summaries/*` to the output bucket, invoke one model, and write to its own log group. No credentials appear anywhere in the code.

## Running it

The full manual build, with the screenshot list, is in [`docs/console-walkthrough.md`](docs/console-walkthrough.md). To deploy from the CLI:

1. Copy `.env.example` to `.env` and fill in the temporary credentials from the course's Cloud Resources page. `.env` is git-ignored.
2. Put the sample document in `samples/`.
3. From the repo root (Git Bash on Windows):

```bash
bash infra/deploy.sh samples/<sample-file>.txt
```

This validates the template, deploys the stack `objection-inspection` (override with `STACK_NAME`), uploads the document, waits for the summary, and prints it.

```bash
bash infra/teardown.sh
```

Parameters: `ProjectName` (resource name prefix), `ModelId` (default `amazon.nova-lite-v1:0`), `MaxInputChars`, `MaxOutputTokens`, `LogRetentionDays`.

## Testing

```bash
python -m unittest discover -s tests -v
```

The handler tests stub S3 and Bedrock. The template test fails if the inline code in `cloudformation.yaml` drifts from `src/summarize_function/lambda_function.py`, or goes over CloudFormation's 4,096-character inline limit. After editing the handler, copy it into the template's `ZipFile` block, indented 10 spaces.

Lint the template with [cfn-lint](https://github.com/aws-cloudformation/cfn-lint):

```bash
cfn-lint cloudformation.yaml
```
