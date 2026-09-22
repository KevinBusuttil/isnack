# Batch Explorer: save the exploration to PDF

The Batch Explorer (`/app/batch-explorer/<batch>`) has a **Save as PDF** button
next to *Expand all* / *Collapse all*. It prints the exploration of the batch
currently loaded — the summary card and the whole tree, every group open — so an
auditor can file or send the trace of a lot without screenshotting it branch by
branch.

The button is enabled once a batch has been explored and has at least one
transaction, the same rule as the expand/collapse buttons.

## What reaches the paper

```
Batch Explorer · AAO-007                                 Isnack Ltd
FG10005 · Corn Puffs 30g              Generated 22/09/2026 14:32 by K. Busuttil
────────────────────────────────────────────────────────────────────────────────
[ summary card: batch qty, manufactured, expiry, transactions, document types ]

Batch · AAO-007
├─ Work Order [2] ───────────────────────────── every group expanded, always
│  ├─ MFG-WO-2026-00027 …
│  │  ├─ Materials consumed [4] ─────────────── nested groups expanded too
│  │  ├─ Work Order stock entries [6]
│  │  └─ Not effective [1]
…
```

* **Everything is expanded.** The printed copy is built from the data, not from
  the tree on screen, so it never matters what the user had collapsed. The
  nested production-input groups, which start collapsed on screen, are open on
  paper.
* **Nothing is filtered out.** The search box is a screen-only lens; the PDF is
  the complete exploration of the batch. The box itself is not printed.
* **Deferred Work Orders are loaded first.** A batch produced by more than
  `MAX_EAGER_INPUT_WOS` (10) Work Orders leaves the rest behind a *Load
  production inputs* button. Before printing, the page re-reads the exploration
  with `get_batch_usage(batch_no, eager_inputs=1)`, which ignores that cap, so
  no Work Order goes to paper unexpanded. If that read fails the PDF is still
  produced and says, under each Work Order it could not load, that its
  production inputs are missing.
* **The page is left as it was.** The printed copy is a separate off-screen
  document; the filter, the scroll position and whatever the user had collapsed
  survive the print untouched.
* **The links survive.** Document names keep their `/app/…` hrefs, so in the
  saved PDF they are still clickable back into the desk, the nested batches
  included (they open the Batch Explorer for that batch).

## How the PDF is made

The browser makes it: the page renders the copy, calls `window.print()`, and the
user picks *Save as PDF* (or a printer) in the print dialog. Nothing is rendered
server-side, which is what keeps the colours — wkhtmltopdf, the PDF engine
behind Frappe's print formats, understands neither the CSS custom properties nor
the flexbox this page is built on.

Consequences worth knowing:

* The per-doctype accent colours (purple Work Order, teal Delivery Note, green
  Sales Invoice …), the status pills, the quantity chips and the tags all print,
  including their backgrounds: the print stylesheet sets `print-color-adjust:
  exact`, which overrides the browser's "Background graphics" setting.
* **Surfaces are forced light.** The print block re-declares the surface
  variables (`--card-bg`, `--text-color`, `--border-color` …) with light values,
  so a desk in dark theme still prints black on white. Only the surfaces change;
  the accent colours are inline on the nodes and are printed as they are.
* Page breaks avoid splitting a summary card, a group header or a leaf row, and
  a group header is kept with the rows under it.
* The document title is set to `Batch Explorer - <batch>` for the duration of
  the print, so that is the filename the browser offers.

## Code

* `isnack/isnack/page/batch_explorer/batch_explorer.js`: `save_pdf` (button
  handler), `full_data` (the eager re-read), `print_document` (builds the
  off-screen copy, prints it, cleans up) and `print_header_html`. `build_tree`
  and the `render_*` methods take an `opts.print` flag that leaves groups open
  and drops the click handlers and the *Load production inputs* button.
* `isnack/isnack/page/batch_explorer/batch_explorer.css`: the `.be-print-doc`
  rules and the `@media print` block.
* `isnack/isnack/page/batch_explorer/batch_explorer.py`: `eager_inputs` on
  `get_batch_usage`, `eager_all` on `_attach_production_inputs`.
* Tests: `isnack/isnack/page/batch_explorer/test_batch_explorer.py`
  (`TestGetBatchUsageEagerInputs`, `TestAttachProductionInputs`).
