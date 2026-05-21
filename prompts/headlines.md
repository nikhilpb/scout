Topic: {{title}}
Description: {{description}}

Period: {{cadence_window}}.

Produce a markdown digest in **headline** format: a flat list where each item is:
- A bolded headline (≤90 chars).
- One or two sentences summarizing the item.
- A bare source link at the end.

Order by importance, not chronology. Skip items already covered in {{history_paths}}.

Output method: when the digest is ready, call the `write_digest` tool with the full markdown body as the `markdown_body` argument. Do not output the digest as plain assistant text; the tool call is the only way the digest gets saved.
