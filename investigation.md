TLDR: Grep for using across both repos first — that single command tells you every real bicep↔bicepparam relationship, cutting through any naming-convention assumptions.

Concrete investigation steps, in order of signal-to-effort:

Find every using line across both repos — this is ground truth, nothing else matters as much:
bash
grep -rn "^using" --include="*.bicepparam" /path/to/common-cicd-repo /path/to/dev-repo

This tells you exactly which .bicepparam targets which .bicep, regardless of filenames or folder structure.

Find every .bicepparam file that has NO using line (would indicate either a non-Bicep file with a confusing name, or a broken/invalid file):
bash
find . -name "*.bicepparam" -exec sh -c 'head -1 "$1" | grep -q "^using" || echo "NO USING LINE: $1"' _ {} \;
Trace the CI YAML invocation chain — grep both repos' .yml/.yaml for where az deployment or bicep build-params/az deployment group create --parameters is actually called, and what path is passed:
bash
grep -rn "\-\-parameters\|bicepparam\|az deployment" --include="*.yml" --include="*.yaml" .

This shows you which CI job invokes which .bicepparam, which is the "who actually deploys what, when" answer — the using line tells you the template relationship, but the CI YAML tells you the trigger/sequence relationship (your "invoker CI triggers actual CI" pattern).

Check for a workflow_call / repository_dispatch / reusable-workflow reference between the two GH repos — since you said the dev repo's CI triggers the common CI/CD repo's CI, search for:
bash
grep -rn "workflow_call\|uses:.*\.github\|repository_dispatch" .github/workflows/

This is the actual cross-repo trigger mechanism (GH Actions reusable workflows or dispatch events), separate from and orthogonal to the Bicep using relationships.

Once you have the using map (step 1) and the CI trigger map (step 3/4) side by side, build a simple table: bicepparam file → using target → invoked by which CI job → triggered by which repo/event. That table will make any mismatch (like bp2→b1 when you expected bp2→b2) immediately visible instead of something you have to reason about in the abstract.

Steps 1 and 3 alone will probably answer 90% of your confusion in under five minutes once you're at the actual machine.

TLDR: With scattered .github folders per subproject, you need to enumerate at the .github folder level first, then map each one's environment .bicepparam files to their using targets and their own workflows — a monorepo-wide sweep, not a single grep.

Extended investigation plan:

1. Enumerate every .github folder first (mono repos hide multiple independent CI units):

bash
find . -type d -name ".github" | sort

This gives you the actual unit-of-CI boundaries — each one is effectively its own "mini repo" for CI purposes (API's .github, UI's .github, etc.), even though they share a git history.

2. For each .github folder found, map its environment folder's bicepparam files to using targets — do this per-unit, not repo-wide, so you don't conflate API's params with UI's params:

bash
find . -type d -name ".github" | while read gh; do
  echo "=== $gh ==="
  find "$gh/environment" -name "*.bicepparam" 2>/dev/null | while read bp; do
    echo "  $bp -> $(head -1 "$bp")"
  done
done

Output becomes a clean per-unit table: which .github folder, which env file, which using target.

3. For each .github folder, list what workflows actually reference which environment files — this ties CI trigger to bicepparam usage:

bash
find . -type d -name ".github" | while read gh; do
  echo "=== $gh/workflows ==="
  grep -rn "bicepparam\|environment/" "$gh/workflows" 2>/dev/null
done

4. Cross-reference environment folder names against the "using" targets from step 2 — since you likely have one .bicepparam per environment (dev/staging/prod) per subproject, check whether they all using the same template (expected — one shared common CI/CD template) or whether some environments accidentally point elsewhere:

bash
find . -path "*/environment/*.bicepparam" -exec sh -c 'echo "$1: $(grep "^using" "$1")"' _ {} \;

Any environment file whose using target doesn't match the pattern of the others in the same .github folder is your anomaly.

5. If workflows call the common CI/CD repo as a reusable workflow, find exactly which environment file gets passed in as an input — reusable workflow inputs are the actual runtime binding, separate from the static using declaration:

