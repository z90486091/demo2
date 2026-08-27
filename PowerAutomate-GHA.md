# Copilot prompt

```
Create a scheduled cloud flow named "WSOD GH Trigger" that does the following:

1. Trigger: Recurrence, set to run twice per hour at minute 23 and minute 51 of every hour.

2. Action: Send an HTTP POST request to
   https://api.github.com/repos/<owner>/<repo>/actions/workflows/wsod-monitor.yml/dispatches
   with headers:
     Authorization: Bearer <GITHUB_PAT>
     Accept: application/vnd.github+json
     X-GitHub-Api-Version: 2022-11-28
   and JSON body: { "ref": "main" }

3. Action: Delay for 90 seconds to allow the GitHub Actions run to complete.

4. Action: Send an HTTP GET request to
   https://api.github.com/repos/<owner>/<repo>/actions/runs?event=workflow_dispatch&per_page=1
   with the same Authorization header as step 2.

5. Action: Parse the JSON response from step 4 to extract workflow_runs[0].id and workflow_runs[0].conclusion.

6. Condition: If conclusion equals "failure", do the following (Yes branch); otherwise do nothing (No branch):
   a. Send an HTTP GET request to
      https://api.github.com/repos/<owner>/<repo>/actions/runs/{run id from step 5}/artifacts
      with the same Authorization header.
   b. Parse the JSON response to extract artifacts[0].archive_download_url.
   c. Send an HTTP GET request to that archive_download_url (same Authorization header) to download the artifact zip as binary content.
   d. Save the downloaded file to OneDrive for Business (or SharePoint) in a folder I specify, named "wsod-artifacts-" followed by the current UTC timestamp, with a .zip extension.
   e. Post a message in a Microsoft Teams channel I specify, including a link to the GitHub Actions run
      (https://github.com/<owner>/<repo>/actions/runs/{run id}) and a link to the saved OneDrive/SharePoint file.

7. Set the flow owner notification setting so I receive an email if the flow itself fails to run.
```

# PA Steps

## Power Automate → GitHub Actions — WSOD Monitor Flow

### 1. Create scheduled trigger
- Teams → **Workflows** app → **+ New flow** → **Scheduled cloud flow**
- Name: `WSOD GH Trigger`
- Recurrence: 1 hour → **Show advanced options** → set minutes: `23, 51`

### 2. Dispatch GitHub workflow
- **+ New step** → `HTTP`
- Method: `POST`
- URI: `https://api.github.com/repos/<owner>/<repo>/actions/workflows/wsod-monitor.yml/dispatches`
- Headers:
  - `Authorization`: `Bearer <GITHUB_PAT>`
  - `Accept`: `application/vnd.github+json`
  - `X-GitHub-Api-Version`: `2022-11-28`
- Body: `{"ref": "main"}`

### 3. Wait for run to finish
- **+ New step** → `Delay`
- Duration: `90 seconds`

### 4. Poll run result
- **+ New step** → `HTTP`
- Method: `GET`
- URI: `https://api.github.com/repos/<owner>/<repo>/actions/runs?event=workflow_dispatch&per_page=1`
- Headers: same as step 2

### 5. Parse the response
- **+ New step** → `Parse JSON`
- Content: body of step 4
- Extract: `workflow_runs[0].id`, `workflow_runs[0].conclusion`

### 6. Check for failure
- **+ New step** → `Condition`
- If `conclusion` is equal to `failure`

### 7. On failure — list artifacts
- **Yes branch** → `HTTP` → `GET`
- URI: `https://api.github.com/repos/<owner>/<repo>/actions/runs/<run_id>/artifacts`
- Headers: same as step 2

### 8. On failure — parse artifact URL
- `Parse JSON` → extract `artifacts[0].archive_download_url`

### 9. On failure — download the zip
- `HTTP` → `GET` → URI: the `archive_download_url` from step 8
- Headers: same as step 2 (auth required even on download)

### 10. On failure — save to OneDrive/SharePoint
- `Create file` action
- Folder: your chosen path
- File name: `wsod-artifacts-<timestamp>.zip`
- Content: binary output of step 9

### 11. On failure — alert Teams
- `Post message in a chat or channel`
- Include: GitHub run link + OneDrive/SharePoint file link

### 12. Save and test
- Save flow → **Test** → **Manually** → **Run flow**
- Confirm 204 on dispatch, correct conclusion parsed, and (if forced failure) file saved + Teams message posted

### 13. (Optional) Flow-failure alerting
- Flow owner settings → enable **"Send an email when a cloud flow fails"**


# GH PAT

**Fine-grained PAT:** Repository access → this repo only → Permissions → `Actions: Read and write` + `Contents: Read-only` (unchanged, fine-grained scoping already handles private repos correctly).

**Classic PAT:** must use full `repo` scope (not `public_repo`) + `workflow` scope — `public_repo` alone won't work on a private repo regardless of `workflow` being set.

**TL;DR:** Private repo → Classic PAT needs `repo` + `workflow` (not `public_repo`); fine-grained stays `Actions: Read+write` + `Contents: Read-only`.
