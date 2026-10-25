# Project Answers: Trial of the Century - Modern Cloud Architecture v. AI

## Part 1: Implementation

### Architecture

![Architecture diagram: a user uploads a .txt legal document to the encrypted, private S3 input bucket; the ObjectCreated event invokes a Lambda function, which reads the document, sends it with a summarization prompt to Amazon Nova Lite through the Bedrock Converse API, and writes the summary to the encrypted, private S3 output bucket; the function runs under a least-privilege IAM role and logs to CloudWatch](docs/architecture.png)

1. A user uploads a plaintext legal document (`*.txt`) to the **S3 input bucket** over HTTPS.
2. The bucket's **S3 Event Notification** (`s3:ObjectCreated:*`, suffix `.txt`) invokes the **Lambda function**, which reads the document with `s3:GetObject`.
3. The function sends the document and a summarization prompt to **Amazon Bedrock** (Converse API, Amazon Nova Lite). The prompt follows the Bedrock console's summarization examples: a role ("paralegal"), an audience ("busy attorney"), a length limit, and fixed headings (parties, key terms, dates, termination, risks).
4. The function writes the summary to `summaries/<name>-summary.txt` in the **S3 output bucket**. The object metadata records the model ID and the input and output token counts, so each summary's cost can be traced.

The function gets its credentials from its **IAM execution role**. No secrets are stored in code or environment variables. Logs go to **CloudWatch Logs** with 14-day retention.

### Security

| Control | How it is applied |
| --- | --- |
| Encryption at rest | Both buckets use default server-side encryption, SSE-S3 (AES-256). |
| No public access | All four S3 Block Public Access settings are on for both buckets. Object Ownership is `BucketOwnerEnforced`, so ACLs are disabled. |
| Encryption in transit | Both bucket policies deny any request where `aws:SecureTransport` is false. |
| Least privilege | The execution role can only `s3:GetObject` on the input bucket, `s3:PutObject` on `summaries/*` in the output bucket, `bedrock:InvokeModel` on one model ARN, and write to its own log group. It cannot list or delete objects, or reach any other bucket or model. The trust policy allows only `lambda.amazonaws.com` from this account. |
| Scoped trigger | The Lambda resource policy lets only `s3.amazonaws.com`, for this input bucket in this account, invoke the function. |
| No recursion | Summaries go to a different bucket than the trigger, so a summary can never re-trigger the function. |

### Screenshots

<!-- Add the screenshots to docs/screenshots/ and update the file names below. -->

1. Input bucket configuration (encryption, Block Public Access, event notification): `docs/screenshots/`
2. Output bucket configuration (encryption, Block Public Access): `docs/screenshots/`
3. Lambda function execution (test event result and CloudWatch log line): `docs/screenshots/`
4. Generated summary in the output bucket: `docs/screenshots/`

---

## Part 2: Cost Optimization

### 1. How would you further optimize your solution if your storage costs become prohibitively expensive?
To optimize storage costs, I would implement the following strategies:

**a. S3 Lifecycle policies on the input bucket, based on how legal documents are used.** A document is read once by the function when it is uploaded, and then rarely, unless a matter is reopened. Firms often must keep these documents for years. Paying S3 Standard prices (about $0.023/GB-month) for that whole time is the largest avoidable cost. I would add a lifecycle rule that:

- moves originals to **S3 Standard-IA** after 30 days (about $0.0125/GB-month, around 45% cheaper, still millisecond access),
- moves them to **S3 Glacier Instant Retrieval** after 90 days (about $0.004/GB-month, around 80% cheaper, still millisecond access when an attorney needs the original),
- moves them to **S3 Glacier Deep Archive** after 1 year (about $0.00099/GB-month, around 95% cheaper) for documents kept only for compliance, where a 12–48 hour restore is acceptable,
- **expires** objects when the firm's retention period ends, and aborts incomplete multipart uploads after 7 days, so the firm stops paying for data it no longer has to keep or that never finished uploading.

Lifecycle rules are a good fit because the access pattern is predictable: hot at upload, cold afterward. They cost nothing to configure, only a small per-object transition fee. I would keep the transitions after each class's minimum storage duration (30, 90, and 180 days) to avoid early-deletion charges.

