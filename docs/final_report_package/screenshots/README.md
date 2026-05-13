# screenshot placeholders

Expected assets:
- `mission_control_view.png`
- `requirements_view.png`

Status:
- Existing repository includes a Mission Control visual asset: `docs/visuals/mission-control-surface.svg`.
- Live UI PNG/JPG screenshots were not present in the repository at packaging time.

Capture guidance (local run):
1. Launch stack (`docker compose up --build`).
2. Open Mission Control page and export screenshot as `mission_control_view.png`.
3. Open Requirements page and export screenshot as `requirements_view.png`.
4. Store both files in this folder.
