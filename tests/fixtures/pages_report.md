---
markitdoc: 2
fields: {client: Nordwind AG}
date: 2025-03-04
page: {paper: a5, margins: narrow}
pages:
  default:
    header: "{section} | {title} | {client}"
    footer: " | {page} | {date}"
  front:
    numbers: roman
    header: none
  wide:
    orientation: landscape
---

::: {.cover variant=light}
kicker: For {client}
title: Valley Report
subtitle: Prepared for {client} on {date}.
:::

+++ {page=front}

## Summary

Front matter text for {client} with `{client}` kept in code.

+++ {page=default numbers=restart}

## Evidence

Body text under Evidence.

+++ {page=wide}

## Wide section

Landscape text.
