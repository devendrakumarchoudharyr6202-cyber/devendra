# Naukri Profile Agent (GitHub Actions)

Hourly GitHub Action that refreshes **Swanand Nagane**'s Naukri profile from
`Swanand Nagane.pdf` (copied to `assets/resume.pdf`):

- re-uploads resume (bumps last updated)
- rotates profile summary across safe variants (QA / Playwright / Manual Testing)
- gently adds/removes skills within configured bounds

## How it works

```text
GitHub cron (every hour)
   → checkout repo
   → Playwright (Chromium)
   → login via session cookie secret (preferred) or email/password
   → update summary + skills + resume
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
| `NAUKRI_EMAIL` | yes | Naukri login email |
| `NAUKRI_PASSWORD` | yes | Naukri password |
| `NAUKRI_STORAGE_STATE_B64` | **strongly recommended** | base64 session cookies |
| `RESUME_B64` | optional | base64 of resume.pdf if not in repo |

### 3. Capture a login session (recommended)

Naukri often asks for OTP in CI. Capture cookies once on your machine:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env   # fill email/password
python scripts/capture_session.py
base64 -w0 storage_state.json
```

Paste the base64 string into `NAUKRI_STORAGE_STATE_B64`. Re-capture when the session expires (usually weeks).

### 4. Resume (already copied)

`assets/resume.pdf` is loaded from `assets/Swanand Nagane.pdf`.

It is gitignored (PII). For GitHub Actions pick one:

```bash
# Private repo: force-add
git add -f assets/resume.pdf

# Or secret (safer)
base64 -w0 assets/resume.pdf   # → RESUME_B64
```

### 5. Edit `config/profile.yaml` (already filled from resume)

Core skills, rotate pool, and 4 summary variants are set from the resume
(Playwright BDD-Cucumber, Manual/Functional/Regression Testing, BrowserStack,
Jira/Azure DevOps, Healthcare/CRM/Banking domains…).
Tweak only if you want different emphasis.

### 6. Run it

- **Actions → Update Naukri Profile → Run workflow** (manual test)
- Or wait for the hourly cron (`0 * * * *` UTC)

Use `dry_run: true` on manual runs first to verify selectors without saving.

## Job auto-apply (every 8 hours)

```bash
HEADLESS=0 python src/main.py --mode apply
```

Rules:
1. Read your live profile skills + config skills
2. Scan Recommended + targeted searches
3. Keep jobs where **required skills match ≥ 50%**
4. Sort **latest first**
5. Apply to **all matching jobs**

GitHub Action: `.github/workflows/apply-jobs.yml` (`0 */8 * * *` UTC).
Local loop is preferred (Akamai often blocks cloud IPs).

## Skill rotation policy

Each hour the planner:

1. keeps all `core_skills`
2. removes up to `remove_per_run` non-core skills from the rotate pool
3. adds up to `add_per_run` missing rotate skills
4. clamps total into `[min_total, max_total]`

Same UTC hour → same plan (safe retries).

## Important notes

- Naukri UI changes often; if a step skips, check Action artifacts (`summary_skip.png`, `skills_skip.png`, `failure.png`) and adjust selectors in `src/naukri_client.py`.
- Automated profile bumping may conflict with Naukri terms — keep changes small and truthful.
- Prefer session cookies over password login in CI.
- Cron is UTC. For IST top-of-hour feel, cron is already hourly so timing is fine.
