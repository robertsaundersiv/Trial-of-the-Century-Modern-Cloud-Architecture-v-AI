# Console Walkthrough (Part 1) and IaC Generator (Part 3)

Build the summarizer by hand in the AWS Console, collect the screenshots, generate a template with the IaC generator, and then deploy [`cloudformation.yaml`](../cloudformation.yaml) as the validated version.

Everything runs in **us-east-1 (N. Virginia)** in the temporary Udacity account. Open the console from the course's **Cloud Resources** page.

> [!NOTE]
> The resources you create by hand use the prefix `objection-inspection-console`. The CloudFormation stack uses `objection-inspection`. The two sets can exist side by side, so the stack deploy doesn't fail on bucket names that are already taken.

Throughout, replace `<account-id>` with the 12-digit ID shown in the console's top-right menu.

## 0. Check Bedrock model access

> [!WARNING]
> In the Udacity (Vocareum) lab account, the lab policy `Pvoclabs3` explicitly denies `bedrock:ListFoundationModels` and `bedrock:ListInferenceProfiles`. Because of that, the **Model catalog** and **Playground** pages show "not authorized" errors. Those denies cover only *listing* models, not *calling* them, so test by calling the model directly instead.

1. Open **CloudShell** (the `>_` icon in the console's top bar, us-east-1) and run:

   ```bash
   aws bedrock-runtime converse --region us-east-1 \
     --model-id amazon.nova-lite-v1:0 \
     --messages '[{"role":"user","content":[{"text":"Reply with the word OK."}]}]' \
     --query 'output.message.content[0].text' --output text
   ```

   If it prints `OK`, the account can call Nova Lite. Keep the defaults and go on to step 1.
2. If it prints `AccessDeniedException`, check which models the lab allows:

   ```bash
   for m in amazon.nova-micro-v1:0 amazon.nova-pro-v1:0 amazon.titan-text-express-v1 \
            anthropic.claude-3-haiku-20240307-v1:0 meta.llama3-8b-instruct-v1:0; do
     printf '%-45s ' "$m"
     aws bedrock-runtime converse --region us-east-1 --model-id "$m" \
       --messages '[{"role":"user","content":[{"text":"Reply with the word OK."}]}]' \
       --query 'output.message.content[0].text' --output text 2>&1 | head -1
   done
   ```

   You can also read the lab policy itself, if the account allows it:

   ```bash
   P=arn:aws:iam::<account-id>:policy/Pvoclabs3
   aws iam get-policy-version --policy-arn $P \
     --version-id $(aws iam get-policy --policy-arn $P --query Policy.DefaultVersionId --output text)
   ```

3. Use the first model that answers in all three places: the Lambda `MODEL_ID` variable, the IAM policy's `InvokeSummaryModel` resource, and the template's `ModelId` parameter.

These calls run as the lab's `voclabs` role. The Lambda function runs as its own execution role, which `Pvoclabs3` does not apply to. A model that works from CloudShell should therefore work from the function, too. The **Lambda test event in step 6** is the real check.

The prompt is modeled on the Bedrock console's **Examples** (summarization): it gives the model a role, an audience, a length limit, and a fixed output structure.

## 1. Create the input bucket

**S3 → Create bucket**

| Setting | Value |
| --- | --- |
| Bucket type | General purpose |
| Name | `objection-inspection-console-input-<account-id>` |
| Object Ownership | ACLs disabled (recommended) |
| Block Public Access | **Block all public access** (leave checked) |
| Bucket Versioning | Disable |
| Default encryption | **Server-side encryption with Amazon S3 managed keys (SSE-S3)** (this is AES-256) |

📸 **Screenshot:** the bucket's **Permissions** tab (Block Public Access all On) and **Properties → Default encryption** (SSE-S3).

## 2. Create the output bucket

Repeat step 1 with the name `objection-inspection-console-output-<account-id>`.

📸 **Screenshot:** the same two settings for the output bucket.

### Optional: require TLS

On each bucket, go to **Permissions → Bucket policy** and paste the following, replacing `BUCKET`:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "DenyInsecureTransport",
    "Effect": "Deny",
    "Principal": "*",
    "Action": "s3:*",
    "Resource": ["arn:aws:s3:::BUCKET", "arn:aws:s3:::BUCKET/*"],
    "Condition": {"Bool": {"aws:SecureTransport": "false"}}
  }]
}
```

## 3. Create the least-privilege IAM role

**IAM → Policies → Create policy → JSON**. Name it `objection-inspection-console-summarize-policy`.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadInputDocuments",
      "Effect": "Allow",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::objection-inspection-console-input-<account-id>/*"
    },
    {
      "Sid": "WriteSummaries",
      "Effect": "Allow",
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::objection-inspection-console-output-<account-id>/summaries/*"
    },
    {
      "Sid": "InvokeSummaryModel",
      "Effect": "Allow",
      "Action": "bedrock:InvokeModel",
      "Resource": "arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-lite-v1:0"
    },
    {
      "Sid": "WriteOwnLogs",
      "Effect": "Allow",
      "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
      "Resource": "arn:aws:logs:us-east-1:<account-id>:log-group:/aws/lambda/objection-inspection-console-summarize:*"
    }
  ]
}
```

Then **IAM → Roles → Create role**:

- Trusted entity: **AWS service → Lambda**.
- Permissions: only `objection-inspection-console-summarize-policy`. Don't add `AWSLambdaBasicExecutionRole` or any S3 or Bedrock "FullAccess" policy.
- Name: `objection-inspection-console-summarize-role`.

📸 **Screenshot:** the role's **Permissions** tab with the policy JSON expanded.

