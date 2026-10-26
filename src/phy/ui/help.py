"""Hover help (SPEC §9 page conventions): one dictionary, so every page explains a badge, pill
or control the same way. Written for a new user. Templates read it as `help.<key>`.
"""

HELP = {
    # top bar
    "nav": "Pages: review Cards, monitor the pipeline, inspect runs.",
    "release": "A newer Release is tagged than the one the schedule runs. Run `phy schedule update`"
    " to install it.",
    "stale": "A newer version of this paper arrived after the Card was made. If you rate it yes"
    " or partly, it is re-Read.",
    "invented": "Numbers in a value or the tl;dr that appear nowhere in the paper: likely invented."
    " The fields holding them are unsupported.",
    "supported": "Fields whose quotes were found word for word in the paper, and the value is"
    " stated in them.",
    "inferred": "The quotes were found, but the value is the agent's conclusion from them"
    " (combined, converted, or reasoned), not stated outright. Check the reasoning.",
    "unsupported": "Verify could not find a quote in the paper, or the value has a number the"
    " paper doesn't contain, so nothing backs this value. Treat it as unverified.",
    "secnav": "Jump to a section.",
    "secuns": "Unsupported fields in this section.",
    "raw": "Show the raw LaTeX instead of the rendered math and text.",
    "keys": "Show the keyboard shortcuts.",
    "timer": "Time on this Card since the page loaded; the target is about 4 minutes (amber at"
    " 4:00, red at 5:00). The server times it and saves it with your Review.",
    "fieldnav": "Move to the next or previous field.",
    # the verdict bar
    "relevance": "Is this paper relevant to your research questions? Used to measure the"
    " Filter's precision.",
    "deep_read": "Mark the paper for a full read later. The agent's suggestion is shown alongside.",
    "note": "An optional note on the whole Card, saved with your Review.",
    "save": "Save your Review (relevance, deep read, note, time) and load the next Card.",
    "saved": "Your last Review was saved.",
    "export": "Download the Card, its Flags and its Review as Markdown.",
    # fields
    "numq": "This number is in the value but not in the field's own quotes. It may come from"
    " elsewhere in the paper.",
    "nump": "This number appears nowhere in the paper: likely invented.",
    "none": "The paper has none of these. Not the same as unsupported.",
    "flag": "Flag this field: say what is wrong with it. Flags improve the prompts; Cards are"
    " never hand-edited.",
    # Flag kinds
    "wrong_value": "The value misstates the paper.",
    "quote_doesnt_support": "The quotes are real, but they do not back up the value.",
    "missing": "Something important is left out of this field.",
    "should_be_opinion": "This is the agent's judgement presented as the paper's claim.",
    "flagdel": "Remove this Flag. Flags can be removed until the Review is saved.",
    "flagkind": "In the Flag form, while the note is empty: pick the kind of Flag.",
    "flagsave": "In the Flag form: save the Flag, or cancel it.",
    "quotes": "The exact passages from the paper (raw LaTeX, rendered) that back this value.",
    "loc": "Where Verify found the quote in the paper.",
    "also": "The same text appears this many more times in the paper, so the location shown may"
    " not be the only one.",
    "notfound": "Verify did not find this quote in the paper's text (or it breaks the quote"
    " rules: 5–60 words, one paragraph, no ellipses).",
    "opinion": "The agent's own judgement, not the paper's claims. It has no quotes by design.",
    "norender": "This figure is in a format the page can't display (EPS). Open the paper to see"
    " it.",
    "nofile": "The figure's file was not found in the paper's source.",
    "caption": "The figure's caption from the source.",
    "ref": "A cross-reference or citation in the paper, shown by its LaTeX key.",
    # Verify warnings, by kind: grey chips on their sections
    "over_cap": "The agent wrote more items than the Card allows; the extra ones were dropped"
    " unchecked.",
    "no_key_results": "The Card has no key results.",
    "unknown_label": "The agent named a label that is not in the paper's source.",
    "equation_mismatch": "The equation's LaTeX is not in the body of the environment its label"
    " names.",
    "figure_label_not_figure": "The label is in the source, but not in a figure environment.",
}

# /runs and the run viewer
HELP |= {
    "runfilter": "The filter in the address bar: stage, status, ids (comma-separated arXiv ids)"
    " and since (7d, week, or a date). Edit the address to change it.",
    "runcount": "Runs matching the filter.",
    "statuspills": "Show only the runs that ended this way, keeping the rest of the filter.",
    "stage": "The Stage that ran: watch, filter, read or verify.",
    "paper": "The arXiv id the run worked on; blank for a run over many papers.",
    "paperruns": "Every run on this paper.",
    "runstatus": "How the run ended: ok, failed, skipped (no model call) or aborted (stopped"
    " before its model call).",
    "st_ok": "The run finished without an error.",
    "st_failed": "The run hit an error; the run viewer shows it. A later ok run of the same Stage"
    " and paper counts as the retry.",
    "st_skipped": "No model call was made: the paper is too long to Read. The error line says by"
    " how much.",
    "st_aborted": "No model call was made: the API account was blocked (no credit, or"
    " credentials rejected), so the Stage stopped.",
    "model": "The model the run called.",
    "prompt": "The prompt version the run used.",
    "tokens": "Input tokens (uncached, cache reads and cache writes together) / output tokens,"
    " summed over the run's calls.",
    "cost": "What the run's calls cost, from the prices in config.toml.",
    "duration": "From the run's start to its end (m:ss).",
    "started": "When the run started (UTC).",
    "openrun": "Open the run viewer: what the run sent and got back.",
    "runid": "The run's id; its full log is $PHY_HOME/runs/<id>.jsonl.",
    "runerror": "The error the run ended with.",
    "nocall": "This run made no model call, so there is no request or response to show.",
    "missinglog": "The runs row names a log file that is not on disk (deleted or moved). The"
    " row's tokens and cost still stand.",
    "settings": "The call's output token cap and effort.",
    "papertext": "The paper as sent to the model. Folded because it is long; click to open.",
    "systemprompt": "The system prompt, shared by the Stage's calls. Click to open.",
    "schema": "The JSON schema the output had to follow.",
    "stopreason": "Why the model stopped: end_turn is a finished answer; max_tokens means the"
    " output was cut off at the cap.",
    "callduration": "How long the call took.",
    "rawresponse": "The response body exactly as the API returned it.",
    "noresponse": "The API returned an error instead of a response, or could not be reached.",
    "outputerror": "The response text could not be read as JSON, usually because it was cut off.",
    "callerror": "What made this call fail: an API error, a cut-off output, or output that"
    " fails its schema.",
    "usage": "Input tokens are split into uncached, cache reads (cheap) and cache writes"
    " (dearer); cost is from the prices in config.toml.",
}

# The `?` key list of `/review`: each key with the hover text of what it does.
REVIEW_KEYS = [
    ("j / k", "fieldnav"),
    ("[ / ]", "secnav"),
    ("o", "quotes"),
    ("f", "flag"),
    ("1–4", "flagkind"),
    ("Enter / Esc", "flagsave"),
    ("y / p / n", "relevance"),
    ("d", "deep_read"),
    ("s", "save"),
    ("r", "raw"),
    ("?", "keys"),
]
