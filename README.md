# Naukri Profile Agent (GitHub Actions)

The profile workflow updates the configured headline, summary, key skills, and
resume, then searches and applies to suitable jobs at 09:00, 12:00, and 14:00
India time using a self-hosted Windows runner. Job criteria and the application
limit are defined in `config/profile.yaml`.

## How it works

```text
GitHub cron (09:00, 12:00, and 14:00 India time)
   → checkout repo
   → self-hosted Windows runner
   → Playwright (Chromium)
   → login via the authenticated session secret
   → update profile, search suitable jobs, and submit up to 10 applications
   → persist application ledger and upload a run report/artifacts
```

## Setup (15 minutes)

### 1. Put this repo on GitHub

```bash
cd "/home/mcw/Desktop/learning/Naikri Agent"
git add .
git commit -m "Initial Naukri GitHub Actions agent"
# create empty repo on GitHub, then:
git remote add origin git@github.com:<YOU>/naukri-agent.git
git push -u origin main
```

### 2. Configure secrets

Repo → **Settings → Secrets and variables → Actions**:

| Secret | Required | What it is |
|--------|----------|------------|
| `NAUKRI_EMAIL` | Optional | Naukri login email for local fallback login |
| `NAUKRI_PASSWORD` | Optional | Naukri password for local fallback login |
| `NAUKRI_STORAGE_STATE_GZ_B64` | Required for Actions | Compressed authenticated browser session |
| `NAUKRI_STORAGE_STATE_B64` | Alternative | Base64 authenticated browser session; refresh it when expired |
| `RESUME_B64` | optional | base64 of resume.pdf if not in repo |

Add these under **Settings → Secrets and variables → Actions**. Never put
credentials or session data in workflow files or commit them to the repository.
The GitHub Actions workflows require a captured session secret and stop
immediately if it is missing.

### 3. Capture a login session (recommended)

Naukri often asks for OTP in CI. Capture cookies once on your machine:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
python scripts/capture_session.py
```

The capture script opens a browser and waits while you complete the Naukri login
yourself, including OTP or captcha. It does not need your password in `.env`.
Keep the browser open until the script confirms that it saved the session.

On Windows, run these commands from the repository root in PowerShell. They
use the virtual environment's Python directly, so activation is not required:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe scripts\capture_session.py
```

Complete the OTP/captcha in the opened browser and wait for the capture script
to confirm it saved `storage_state.json`. Then authenticate GitHub CLI and
upload the session directly without copying or displaying it:

```powershell
& "$env:ProgramFiles\GitHub CLI\gh.exe" auth login
& "$env:ProgramFiles\GitHub CLI\gh.exe" auth status
.\.venv\Scripts\python.exe scripts\set_session_secret.py
```

If GitHub CLI is not installed, install it with
`winget install --id GitHub.cli --exact`. The commands above use its install
path directly, so a terminal restart or PATH update is not required.

The script removes only Naukri's large similar-jobs recommendation caches,
compresses the remaining session, verifies it fits GitHub's secret-size limit,
and sends it to GitHub using the CLI. The workflow decompresses it at runtime.
Re-capture when the session expires (usually weeks).

### 4. Set up the Windows Actions runner

Naukri blocks or times out requests from GitHub-hosted runners. The **Update
Naukri Profile** workflow therefore uses your Windows PC as a self-hosted runner.

1. In the GitHub repository, open **Settings → Actions → Runners → New
   self-hosted runner**, select **Windows** and **x64**, and follow GitHub's
   current instructions to download and configure the runner in a dedicated
   folder. Do not share the temporary runner registration token.
2. Start the runner interactively with `.\run.cmd` and leave its PowerShell
   window open. Keep the PC awake and the Windows user session signed in. The
   workflow opens a visible browser (`HEADLESS=0`), so do not run it as a
   Windows service in session 0.
3. Confirm the runner shows **Idle** under **Settings → Actions → Runners**.
   Then use **Actions → Update Naukri Profile → Run workflow**.

Scheduled profile updates and job searches only run while this PC is awake and
the runner is online. GitHub may start scheduled workflows a few minutes later
than the requested cron minute.

### 5. Add your résumé

`assets/resume.pdf` is gitignored because it may contain personal information.
For GitHub Actions, choose one:

```bash
# Private repo: force-add
git add -f assets/resume.pdf

# Or store it as an Actions secret (recommended)
$resumeB64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes("assets\resume.pdf"))
$resumeB64 | & "$env:ProgramFiles\GitHub CLI\gh.exe" secret set RESUME_B64 --repo devendrakumarchoudharyr6202-cyber/devendra
```

For a normal profile update, the workflow requires the `RESUME_B64` secret
unless the résumé is checked into the repository. Dry runs skip résumé restore.
The command above sends it through standard input; do not print or paste the
encoded résumé into chat.

### 6. Review `config/profile.yaml`

The configuration currently reflects 1 year of experience and the supplied
Python, SQL, Excel, Power BI, data analysis, data cleaning, and data
visualization skills. Confirm the résumé and all profile details are accurate.
The scheduled profile run adds missing core skills and removes the prior
unverified skills configured for cleanup.

### 7. Run it

- **Actions → Update Naukri Profile → Run workflow** for a manual run.
- Scheduled full runs occur at 09:00, 12:00, and 14:00 IST.
- Review the run's **Summary** for profile status, jobs found, confirmed
  applications, pending confirmations, and errors. The artifact includes the
  JSON run report and a copy of the application ledger.

## Job applications

```bash
HEADLESS=0 python src/main.py --mode apply
```

Rules:
1. Search Recommended and configured role queries across Naukri India.
2. The current configuration does not require a target-title or skill match.
   It accepts explicit experience requirements overlapping 0–5 years.
3. Prioritize postings from the last 24 hours; the configured cap is 50 per run
   and 50 per IST calendar day.
4. Track applications in `artifacts/applications.csv`. Keep this ledger between
   runs so the daily cap and duplicate checks remain effective. Confirmed and
   submission-unconfirmed attempts count toward the daily allowance.
5. Skip jobs already marked as applied on Naukri or present in the ledger.
   Submit only when Naukri confirms after the initial Apply action. If another
   Continue/Confirm/Submit action is required, do not click it; record the job
   as pending confirmation with its link for manual review.

The `apply-jobs.yml` workflow is manual-only (dry run by default); scheduled
applications run as part of the profile workflow to avoid duplicate runs.

## Skill policy

Each profile-mode run uses the planner to:

1. keeps all `core_skills`
2. removes the configured prior skills that are not part of the verified core
3. adds missing core skills
4. clamps total into `[min_total, max_total]`

Same UTC hour → same plan (safe retries).

## Important notes

- Naukri UI changes often; if a step skips, check the Action artifacts and adjust selectors in `src/naukri_client.py`.
- Automated profile updates and job applications may be subject to Naukri terms; review each workflow and keep profile claims truthful.
- Prefer session cookies over password login in CI.
- Cron is UTC. The scheduled profile and job-application workflow runs at
  09:00, 12:00, and 14:00 IST. The self-hosted runner must be online; GitHub
  can delay scheduled starts by several minutes.