Topic: {{title}}
Description: {{description}}

Period: {{cadence_window}}.

Produce a markdown digest in **sectioned** format:
- First, "Top stories": 3–5 items, each with its own heading and a paragraph.
- Then, "Everything else": a flat bullet list of remaining items as one-liners.

Each item should link to its primary source. Skip items already covered in {{history_paths}}.

Output method: when the digest is ready, call the `write_digest` tool with the full markdown body as the `markdown_body` argument. Do not output the digest as plain assistant text; the tool call is the only way the digest gets saved.
