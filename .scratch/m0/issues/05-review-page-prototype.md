# Review page design

Type: prototype
Status: open
Blocked by: 04

## Question

Can a Card be reviewed in about 4 minutes on the `/review` page? Build a rough FastAPI + HTMX page from the prototype Card that shows:
- the tl;dr, results and assumptions first;
- unsupported fields shaded;
- quotes that expand;
- the Stale and invented-number badges;
- relevance, deep read, and a per-field Flag (a kind plus an optional note);
- a timer.

Settle the layout, how Flags are entered, keyboard shortcuts, and the page conventions that `/monitor` and `/runs/<id>` will reuse.
