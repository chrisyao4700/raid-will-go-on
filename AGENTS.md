# Working in this repository

This repository starts from the final v4 manuscript of 《下周照常开团》.

## Versioning and commits

- Edit the existing files and record changes with Git. Do not create new `prod-00x` directories, duplicate version folders, or a new full-workspace snapshot for routine revisions.
- Commit completed, verified changes in this repository. Do not assume authorization to merge reviews or force-push shared history.
- The initial `main` commit and `v4` tag preserve the imported baseline. Never rewrite that published baseline.
- For each repository change and each CR/PR, keep exactly one unmerged commit ahead of the latest target branch.
- Fetch the target branch before creating or updating a review. Rebase onto its latest state when needed.
- Amend the existing change commit for fixes and review revisions; do not accumulate additional commits for the same review.
- Use the current target branch as the review base. Do not add already-landed commits to expand a review diff.
- Before uploading a review, verify one commit ahead and zero commits behind the target.
- Preserve unrelated work and already-landed/shared history. Squash only commits belonging to the current change; isolate the change if unrelated commits are present.
- With the default target `origin/main`, an unmerged change should show `0 1` from `git rev-list --left-right --count origin/main...HEAD`. A synchronized published baseline naturally shows `0 0`.

## Manuscript sources

- Edit `正文/`, not the generated complete manuscript.
- Maintain ordering and chapter titles in `章节清单.json`.
- Read `设定/创作约定.md`, `设定/人物.md`, and `设定/文风.md` before substantive writing.
- Preserve the established narrator, facts, diary boundaries, and knowledge available to 绯月 at each point. The user's newer instructions override older editorial choices.
- When changing diary scenes, update `设定/日记场景表.json` and `设定/日记场景与时间.md`.
- Do not print diary labels, scene titles, or introductory date/location captions in the manuscript. Keep chapter headings and scene breaks; reveal setting through environment, objects, dialogue, and warranted narrator guesses.
- Scene `title`, `kind`, and `event_time` in the JSON are editor-only references. Use `sequence_in_chapter` and the recorded opening/closing to identify untitled scenes; never reinsert the labels as a parsing shortcut.
- Scene IDs stay stable when scenes move. Use the chapter manifest and `sequence_in_chapter` (or the explicit `reading_order`) for reading order; sorting scene IDs would undo the nonlinear structure.
- Regenerate and verify before committing:

  ```sh
  python3 工具/合稿.py
  python3 工具/合稿.py --check
  ```

- Keep Markdown links portable and relative to the containing document. Do not embed machine-specific absolute paths in tracked files.
- Treat `编辑记录/v4基线校验.json` as a historical import record, not a requirement that future chapter contents remain unchanged.

## Local archive

- `archive/legacy/` contains the preserved pre-Git workspace and is intentionally ignored.
- Do not modify, delete, force-add, or publish that archive unless the user asks.
- Do not use historical reconstruction scripts to overwrite the current manuscript.
- Keep transient output under the ignored `.cache/` directory.
