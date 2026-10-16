# Naukri Profile Agent (GitHub Actions)

The profile workflow updates the profile summary and uploads the latest resume
hourly between 08:00 and 20:00 India time on a self-hosted Windows runner.
The separate GitHub Actions workflow applies to matching jobs using the settings in
`config/profile.yaml`.

## How it works

```text
GitHub cron (profile update hourly 08:00–20:00 India time / job applications every 8 hours)
   → checkout repo
   → self-hosted Windows runner for profile updates / hosted runner for job applications
   → Playwright (Chromium)
   → login via session cookie secret (preferred) or email/password
   → update the configured summary and upload the resume during the hourly workflow
   → upload screenshots as artifacts
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
| `NAUKRI_EMAIL` | Optional fallback | Naukri login email; headless Actions cannot complete OTP or captcha |
| `NAUKRI_PASSWORD` | Optional fallback | Naukri password; headless Actions cannot complete OTP or captcha |
| `NAUKRI_STORAGE_STATE_GZ_B64` | Recommended for OTP login | Compressed authenticated browser session; preferred for Actions secrets |
| `NAUKRI_STORAGE_STATE_B64` | Alternative | Base64 authenticated browser session; refresh it when expired |
| `RESUME_B64` | optional | base64 of resume.pdf if not in repo |

Add these under **Settings → Secrets and variables → Actions**. Never put
credentials or session data in workflow files or commit them to the repository.
For OTP/captcha login, the GitHub Actions workflows require a captured session
secret and stop immediately if it is missing. Email/password credentials alone
cannot complete OTP or captcha on the headless runner.

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

Scheduled profile updates only run while this PC is awake and the runner is
online. The Apply Naukri Jobs workflow still uses GitHub-hosted runners.

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

The configured `core_skills` list reflects the supplied Python, data analysis,
visualization, Excel, and web skills. Headlines, summaries, and target job
titles are separate settings; verify that they, the résumé, and every other
configured profile claim are accurate before running the workflows. Each
profile run adds up to `add_per_run` missing
`core_skills` (in list order), then skills from `rotate_skills`; optional
rotating skills are removed according to `skill_policy`. Other skills are
preserved unless needed to enforce `max_total`.

### 7. Run it

- **Actions → Update Naukri Profile → Run workflow** (manual test)
- Or wait for the hourly GitHub schedule: 08:00–20:00 India time, with a retry
  15 minutes later if no active or successful run exists in that IST hour.

The hourly workflow removes the opening "Full Stack Developer" phrase from the
configured profile summary, verifies that removal, adds the phrase back, and
uploads the resume; it does not change the headline or key skills. Scheduled
runs happen automatically and do not require a prompt. Automatic updates use
GitHub's `schedule` event; **Run workflow** and explicit `gh workflow run`
commands create `workflow_dispatch` events and appear as manually started.

## Job auto-apply (every 8 hours)

```bash
HEADLESS=0 python src/main.py --mode apply
```

Rules:
1. Read your live profile skills + config skills
2. Scan Recommended + targeted searches
3. Keep jobs where **required skills match ≥ 60%**
4. Sort **latest first**
5. Apply to up to the configured `max_apply_per_run` matching jobs

GitHub Action: `.github/workflows/apply-jobs.yml` (`0 */8 * * *` UTC).
Local loop is preferred (Akamai often blocks cloud IPs).

## Skill rotation policy

Each profile-mode run uses the planner to:

1. keeps all `core_skills`
2. removes up to `remove_per_run` non-core skills from the rotate pool
3. adds up to `add_per_run` missing rotate skills
4. clamps total into `[min_total, max_total]`

Same UTC hour → same plan (safe retries).

## Important notes

- Naukri UI changes often; if a step skips, check Action artifacts (`summary_skip.png`, `skills_skip.png`, `failure.png`) and adjust selectors in `src/naukri_client.py`.
- Automated profile updates and job applications may be subject to Naukri terms; review each workflow and keep profile claims truthful.
- Prefer session cookies over password login in CI.
- Cron is UTC. The profile workflow runs hourly from 08:00 through 20:00 India time; job applications run every 8 hours.