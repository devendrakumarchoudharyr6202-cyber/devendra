# Naukri Profile Agent (GitHub Actions)

The GitHub Actions workflows update the profile summary and upload the latest
resume to Naukri hourly between 08:00 and 20:00 India time and apply to matching
jobs using the settings in
`config/profile.yaml`. The profile configuration is for a Senior Full Stack
Developer with 6+ years of experience in Angular and C#/.NET.

## How it works

```text
GitHub cron (resume upload hourly 08:00–20:00 India time / job applications every 8 hours)
   → checkout repo
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
| `NAUKRI_EMAIL` | With password login | Naukri login email |
| `NAUKRI_PASSWORD` | With email login | Naukri password |
| `NAUKRI_STORAGE_STATE_GZ_B64` | Either this or the email/password pair | Compressed authenticated browser session; preferred for Actions secrets |
| `NAUKRI_STORAGE_STATE_B64` | Either this or the email/password pair | Base64 authenticated browser session; refresh it when expired |
| `RESUME_B64` | optional | base64 of resume.pdf if not in repo |

Add these under **Settings → Secrets and variables → Actions**. Never put
credentials or session data in workflow files or commit them to the repository.
The workflows validate that either the email/password pair or session secret is
configured before installing dependencies. If a session secret has expired,
refresh it or configure the email/password pair as a fallback.

### 3. Capture a login session (recommended)

Naukri often asks for OTP in CI. Capture cookies once on your machine:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env   # fill email/password
python scripts/capture_session.py
```

On Windows, install and authenticate GitHub CLI (`gh auth login`), then update
the session secret directly without copying or displaying it:

```bash
python scripts/set_session_secret.py
```

The script removes only Naukri's large similar-jobs recommendation caches,
compresses the remaining session, verifies it fits GitHub's secret-size limit,
and sends it to GitHub using the CLI. The workflow decompresses it at runtime.
Re-capture when the session expires (usually weeks).

### 4. Add your résumé

`assets/resume.pdf` is gitignored because it may contain personal information.
For GitHub Actions, choose one:

```bash
# Private repo: force-add
git add -f assets/resume.pdf

# Or secret (safer)
base64 -w0 assets/resume.pdf   # → RESUME_B64
```

### 5. Review `config/profile.yaml`

The profile skills, headlines, summaries, and target job titles are based on
the profile details supplied for Angular and .NET full-stack roles. Verify that
the résumé and every configured skill/profile claim are accurate before running
the workflows. Each profile run adds up to `add_per_run` missing
`core_skills` (in list order), then skills from `rotate_skills`; optional
rotating skills are removed according to `skill_policy`. Other skills are
preserved unless needed to enforce `max_total`.

### 6. Run it

- **Actions → Update Naukri Profile → Run workflow** (manual test)
- Or wait for the hourly schedule: 08:00–20:00 India time (`30 2-14 * * *` UTC)

The hourly workflow updates only the configured profile summary and uploads the
resume; it does not change the headline or key skills.

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
- Cron is UTC. Profile refresh is scheduled every 30 minutes; job applications run every 8 hours.
