# Two audiences, one rebuild

`python3 scripts/narralyze.py rebuild` generates:

- `data/sessions.json` and `explorer/data.js`: complete local records.
- `site/public/explorer/`: complete private Sites source, when the Sites checkout exists.
- `build/public/`: public HTML/JavaScript, with only approved full transcripts.

`config/transcript-sharing.json` is the local approval registry. `share-transcript <lang/id>` records the SHA-256 of the exact readable text. Missing, revoked, or mismatching approvals omit the full text. Invalid approval files fail the build. `unshare-transcript` revokes permission; `list-sharing` reports `omitted`, `approved`, or `changed`. Do not approve on the owner's behalf without their explicit selection. Approval does not grant permission for recordings or alternate ASR/word-timing transcripts.

The public schema includes metrics, analysis prose, Anki practice, and proficiency evidence quotations. It excludes raw ASR structures, original filenames, audio, private history, and unapproved full transcripts. It is not a redactor for quotations or personal details inside the analyses; those remain public by design.

## Publishing both sites (owner/assistant workflow)

1. Complete analysis/rating stamping for new sessions.
2. Use the Sites skill: get the current private Site and its source write credential, preserving its audience. Open the existing `site/` checkout with the supported `site-workflow.mjs` helper before changing hosted source. Pass credentials only through hidden stdin.
3. Run `python3 scripts/publish.py --public`. This rebuilds both audiences, runs Python tests, verifies the filtered payload against the current approval registry, scans exported files for unapproved full transcripts, and pushes only allowlisted public files to the configured GitHub repository. Without `--public`, it builds and audits without pushing. GitHub Pages publishes `main` at `/`.
4. In `site/`, run `npm test`. Package and synchronize the private source with the Sites source helper (same project and opening result), using an absolute archive path and the current credential through hidden stdin. Do not manually upload the public build to the private Site.
5. Use native Sites `save_site_version` with the helper's verified project ID, commit SHA and archive, then `deploy_site_version` for the existing invitation-only/custom audience. Preserve the access policy. Poll only nonterminal deployment states. Do not declare both sites published until both deployment results succeed.
6. Verify the GitHub Pages build status and served `data.js` against `build/public/data.js`; verify the Sites deployment and unchanged private access. If one target fails, report which one succeeded and resume the other; never widen access to bypass a failure.

The private Sites publication intentionally uses the supported authenticated Sites tools rather than storing a long-lived publishing credential in the public repository or a GitHub action.

## GitHub repository and domain

The initial owner's repository is `brainheart/narralyzer`, with domain `narralyzer.everydaysystems.com`. The publish command uses `config/publishing.json`; a fork should copy `config/publishing.example.json` there and set its own destination. The `site/` checkout and its hosting manifest are owner-local, not part of the public repository. A fork can use GitHub Pages alone or create its own private Site with the Sites skill.

`.publication/github/` is a separate generated Git checkout containing only an explicit file allowlist: public HTML/data, reusable scripts/tests, methodology docs, and an empty approval template. It never inherits private Git history. Unexpected files stop publication for review. The public repository contains the tool and demonstration data; private session folders are never copied.

Configure GitHub Pages to deploy `main` from `/`. A custom subdomain uses a DNS-only CNAME to the owner's GitHub Pages host (`brainheart.github.io` for the original). Save the domain in `public_domain` to generate `CNAME`. The DNS credential stays on its existing authorized host and is not used by routine updates. Enable GitHub's HTTPS enforcement once its certificate is issued.

After approving or revoking a transcript, run the complete publication workflow again. A transcript previously published may remain in Git history, caches, and downloaded copies even after it is removed from the live site.
