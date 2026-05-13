# Demo assets

Drop the following files here before `v0.1.0` is tagged. The main `README.md`
references them by path, so any missing file just shows as a broken image.

| Filename | Content | Target size |
|---|---|---|
| `demo.gif` | 30–45s screencast: login → new agent → run now → live log | ≤ 5 MB |
| `landing.png` | Landing page hero | 1600×900, ≤ 400 KB |
| `dashboard.png` | Authenticated dashboard with 2–3 agents | 1600×900, ≤ 400 KB |
| `detail.png` | Agent detail page with Live log panel open | 1600×900, ≤ 400 KB |

## Capture tips

- macOS: Cleanshot X (Cmd+Shift+5 also works) → record mp4 → `ffmpeg -i in.mp4 -vf "fps=12,scale=820:-1" demo.gif`
- Hide all personal info: GitHub avatar / email / login can show; auth tokens cannot
- Use a clean profile in your browser (no extensions in the corner)
