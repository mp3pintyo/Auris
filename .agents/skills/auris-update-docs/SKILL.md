---
name: auris-update-docs
description: Review Auris product changes, keep the built-in Hungarian documentation accurate, and complete versioned GitHub releases. Use after Auris feature, workflow, UI, setting, import, speaker-assignment, playback, export, model, performance, documentation, or operational changes, and whenever completed Auris work is being pushed or handed off.
---

# Auris documentation and release completion

## Project completion rule

In `D:\AI\Auris`, a completed change that is pushed to the repository must also become a versioned GitHub Release. A plain commit or push is incomplete unless the user explicitly asks to omit the release.

Treat a request to push or publish completed Auris work as authorization to run the full release flow. Do not stop after pushing `main` or the version tag. Wait for the release workflow and verify that the public GitHub Release exists.

## Workflow

1. Inspect the current change set and `D:\AI\Auris\reader\templates\docs.html`.
2. Decide whether the change affects user-visible behavior or operation.
3. Update `docs.html` when needed; otherwise record a concise reason why no documentation change is necessary.
4. Add the change to the bilingual `CHANGELOG.md` `Unreleased` section.
5. Choose the semantic-version impact according to `RELEASING.md` and prepare the release with `scripts/release.py`.
6. Run all checks required by `RELEASING.md`, including local Playwright verification for visible UI changes.
7. Commit the release files, create the annotated `vX.Y.Z` tag, and push both `main` and the tag.
8. Wait for `.github/workflows/release.yml` to finish successfully and verify the published release with `gh release view vX.Y.Z`.

## Documentation impact checklist

Check for changes to:

- capabilities and limitations;
- import or setup steps;
- UI labels, controls, modes, defaults, and prerequisites;
- background processing and status messages;
- speaker, voice, playback, cache, or export behavior;
- failure states and troubleshooting;
- keyboard shortcuts, performance guidance, and licensing.

Internal refactors, tests, and bug fixes that do not change observable behavior normally need no documentation edit.

## Editing rules

- Keep the page in Hungarian, while retaining literal English UI labels where they help users find controls.
- Preserve the existing information architecture, components, CSS classes, and visual style.
- Describe only implemented behavior; do not document plans as finished features.
- Reconcile stale or contradictory passages instead of only appending new text.
- Explain both the normal workflow and the most likely corrective workflow.
- Keep model-specific claims, measured values, and licensing statements unchanged unless the implementation or authoritative source changed.

## Verification

- Run the relevant Auris tests with the project virtual environment.
- For visible layout changes, use local Playwright as required by the project instructions.
- Check that every new table-of-contents link resolves to a unique section ID.
- Run `scripts/release.py check --tag vX.Y.Z` before tagging.
- Confirm the release workflow succeeded and the public GitHub Release URL resolves.
- In the final handoff, state the version, tag, release URL, checks run, and whether `reader/templates/docs.html` was updated or why it did not need changes.

If any required check or release step fails, fix it before declaring completion. If an external blocker prevents publishing, report the exact failed step and leave the work explicitly incomplete.
