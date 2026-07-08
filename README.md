# Spec Kit Agents — Project Page (arXiv 2604.05278)

A dark-mode academic project page for the paper:

> **Spec Kit Agents: Context-Grounded Agentic Workflows**
> Pardis Taghavi, Santosh Bhavani — arXiv:2604.05278 (April 2026)

## Theme

This is the **teal sibling** of the [CAST project page](../cast-website/).

- **CAST** uses NVIDIA green `#76B900`
- **Spec Kit Agents** uses NVIDIA teal `#008564` / `#00C896`

Both stay strictly inside the [official NVIDIA palette](https://www.nvidia.com/en-us/about-nvidia/privacy/california-privacy-rights/#color):
`#76B900`, `#008564`, `#5D1682`, `#890C58`, `#FAC200`, `#5E5E5E`, `#CDCDCD`, `#FFA500`.

Dark-only by design — no theme toggle. Background `#0a0d12` (NVIDIA-build-style near-black)
with a subtle teal radial glow in the hero.

## Files

```
speckit-website/
├── index.html                  # main page (single page, ~1100 lines)
├── assets/
│   ├── spec_logo.svg           # SK monogram + wordmark
│   ├── Taghavi_Bhavani_SpecKitAgents_arXiv2604.pdf   # paper for download
│   └── figures/
│       └── fig1_workflow.png   # workflow diagram
└── static/
    ├── css/                    # Bulma + index.css overrides
    └── js/                     # FontAwesome, plugins, index.js
```

## Run

```bash
cd speckit-website
python3 -m http.server 8765
# open http://localhost:8765
```

## Deploy

Same as the CAST page — push to a repo, enable GitHub Pages from the
`main` branch root.

## Sections

1. **Hero** — SK logo, title, authors, arXiv + backbone pills, primary buttons
2. **Headline Results** — four stat cards (+0.15, p<0.05, 58.2%, 99.7–100%)
3. **TL;DR** — paragraph summary + key claim
4. **Teaser** — Figure 1 with annotated SPEC.md → PLAN.md → TASKS.md → Pull Request pipeline
5. **Overview** — context blindness, hook layer, orchestrator
6. **Method: Phase-Scoped Context-Grounding** — Discovery hooks, Validation hooks, Tool access control
7. **Experimental Setup** — 5 repositories, 4 configurations, judging protocol
8. **Main Results** — Table 1 (composite quality per repo) + Table 2 (blinded human preference)
9. **Ablations & SWE-bench Lite** — Table 3 (hook ablation), Table 4 (latency), Table 5 (SOTA comparison)
10. **Conclusion** + **BibTeX** + **Acknowledgments** + **Footer**

## Design choices

- **Teal `#008564` / `#00C896`** instead of CAST's green — distinct while staying in the official NVIDIA family
- **Dark mode only** — toggle removed; tightens the visual identity (matches the "always-on NVIDIA build" vibe)
- **NVIDIA-build-style outline pills** (`arXiv 2604.05278`, `MiniMax-M2.5 backbone`) — same component pattern as `build.nvidia.com`'s "agentic ai" / "physical ai" chips
- **Subtle hero radial glow** — a faint teal ellipse at the top of the hero, mimicking the ambient glow on `build.nvidia.com`
- **Same Inter / Inter Tight / JetBrains Mono typography stack** — proves the design system is portable
- **SK monogram** — interlocking "S" + "K" inside the three-ring motif (echoes the discovery/validation/loop structure)
- **Re-typeset all 5 tables** with Best/Second highlighting and Δ% in teal — no screenshot tables

## License

[CC BY-SA 4.0](http://creativecommons.org/licenses/by-sa/4.0/).
