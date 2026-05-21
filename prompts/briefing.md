Topic: {{title}}
Description: {{description}}

Period: {{cadence_window}}.

Produce a markdown digest in **briefing** format: a few paragraphs that
synthesize the period's developments on this topic. Inline-cite sources
in `[label](url)` form. Lead with the most important development. End
with a short "Also notable" bullet list (3–5 one-liners).

Skip items already covered in {{history_paths}}.

Output method: when the digest is ready, call the `write_digest` tool with the full markdown body as the `markdown_body` argument. Do not output the digest as plain assistant text; the tool call is the only way the digest gets saved.
