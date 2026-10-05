# Resume asset

Active file: `resume.pdf` (copied from `Swanand Nagane.pdf`).

The hourly GitHub Action re-uploads this file when
`resume.reupload_each_run` is true in `config/profile.yaml`.

**Privacy:** the PDF may contain phone/email. For CI, either:

```bash
# Option A — private repo only
git add -f assets/resume.pdf

# Option B — Actions secret (preferred for safety)
base64 -w0 assets/resume.pdf
# → paste into GitHub secret RESUME_B64
```
