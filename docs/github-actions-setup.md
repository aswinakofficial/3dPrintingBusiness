# Building runtime images via GitHub Actions

`az acr build` is restricted on free / trial / $200-credit Azure subscriptions
(`TasksOperationsNotAllowed`). The workaround is to build the runtime images
on GitHub-hosted runners and push them to your ACR. This document is the
one-time setup.

## Prerequisites

- The repo is pushed to a GitHub repository you own.
- Terraform infra is already deployed (your ACR exists).
- You're logged in with `az login` to the same subscription.

## 1. Collect IDs you'll need

```fish
set ACR_NAME (terraform -chdir=terraform output -raw container_registry_name)
set ACR_ID (az acr show --name $ACR_NAME --query id -o tsv)
set SUB_ID (az account show --query id -o tsv)

echo "ACR_NAME=$ACR_NAME"
echo "ACR_ID=$ACR_ID"
echo "SUB_ID=$SUB_ID"
```

## 2. Create a service principal with AcrPush role

This creates a non-human identity that GitHub Actions uses to push images.
`--json-auth` produces a JSON document `azure/login@v2` understands directly.

```fish
az ad sp create-for-rbac \
  --name "github-actions-3dfigurine" \
  --role AcrPush \
  --scopes $ACR_ID \
  --json-auth
```

The output looks like:

```json
{
  "clientId": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "clientSecret": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "subscriptionId": "...",
  "tenantId": "...",
  ...
}
```

**Copy the entire JSON object — including the curly braces.** You'll paste it
into a GitHub secret in the next step. The `clientSecret` is shown only
once; if you lose it, run `az ad sp credential reset` to generate a new one.

## 3. Add the JSON as a GitHub repository secret

In your GitHub repo → **Settings → Secrets and variables → Actions → New
repository secret**:

- Name: `AZURE_CREDENTIALS`
- Value: the entire JSON from step 2

## 4. (Optional) Override the default ACR name

If your ACR isn't named `acr3dfigurinelabdev`, the workflow falls back to
that default. Override it per-run via the workflow_dispatch input, or edit
the `REGISTRY_NAME` env in `.github/workflows/build-images.yml`.

## 5. Trigger the build

Push to `main` (any change to `docker/`, `engines/`, `utils/`, `main.py`,
`config.yaml`, or `requirements-runtime.txt` will fire the workflow), or
trigger manually:

GitHub repo → **Actions → Build runtime images → Run workflow**.

You can pick which image(s) to build. First-time builds take ~25-40 minutes
(downloading CUDA + PyTorch + 3D libraries). Subsequent builds are
~5-10 minutes thanks to the buildcache stored in ACR itself.

## 6. Verify

After the workflow succeeds:

```fish
az acr repository list --name $ACR_NAME -o table
az acr repository show-tags --name $ACR_NAME --repository 3dfigurine-trellis -o table
```

You should see `latest` and `buildcache` tags for each image. Then submit
a smoke-test job from your laptop:

```fish
python scripts/run_job.py --engine trellis --input ./input/photo.jpg --smoke-test
```

## Maintenance

- The service principal credential expires after 1 year. To rotate:
  ```fish
  az ad sp credential reset --id <clientId> --json-auth
  ```
  Update the `AZURE_CREDENTIALS` GitHub secret with the new JSON.

- To grant a second registry or environment, run a new
  `az role assignment create --assignee <clientId> --role AcrPush --scope <other-acr-id>`.

- To revoke GitHub access entirely:
  ```fish
  az ad sp delete --id <clientId>
  ```

## Future hardening (not required to ship)

The current setup uses a long-lived client secret. The more secure pattern is
**OIDC federated credentials** — GitHub presents a short-lived OIDC token,
Azure trusts it, no secret stored. Setup is one extra Terraform resource
(`azuread_application_federated_identity_credential`) and a different
`azure/login@v2` invocation. Defer until the project leaves the prototype
stage.