**b. S3 Intelligent-Tiering when access is unpredictable.** Some practice areas pull old documents back often, for example litigation that is reopened or due-diligence reviews. A fixed lifecycle schedule could then move documents to a cold class and charge retrieval fees. **S3 Intelligent-Tiering** moves each object between Frequent, Infrequent (after 30 days without access), and Archive Instant Access (after 90 days) tiers based on actual access. It has no retrieval fees, and the optional archive tiers can be turned on for long-term originals. Its monitoring fee is about $0.0025 per 1,000 objects per month, which is small for documents that are hundreds of KB or more. Objects smaller than 128 KB are never moved to a cheaper tier, so it fits the large original documents, not the summaries.

**c. Keep the summaries in S3 Standard and keep fewer bytes overall.** Summaries are small (a few KB) and are the objects people actually read, so Standard is the right class for them. Moving them would save almost nothing, and the 128 KB minimum billable size in Standard-IA would raise their cost. To shrink what is stored:

- **Compress** documents with gzip before storing them. Legal text usually compresses by 70–80%, and the function can decompress it in memory before calling Bedrock.
- **Deduplicate** by storing documents under a SHA-256 content hash, so the same contract uploaded twice is stored (and summarized) once.
- Leave versioning off, or expire noncurrent versions after a short period, so overwritten files do not pile up.
- Keep CloudWatch log retention short (14 days in this template) instead of the default "never expire".

**d. Measure before and after.** I would turn on **S3 Storage Lens** and **Storage Class Analysis** on the input bucket to confirm the real access pattern and tune the transition days. I would also set an **AWS Budgets** alert on S3 spend so a cost increase is caught early.

---

### 2. How would you further optimize your solution if your model inference costs become prohibitively expensive?
To reduce model inference costs, I would consider the following optimizations:

Bedrock on-demand pricing is per token. Output tokens cost about 4× as much as input tokens. Amazon Nova Lite costs about $0.00006 per 1K input tokens and $0.00024 per 1K output tokens. A 10,000-token document with a 500-token summary therefore costs about **$0.00072**. Cost grows with the number of documents × tokens per document × price per token, so each strategy below reduces one of those factors.

**a. Use the smallest model that gives acceptable summaries, and route by document.** **Amazon Nova Micro** costs about $0.000035 / $0.00014 per 1K tokens, around 40% less than Nova Lite. The same document would cost about **$0.00042**. I would run both models on a sample set, have attorneys review the results, and keep the cheaper model if quality is acceptable. I would also route by document: short or routine documents (NDAs, standard leases) go to Nova Micro, and only long or complex agreements go to a larger model. This needs only a change to the `ModelId` parameter, or a length check in the function. Model choice is usually the single biggest cost factor.

**b. Batch inference for documents that are not urgent.** **Amazon Bedrock batch inference** charges about **50% less** than on-demand for the same model. Most summaries are not needed within seconds; next morning is fine. The function would write each request as a JSONL record to S3 instead of calling the model. A scheduled job (EventBridge Scheduler + Lambda) would then start one `CreateModelInvocationJob` each night, and a final step would copy the outputs into `summaries/`. Urgent documents, for example ones tagged `priority=high`, would keep the real-time path. The trade-off is latency, so this fits the bulk of the workload but not everything.

**c. Avoid paying twice for the same work: deduplicate and cache.** S3 delivers events at least once, and users re-upload files, so the same document can be summarized more than once. Before calling Bedrock, the function would hash the document and check whether a summary for that hash already exists (`HeadObject` on the output bucket). If it does, the function skips the model call, which costs nothing. When the same long document is sent several times with different instructions (for example a summary, then a risk list), **Bedrock prompt caching** bills the repeated document prefix at a large discount on later calls. That cuts the input cost of those follow-up requests.

**d. Send fewer tokens and generate fewer tokens.** Because cost is per token:

- **Preprocess** documents before calling the model: collapse whitespace, and remove repeated headers and footers, signature blocks, and boilerplate exhibits. This can remove a large share of input tokens without losing meaning.
- **Cap input size.** `MaxInputChars` already does this. For very large documents, summarize only the sections that matter (definitions, obligations, termination) instead of the whole text.
- **Cap output.** `MaxOutputTokens` and the 400-word limit in the prompt control the expensive output tokens. A tighter format (bullets instead of prose) lowers cost further.
- Keep the system prompt short, because it is sent with every request.

**e. Put guardrails on spend.** The function records input and output token counts in each summary's metadata and in its logs. I would use the Bedrock `InputTokenCount` and `OutputTokenCount` CloudWatch metrics with an alarm, and an **AWS Budgets** alert on Bedrock spend. I would also set Lambda **reserved concurrency** so a bulk upload, or a bug, cannot cause unlimited model calls at once. **Provisioned Throughput** is only cheaper at high, steady volume, so I would consider it only after the usage metrics show that kind of load. It is not a good fit for this bursty, upload-driven workload.

