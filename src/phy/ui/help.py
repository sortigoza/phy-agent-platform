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
    "runstage": "The Stage that ran: watch, filter, read or verify.",
    "runpaper": "The arXiv id the run worked on; blank for a run over many papers.",
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
    "runmodel": "The model the run called.",
    "runprompt": "The prompt version the run used.",
    "runtokens": "Input tokens (uncached, cache reads and cache writes together) / output tokens,"
    " summed over the run's calls.",
    "runcost": "What the run's calls cost, from the prices in config.toml.",
    "runduration": "From the run's start to its end (m:ss).",
    "runstarted": "When the run started (UTC).",
    "openrun": "Open the run viewer: what the run sent and got back.",
    "runid": "The run's id; its full log is $PHY_HOME/runs/<id>.jsonl.",
    "runerror": "The error the run ended with.",
    "nocall": "This run made no model call, so there is no request or response to show.",
    "missinglog": "The runs row names a log file that is not on disk (deleted or moved). The"
    " row's tokens and cost still stand.",
    "unreadable": "Lines of the run's log that are not valid JSON, usually one cut off when the"
    " process stopped mid-write. The other calls are shown.",
    "callsettings": "The call's output token cap and effort.",
    "papertext": "The paper as sent to the model. Folded because it is long; click to open.",
    "systemprompt": "The system prompt, shared by the Stage's calls. Click to open.",
    "callschema": "The JSON schema the output had to follow.",
    "stopreason": "Why the model stopped: end_turn is a finished answer; max_tokens means the"
    " output was cut off at the cap.",
    "callduration": "How long the call took.",
    "rawresponse": "The response body exactly as the API returned it.",
    "noresponse": "The API returned an error instead of a response, or could not be reached.",
    "outputerror": "The response text could not be read as JSON, usually because it was cut off.",
    "callerror": "What made this call fail: an API error, a cut-off output, or output that"
    " fails its schema.",
    "callusage": "Input tokens are split into uncached, cache reads (cheap) and cache writes"
    " (dearer); cost is from the prices in config.toml.",
}

# /monitor: `i_<key>` explains a tile, `f_<key>` a funnel step
HELP |= {
    "monitorwindow": "Tiles cover the last 7 days to now, except Filter precision (14 days),"
    " weekly spend (the ISO week from Monday 00:00 UTC) and the Golden tiles (the latest eval"
    " run).",
    "redcount": "Instruments that need action now.",
    "actions": "One line per red tile: its value, what to do, and the runs behind it. The name"
    " jumps to the tile.",
    "allgreen": "No Instrument is red. Grey tiles have nothing to compute yet.",
    "funnel": "What happened at each step in the last 7 days, with each step's share of the one"
    " before. These are activity counts, not one cohort, so a step can pass 100% (reviewing last"
    " week's Cards). A sudden narrowing points at the Stage to inspect.",
    "spark": "One bar per day for the last 7 days, today last. Grey bars are weekends, when"
    " arXiv announces nothing.",
    "eval_spark": "One bar per Golden eval run, the last 7, newest last.",
    "grey": "Nothing to compute yet, so the tile is neither green nor red. M0 needs every tile"
    " to have left grey.",
    "redrule": "When the tile turns red.",
    "runslink": "The runs behind this value, in the run list.",
    "evallink": "The Golden eval run behind this value.",
    "cardlink": "The Card with an invented number, as Markdown.",
    "skipped_too_long": "Papers whose Read was skipped because the paper is too long to send,"
    " in the last 7 days. No red rule: a few are expected.",
    "i_harvested": "New paper versions arXiv announced on the latest announcement day (Mon–Fri)"
    " the last successful Watch covered. Red at 0: Watch ran but got nothing.",
    "i_hwm_days": "Announcement days since the high-water mark last moved forward. The mark"
    " advances only when every set harvested cleanly. Red above 2.",
    "i_failures": "Stages and papers whose run failed or was aborted in the last 7 days, with no"
    " later ok run. Skipped runs don't count. Red at any.",
    "i_candidates": "Papers that passed the keyword pre-filter (or skipped it) in the last 7 days"
    " and were scored by the model. Red outside alerts.candidates_range, once Filter has run 7"
    " days.",
    "i_unsupported": "Share of Card fields Verify found unsupported, over the Cards Read in the"
    " last 7 days. Red above alerts.unsupported_rate.",
    "i_grounding": "Share of Evidence quotes found word for word on the latest Golden eval run."
    " Red below 98%; below 95% the run can't be accepted.",
    "i_invented": "Numbers that appear nowhere in the paper: on Cards of the last 7 days, and on"
    " the latest Golden eval run, where any is a hard fail. Red at any.",
    "i_golden_diff": "Material changes in the latest Dev eval run against its accepted baseline."
    " Red while there are any and the run is not accepted.",
    "i_precision": "Share of your Reviews in the last 14 days rated yes or partly: how often a"
    " Screened-in paper was worth Carding. Red below 70%, judged from 20 Reviews.",
    "i_review_time": "Median time per Review in the last 7 days, from page load to save. Red"
    " above alerts.review_minutes.",
    "i_cost_per_card": "Median over Carded papers of every run tied to the paper, retries"
    " included, in the last 7 days. Red above 2× the same median over the first Card's week.",
    "i_spend": "Spend this ISO week (from Monday 00:00 UTC) against budget.weekly_usd, the"
    " window the guardrail enforces. At 100% Read selects nothing until Monday. Red at 90%.",
    "i_minutes_per_relevant": "Review minutes in the last 7 days per paper rated yes or partly."
    " The time multiplier is relevant papers × roi.baseline_minutes ÷ Review minutes: what the"
    " platform saves over skimming each paper yourself. Red above alerts.minutes_per_relevant.",
    "i_wasted_minutes": 'Review minutes in the last 7 days on Cards rated "no": what the'
    " Filter's imprecision costs you. Red above alerts.wasted_minutes.",
    "f_harvested": "New paper versions Watch harvested.",
    "f_candidates": "Papers that passed (or skipped) the pre-filter and were scored.",
    "f_screened_in": "Candidates whose best score reached filter.threshold.",
    "f_carded": "Papers Read made a Card for.",
    "f_verified": "Cards that passed Verify.",
    "f_reviewed": "Reviews you saved.",
    "f_relevant": "Reviews rated yes or partly.",
    "f_deep_read": "Reviews marked for a deep read.",
}

# The `?` key list of `/monitor`
MONITOR_KEYS = [("[ / ]", "secnav"), ("?", "keys")]

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
