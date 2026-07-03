---
name: adflow-canvas
description: >-
  Open the AdFlow workflow canvas as a visual interactive UI in the Hermes
  browser preview — NOT as a text table. Use when the user asks to see/show/open
  the canvas, workflow graph, node board, or production pipeline visually.
metadata:
  hermes:
    tags: [adflow, canvas, workflow, ui]
    related_skills: [adflow-workflow]
---

# AdFlow — visual workflow canvas in Hermes

When the user wants to **see the canvas** (画布 / workflow board / node graph):

## DO

1. Call MCP `show_workflow_canvas` (optional `batch_id`).
2. Read `preview_url` from the result — it is always `/hermes/canvas`, never `/`.
3. **Immediately** call `browser_navigate(preview_url)` so the user gets the
   interactive UI in the Hermes browser preview panel.
4. Optionally `browser_screenshot` to confirm it loaded.
5. Tell the user: drag nodes, scroll to zoom, drag empty area to pan, click a
   node for details in the right panel.

## DO NOT

- Do NOT summarize nodes as a markdown table in chat.
- Do NOT open `https://adflow.vidau.info/` (home page with Copilot).
- Do NOT describe the canvas in prose when the browser can show it.

## URLs

- Test: `https://adflow.vidau.info/hermes/canvas`
- With batch: `https://adflow.vidau.info/hermes/canvas?batch_id=B...`

## If canvas is empty

Remote may have no batches yet. Run `create_batch` + generation first, then
refresh the canvas URL.
