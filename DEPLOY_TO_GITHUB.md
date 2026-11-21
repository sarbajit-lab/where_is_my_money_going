# Putting WIMMG on GitHub

Your **database entries must never go online**. Everything below is safe to upload because it is code and docs
only; the personal files are excluded by `.gitignore`.

## Upload these
```
.github/            (test + release workflows)
backend/  frontend/  tests/  tools/  vendor/  docs/
run.py  start.sh  requirements.txt  VERSION
README.md  CHANGELOG.md  RELEASE_NOTES.md  SECURITY.md  LICENSE
DEPLOY_TO_GITHUB.md  .gitignore
data/.gitkeep  backups/.gitkeep
```

## Never upload
| Item | Why |
|---|---|
| `data/` contents (`wimmg.db`, `secret.key`, `FIRST_LOGIN.txt`) | your entries, encryption key and first password |
| `backups/` contents | copies of your database |
| `demo-data/`, `exports/` | generated data |
| Your own Excel/CSV dumps (`*.xlsx`, `*.csv`, `*.tsv`) | your real transactions |

The original Kanakku Pusthakam zip you uploaded contained a real `expenses.db`, a `secret.key`, a backup
and a `.git` folder pointing to the original author's repository. None of these are in this package. If you copy
anything from that old folder, do not bring them along.

## Steps
```bash
cd wimmg
git init -b main
git add .
git status          # check: no .db, .xlsx, .csv, secret.key or FIRST_LOGIN.txt in the list
git commit -m "WIMMG 1.0.0"
git remote add origin https://github.com/<your-username>/wimmg.git
git push -u origin main
```
Then on GitHub: Releases > Draft a new release > tag `v1.0.0`, paste the text from `RELEASE_NOTES.md`. (The release
workflow does this for you when you push a tag: `git tag v1.0.0 && git push origin v1.0.0`.)

Keep your real data on your own machine and back it up from Settings > Backup & export.