---

## Part 3: CloudFormation Template Validation

### Summary of the CloudFormation Template
The AWS CloudFormation template ([`cloudformation.yaml`](cloudformation.yaml)) includes the following resources:
1. **S3 Buckets**:
   - An input bucket to store uploaded legal documents (`<project>-input-<account>-<region>`).
   - An output bucket to store summarization results (`<project>-output-<account>-<region>`).
   - Both are configured with encryption (AES-256) and block public access. Each also has a bucket policy that denies requests not sent over TLS, and has ACLs disabled.
   - The input bucket's event notification invokes the Lambda function for every new `.txt` object.

2. **Lambda Function**:
   - A function to process S3 events, invoke Amazon Bedrock for summarization, and store the results in the output bucket.
   - Configured with appropriate memory size and timeout for handling large legal documents: 256 MB and 120 seconds. The function waits on the model and does little computing, so more memory would add cost without speeding it up. Documents are capped at `MaxInputChars` (50,000 characters by default) so a single call stays within the timeout and within budget.
   - Python 3.13 on arm64 (Graviton), which costs about 20% less per GB-second than x86. The code is inline, so the template deploys without uploading a package first.
   - A log group with 14-day retention, and an `AWS::Lambda::Permission` that allows only this account's input bucket to invoke the function.

3. **IAM Roles and Policies**:
   - A role with limited permissions for the Lambda function to access S3 and Bedrock securely. It allows `s3:GetObject` on the input bucket, `s3:PutObject` on the output bucket's `summaries/*`, `bedrock:InvokeModel` on the single configured model, and `logs:CreateLogStream` / `logs:PutLogEvents` on the function's own log group. No wildcard actions or managed policies are used.

**Parameters:** `ProjectName`, `ModelId`, `MaxInputChars`, `MaxOutputTokens`, `LogRetentionDays`. Everything that might change between environments is a parameter, and nothing is hard-coded to one account.

**Refinements over the IaC generator output.** The IaC generator scans existing resources, so its raw output needs cleanup before it can be reused. This template makes the following fixes:

- It includes only the solution's resources: the 2 buckets, 2 bucket policies, the role, the function, its log group, and its permission. It leaves out unrelated resources the scan picks up, such as other roles, Lambda's default log groups, and the course account's own resources.
- Hard-coded account IDs, ARNs, and bucket names are replaced with `!Sub`, `!Ref`, and `!GetAtt` plus parameters, so the stack can be deployed again in any account.
- The function's code location in Lambda's internal staging bucket is replaced with inline code.
- The circular dependency between the bucket notification, the Lambda permission, and the role is broken. The input bucket's name is built from parameters, and the bucket `DependsOn` the permission, so S3 can validate the notification target when the bucket is created.
- Generated read-only properties and default values are removed so the template is readable.

### Validation Steps
To validate the CloudFormation template:

1. **Syntax Validation**:
   - Run `aws cloudformation validate-template --template-body file://cloudformation.yaml`.
   - The template also passes `cfn-lint cloudformation.yaml` with no errors or warnings.

2. **Test Deployment**:
   - Deploy the template in a test environment using:
     ```bash
     aws cloudformation deploy --template-file cloudformation.yaml --stack-name test-stack --capabilities CAPABILITY_NAMED_IAM
     ```

3. **Verify Resources**:
   - Check that the S3 buckets, Lambda function, and IAM roles are created as expected.
   - Confirm that the Lambda function triggers correctly and interacts with Bedrock to process documents: upload the sample document to the input bucket and confirm that `summaries/<name>-summary.txt` appears in the output bucket.

<!-- Paste the validate-template output, the stack's CREATE_COMPLETE events, and the end-to-end test result here, or add screenshots to docs/screenshots/. -->

---

## Additional Notes

- Ensure all resources are cleaned up after testing to avoid unnecessary costs. `bash infra/teardown.sh` empties both buckets (CloudFormation cannot delete a bucket that still has objects) and then deletes the stack. Any resources created by hand in the console during Part 1 have to be deleted separately.
- Follow AWS security best practices, including the principle of least privilege for IAM roles.

### Clean-Up Confirmation

<!-- After teardown, confirm here, e.g.: "All resources (both S3 buckets, the Lambda function, its IAM role, and its log group) were deleted from the temporary AWS account on <date>." -->

---

### Author: Robert Saunders
