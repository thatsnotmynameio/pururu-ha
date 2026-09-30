---
name: pururu
last_updated: 2026-09-30
---

# pururu Strategy

## Purpose

In Home Assistant, something you think of as one thing (the gate, the pool) is spread over devices from several integrations: a contact, a lock, a camera, an exit button; a filter pump, jets, LEDs, an energy meter. Home Assistant gives no way to make it one: users can't create devices, and areas, labels and groups gather entities without computing anything, so every derived fact (open for how long, who opened it, the pump's runtime this month) and every automation across its parts is a template, `history_stats`, `utility_meter` or automation written by hand, for each thing.

## Positioning

pururu declares the house as code: floors, areas and each thing you think of as one (a gate, a pool, a room), composed from the entities and integrations you already have, with ready-made behaviour for it. The code declares what must hold and pururu builds the rest as native Home Assistant pieces, learning or optimising only inside what the code declares, so the house is a short file a person or an agent can write, diff and review.

## Users

**Primary:** The author, building their own house on Home Assistant: a gate, a pool, a pressure pump, appliances on plugs, spread over many integrations. They're hiring pururu to build each thing, its views and automations, from a short file of code, while Home Assistant stays the place to observe and use the house.

Other Home Assistant users are not a target yet.

## Boundaries

- Never replace a device's own safety logic: the gate's interlock stays in its controller; pururu acts as a person would, pressing the open button.
- Home Assistant is where the house is observed: pururu builds entities, automations and views in it, never a panel of its own.
- Don't rebuild what an integration already does well: if Magic Areas is the best presence engine, or WashData the best program recogniser, compose it.
- Code first: no configuration UI while other users aren't a target; if one comes, whether it writes the code or keeps state of its own is open.

_Resist a change when:_ it makes something the code declares stop holding, moves observing out of Home Assistant, takes over a device's safety, or rebuilds instead of composing.

## Key metrics

- **Hand-written templates** - fewer templates and automations written by hand in the Home Assistant configuration; measurement to be defined.
- **Time to a new thing** - how long a new thing takes to be ready; measurement to be defined.

## Tracks

### Complex automations, ridiculously easy

Declare what a thing should achieve (a runtime goal with modifiers, as the pool's filtering; a sequence with interlocks and waits, as the gate's airlock) instead of writing the automation.

_Why it serves the approach:_ it's the job the author hires pururu for, and where Home Assistant's own tools are weakest.

### The behaviour catalogue

Reusable pieces any thing (or room) can use: cycles, runtime, frequency, presence, statistics, alerts, notifications, generated views.

_Why it serves the approach:_ goals and sequences are built from them; the pool's goal needs runtime and presence, the pump needs frequency.

### Inputs from anywhere

Weather forecast, rain, solar production, a WashData program, a Magic Areas presence: sources a thing reads, composed rather than rebuilt.

_Why it serves the approach:_ what a thing should do depends on things outside it; the pool's modifiers aren't in the pool.
