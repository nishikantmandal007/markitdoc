---
markitdoc: 2
use: [fieldnote, nordwind]          # style files, applied in order (nordwind is a brand pack)
palette: forest
paper: a4
lang: en
fields: {client: Nordwind AG, project: Valley Restoration}
refs: refs.yml
toc: true
---

::: {.cover variant=split image="images/valley.jpg"}
kicker: Field note 7
title: What the Valley Taught Us
subtitle: Five years of wetland restoration, prepared for {client}.
:::

+++ {page=front}

## Summary

Flood days fell by **two thirds** and the [riparian buffer]{.term} tripled in five years.
The trend is in [@area]; the cost per hectare is in [@costs]. The method follows
[@dewit2021] and was reviewed by the regional water board.

::: {.callout kind=key}
**68%** fewer flood days in the four towns downstream.
:::

+++ {page=default numbers=restart}

## Evidence {#evidence}

::: columns {ratio=2:1}
Restoration began upstream, where a hectare of marsh holds back roughly
9 000 m^3^ of storm water. *Feuchtgebiet*{lang=de} is the term used in the original
surveys. {align=justify}

![Gauge station at Alder](images/gauge.jpg){#gauge width=1/1 caption="Gauge station at Alder, 2024"}

::: {.aside title="Method"}
Gauge data, 2021–2025, four towns. Rainfall normalised to the 30-year mean.
:::
:::

```chart {#area caption="Wetland area, hectares"}
{"type": "bar", "labels": ["2021", "2023", "2025"], "values": [120, 260, 410]}
```

The river does the work; we only stopped preventing it.
{.pull}

## A note on design {#design}

This paragraph uses the full-control level: one phrase is set in
[Playfair Display at 14 pt in the brand green]{font=display size=14pt color=brand},
then the text returns to the house style. Humans may use raw keys anywhere; the AI guide
teaches named styles first.

::: box {border="0.5pt accent" padding=m radius=s bg=surface align=center}
A bordered text box, centred, with any markdown inside it.
:::

+++ {page=wide}

Table: Cost per restored hectare {#costs}

| Town  | Hectares | Cost (EUR k) | Per ha |
|:------|---------:|-------------:|-------:|
| Alder |      140 |          910 |    6.5 |
| Brook |      270 |        1 480 |    5.5 |
{.striped header=repeat}

+++ {page=default}

## Next steps

As [@evidence] shows and [@gauge] illustrates, the method transfers. Storage scales as
$V = A \cdot \bar{d}$, so depth matters as much as area.[^depth]

$$ V_{\text{total}} = \sum_{i=1}^{n} A_i \, \bar{d}_i $$ {#storage}

Equation [@storage] gives the total for the {project}.

[^depth]: Mean depth from the 2025 survey.