> The console version adds `logs:CreateLogGroup` because Lambda creates its own log group the first time it runs. The CloudFormation template creates the log group itself (with retention), so its role does not need that permission.

## 4. Create the Lambda function

**Lambda → Create function → Author from scratch**

| Setting | Value |
| --- | --- |
| Name | `objection-inspection-console-summarize` |
| Runtime | Python 3.13 |
| Architecture | arm64 |
| Execution role | Use an existing role → `objection-inspection-console-summarize-role` |

Then:

1. **Code:** replace `lambda_function.py` with the contents of [`src/summarize_function/lambda_function.py`](../src/summarize_function/lambda_function.py) and click **Deploy**.
2. **Configuration → General configuration:** set Memory to 256 MB and Timeout to 2 min 0 sec.
3. **Configuration → Environment variables:**

   | Key | Value |
   | --- | --- |
   | `OUTPUT_BUCKET` | `objection-inspection-console-output-<account-id>` |
   | `MODEL_ID` | `amazon.nova-lite-v1:0` |
   | `MAX_INPUT_CHARS` | `50000` |
   | `MAX_OUTPUT_TOKENS` | `1024` |

## 5. Add the S3 trigger

On the function page, click **Add trigger → S3**:

- Bucket: the **input** bucket
- Event types: **All object create events**
- Suffix: `.txt`
- Check the recursive-invocation acknowledgement. The function writes to a *different* bucket, so it can't trigger itself.

The console adds the matching resource-based permission for you. You can see it under **Configuration → Permissions → Resource-based policy statements**.

📸 **Screenshot:** the function overview diagram showing the S3 trigger. Also take **input bucket → Properties → Event notifications**.

## 6. Test with a Lambda test event

1. Upload the sample legal document from the project's Downloads tab to the input bucket. Copy its key, for example `sample_legal_document.txt`.
2. **Test → Create new event**, named `s3-put`. Paste [`events/s3-put-test-event.json`](../events/s3-put-test-event.json), then change `bucket.name`, `bucket.arn`, and `object.key` to your input bucket and the uploaded key. In the JSON, spaces in the key are written as `+`.
3. Click **Test**. The result should be `{"summaries": [{"source": ..., "summary": "summaries/...-summary.txt"}]}`. The log output should contain the `Summarized s3://... (N in / M out tokens ...)` line.

📸 **Screenshot:** the successful test result with its log output, and **Monitor → View CloudWatch logs** showing the invocation.

If it fails:

- `AccessDeniedException` from Bedrock: the model ID in the IAM policy doesn't match `MODEL_ID`, or model access isn't enabled (step 0).
- `AccessDenied` from S3: check the bucket names in the policy, and that the output key is under `summaries/`.
- Timeout: raise the timeout, or lower `MAX_INPUT_CHARS`.

## 7. End-to-end test

Upload the sample document again with a new name, such as `sample_legal_document_2.txt`. Within a few seconds, `summaries/sample_legal_document_2-summary.txt` should appear in the output bucket. Open it (**Open**, or **Download**). Its **Metadata** shows the model ID and token counts.

📸 **Screenshot:** the output bucket listing, and the summary's contents.

## 8. Generate a template with the IaC generator (Part 3)

1. **CloudFormation → IaC generator → Start a new scan**. Choose **Scan all resources** (or scan specific resource types: S3, Lambda, IAM). Wait for the scan to finish.
2. **Create template** → *Start from a new template*, named `objection-inspection-console`.
3. Add only the solution's resources:
   - `AWS::S3::Bucket` × 2 (the console input and output buckets)
   - `AWS::S3::BucketPolicy` × 2 (if you added them)
   - `AWS::IAM::Role` (`objection-inspection-console-summarize-role`) and its managed policy
   - `AWS::Lambda::Function` (`objection-inspection-console-summarize`)
   - `AWS::Lambda::Permission` (the S3 invoke permission)

   Don't add the "related resources" it suggests that belong to the course account, such as other roles, log groups, or Udacity's own stacks.
4. Download the YAML and save it as `docs/iac-generator-output.yaml` for comparison.
5. Compare it with [`cloudformation.yaml`](../cloudformation.yaml). The refinements to look for are listed in `project_answers.md` → *Refinements over the IaC generator output*. They include hard-coded account IDs and ARNs, a code location in Lambda's internal staging bucket, the bucket/notification/permission ordering, and extra default properties.

📸 **Screenshot:** the IaC generator template page showing the selected resources.

## 9. Validate and deploy `cloudformation.yaml`

Put the Cloud Resources credentials in `.env` (copy [`.env.example`](../.env.example)). Then, from the repo root in Git Bash:

```bash
bash infra/deploy.sh samples/<sample-file>.txt
```

The script runs `validate-template` and `cloudformation deploy` with `CAPABILITY_NAMED_IAM`. It prints the stack outputs, uploads the sample document, waits for the summary, and prints it. You can also run the two commands from the project instructions directly, using `cloudformation.yaml` as the file.

📸 **Screenshot:** the `validate-template` output, the stack's **Events** tab ending in `CREATE_COMPLETE`, its **Resources** tab, and the printed summary.

## 10. Clean up

1. Stack resources: `bash infra/teardown.sh` empties both buckets and deletes the stack.
2. Console resources (delete in this order):
   1. Empty, then delete, both `objection-inspection-console-*` buckets.
   2. Delete the Lambda function.
   3. Delete the IAM role, then the policy.
   4. Delete the `/aws/lambda/objection-inspection-console-summarize` log group.
3. Delete the IaC generator template and scan (optional; they cost nothing).

Record the clean-up in `project_answers.md` → *Clean-Up Confirmation*.