bash
grep -rn "environment/\|bicepparam" **/.github/workflows/*.yml

Look specifically for with: blocks or env: blocks feeding a path into the reusable workflow call — that's what determines which bicepparam actually gets used for a given environment/trigger, at runtime, versus what merely exists on disk.

6. Build the final table per subproject: .github folder → environment file → using target (static) → workflow input value (runtime) → triggered by (push/PR/manual/reusable-call). Mismatches between the static using target and what you expected that environment to deploy are what you're actually hunting for.

Start with steps 1–2 — that alone will tell you how many independent CI units you actually have and which template each one's params resolve to, before you even touch the workflow-trigger layer.

TLDR: Same investigation pattern, aimed at the CICD repo this time — find what it references from "infra" (bicep files, modules, or reusable actions), since that's the only way "infra" could be wired in without you already having spotted it in the dev repos.

Given what you've mapped so far — dev repo invoker YAMLs → CICD repo's actual YAMLs — "infra" is most likely referenced from inside the CICD repo, not from the dev repos directly. That would explain why you can't trace it from the dev-proj side: it's a layer further down.

1. Search the CICD repo's workflows for any reference to an "infra" repo — checkout actions, submodule paths, or reusable workflow calls crossing repo boundaries:

bash
grep -rn "infra" .github/workflows/ --include="*.yml" --include="*.yaml"

Look specifically for actions/checkout steps with a repository: field pointing at the infra repo, or uses: org/infra/...@ref reusable-workflow/action references.

2. Check for git submodules or subtree pulls in the CICD repo pointing to infra:

bash
cat .gitmodules 2>/dev/null
grep -rn "infra" .git/config 2>/dev/null

3. Search the CICD repo's own bicep/bicepparam using lines and any --template-file CLI args for paths that resolve outside the CICD repo itself (i.e., into a checked-out infra repo path):

bash
grep -rn "^using\|template-file" --include="*.bicep*" --include="*.yml" .

If b1.bicep (or wherever the "actual" deployment template lives) itself lives in the infra repo and gets checked out into the CICD repo's workspace at runtime, this is where you'd see it — e.g. a checkout step with path: infra followed by --template-file infra/b1.bicep.

4. Check for infra being pulled in as a container/artifact rather than source — some CICD setups reference infra via a published OCI artifact (az bicep publish) rather than a raw git checkout:

bash
grep -rn "bicep publish\|br:\|oci:" --include="*.bicep*" --include="*.yml" .

Bicep supports registry-published modules (br:myregistry.azurecr.io/bicep/modules/...) — if infra publishes modules this way, the CICD repo's bicep files would reference them via module foo 'br:...' instead of a relative file path, which wouldn't show up in a simple filesystem trace at all.

5. If none of the above show anything, check whether "infra" is referenced by name/tag/environment variable rather than hardcoded path — search for it as a variable:

bash
grep -rn "INFRA\|infra_repo\|INFRA_REPO" .github/workflows/ .github/actions/ 2>/dev/null

Some orgs parameterize the repo name via a GH Actions variable/secret so it's not literally the string "infra" anywhere in a workflow file — worth checking vars:/env: blocks and any composite actions the CICD repo defines under .github/actions/.

Step 4 (OCI/registry-published Bicep modules) is worth checking first if step 1 comes back empty — that's the most common reason an "infra" repo's actual usage is invisible to a plain grep: it's not being checked out or referenced by path at all, it's being consumed as a versioned published artifact, which is a very different (and easy to miss) wiring pattern.

TLDR: Yes, worth proposing — it directly solves the "can't trace where infra is used" problem by making dependencies explicit and versioned, instead of relative-path/checkout tricks. And it's not ACR-only — GHCR (free, you already have GitHub) works too.

Why it fits your situation specifically:

Solves your actual pain point: right now, tracing "infra" usage requires grepping for checkout/path tricks across repos (steps 1-5 above). A registry makes the dependency explicit and greppable in one place — module x 'br:ghcr.io/org/infra/vnet:1.2.0' in a bicep file is the trace, no CI archaeology needed.
Versioning for free: currently, if "infra" changes, every consumer (CICD repo, dev repos) gets whatever's on disk at checkout time — implicit, unpinned. A registry gives you semantic versions per module, so CICD/dev repos pin to 1.2.0 and don't silently break when infra changes main.
Cost-averse fit: doesn't require ACR (paid). GitHub Container Registry (GHCR) is OCI-compliant, free for public repos and cheap/free-tier-friendly for private ones tied to a GitHub org you already use — az bicep publish --target br:ghcr.io/... works against it same as ACR.
2-5 years ago excuse is gone: Bicep registry modules (br: syntax) have been stable Bicep-CLI functionality for a while now, and GHCR-as-Bicep-registry is a well-trodden pattern — not bleeding-edge, safe to propose.

Trade-off to flag when proposing: it's a workflow change, not free — publishing becomes a step (az bicep publish on infra's release/tag), and every consuming .bicep file's module blocks need rewriting from relative paths to br: references. That's a one-time migration cost, worth it given you're already deep in a multi-repo tracing exercise that a registry would eliminate going forward.
