---
version: alpha
name: "SwiftPay Knowledge Desk"
description: "A document-first HR and operations desk with paper beige, deep red and black."
colors:
  primary: "#AE2928"
  primary-hover: "#8D211F"
  background: "#F3EBDC"
  surface: "#FAF5EC"
  sidebar: "#E7DCCB"
  ink: "#211E1B"
  muted: "#665B51"
  line: "#CDBEAA"
  scrollbar: "#8D7F6D"
typography:
  display:
    fontFamily: "Arial Narrow, Helvetica Neue, Arial, sans-serif"
  body:
    fontFamily: "Segoe UI, Arial, sans-serif"
  mono:
    fontFamily: "SFMono-Regular, Consolas, monospace"
rounded:
  DEFAULT: "12px"
  brand: "8px"
spacing:
  page-max: "1100px"
  page-inline: "3.25rem"
  section-gap: "2rem"
components:
  button: {}
  chat-message: {}
  source-list: {}
  chat-input: {}
---

# SwiftPay Knowledge Desk Design System

## Overview

A working employee knowledge desk: find a policy fact and inspect its source. The signature is a deep-red margin on cited answers, like a marked passage in a paper handbook. The user explicitly requested beige, red and black. This is a product interface, with restrained spacing and accessible controls rather than a promotional landing page.

Audience: the supplied SwiftPay India policy's employees and authorized operations users. English UI; dates and amounts are quoted from sources without reinterpretation. Laptop-first with a collapsible sidebar on narrow screens. The display face is a compact sans serif; body and utility text use local fonts to avoid network font shifts. Avoid oversized metric dashboards, gradients, dark mode, decorative icons and marketing copy in operational messages.

Runtime ownership: `ui/styles.css` owns CSS tokens. This file mirrors their exact values. `.streamlit/config.toml` is the framework theme adapter, checked by `tests/test_ui_contract.py`. All controls use Streamlit 1.49.1 primitives; see `UX-CONTRACT.md`.

## Colors

Paper background is `background`, cards use `surface`, the sidebar uses `sidebar`. `ink` carries primary text, `muted` carries helper text. `primary` identifies key actions, selected controls and cited-answer margins; errors always include explicit text and are not represented by red alone. `line` separates surfaces; `scrollbar` remains visible. Forced-colors mode defers to system colors.

## Typography

Display: 57px maximum, 39px on narrow screens, 1.06 line height, bold. Body: 16px with 1.65–1.7 line height. Utility: 11px monospaced labels, never used for the answer itself. Source filenames wrap; excerpts keep their complete original text. Citation IDs are not source-document page numbers.

## Layout

A 1100px maximum content area with natural document scrolling. The sidebar holds knowledge area, accessible source list and connection settings. Empty-state example buttons sit above the fixed framework chat input. Chat and source expanders share one visual system. At 720px, horizontal padding reduces, top padding leaves room for the framework header, and the framework collapses the sidebar. No fixed-height transcript or hidden scrollbars. Busy state keeps the composer present and disabled.

## Elevation & Depth

Flat surfaces and one-pixel borders. No ambient shadows or blur. Hierarchy comes from typography, space, and the red citation margin.

## Shapes

Twelve-pixel controls and answer surfaces; eight-pixel brand mark. Native framework selection indicators remain familiar.

## Components

Buttons: 44px minimum height, surface fill, border, visible hover and pressed states. Primary actions use deep red with light text. Disabled actions have reduced opacity and a not-allowed cursor. Keyboard focus uses a 3px red outline with offset.

Forms: Streamlit owns semantic labels, the masked token field and chat input. The input grows for text and cannot be manually resized. No client-side token persistence or token in URLs. Remote queries only run on explicit submit, with a bounded timeout; duplicate submission is disabled while pending.

Feedback: inline error or warning near the affected answer. No browser alerts. Empty results distinguish unsupported questions, missing corpus and connection problems. Source excerpts are labelled separately from generated answers. The status never claims Groq was verified before a request.

Motion: 150ms hover transitions only; disabled under reduced motion. No staged hero animation or font downloads. Framework icons accompany native controls; text labels remain on main actions.

## Do's and Don'ts

- Do keep evidence and answer visually connected.
- Do show concrete recovery steps and preserve failed questions for retry.
- Don't claim local excerpts are LLM-generated summaries.
- Don't expose hidden records or model credentials in status, URLs or logs.
