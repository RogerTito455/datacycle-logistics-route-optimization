# 008 · Delivery notes

- **Generates:** [`services/generator/seed/delivery_notes.json`](../services/generator/seed/delivery_notes.json)
- **Validated by:** [`services/generator/validate_seeds.py`](../services/generator/validate_seeds.py) against [`delivery_notes.schema.json`](../services/generator/seed/delivery_notes.schema.json)
- **Used by:** `make load-reference`, which loads it into `bronze.delivery_notes`, and `make generate`, which attaches a note to about a third of each day's orders ([generator](../services/generator/README.md#delivery-notes))
- **Model:** Claude Opus 5.5 (`claude-opus-5-5`)
- **How it was run:** as the only message of a fresh conversation with no prior context, in an
  agent session that could run shell commands. The model was told not to browse.
- **Date:** 2026-09-28
- **Version:** 1

## Why this prompt looks the way it does

- **A corpus to draw from, not a note per order.** The generator writes thousands of orders a
  week and about a third carry a note. A fixed corpus of 300 notes can be read and checked in
  full, and drawing from it keeps every generated day reproducible. The prompt tells the model how
  the notes will be used, so it writes notes that stand on their own, without an order to refer to.
- **The notes are the project's unstructured text.** Phase 2 needs a real example of unstructured
  data (issue #25). The prompt asks for what makes text unstructured in practice: several
  languages in the proportions people in Barcelona write them, phone typing with abbreviations,
  lower case and typos, one-word notes next to three-sentence ones, and instructions that
  contradict each other.
- **Barcelona, not a generic city.** The situations are named one by one (porteria hours, fincas
  without a lift, 22@ loading docks, market stalls, holiday flats, gated developments in the upper
  districts, confusing street numbers), so the corpus reads like the notes a driver in this city
  gets.
- **No personal data.** No phone numbers, e-mail addresses, identity documents, full names or real
  businesses: a neighbour is a floor and a door. The validator searches every note for phone
  numbers, e-mail addresses and DNI or NIE numbers.
- **Structured labels on unstructured text.** Each note carries its language, one category and two
  yes-or-no labels. The text stays unstructured; the labels are what a program can filter and
  count. The generator uses the category to give business recipients business-like notes, and the
  simulator (issue #7) can use the two labels.
- **The output shape is fixed.** The JSON skeleton maps to the columns of `bronze.delivery_notes`,
  and `delivery_notes.schema.json` rejects anything that drifts from it.

## Prompt

```text
You are generating seed data for a university data-engineering project that simulates a fictional last-mile parcel carrier, Llobregat Express, which delivers parcels across Barcelona and the neighbouring towns of the lower Llobregat. Use only your own knowledge; do not browse the web.

Produce a corpus of 300 delivery notes: the free-text instructions that recipients type in the "notes for the driver" box when they buy online. A program will attach one of them, at random, to about a third of the orders. They are the project's example of unstructured text data.

Realism requirements:
- Languages as people in Barcelona actually write them: about 50% Spanish, 30% Catalan, 15% English and 5% other languages or mixed (a Spanish note with a Catalan street word, a short note in French or Italian from a visitor).
- Written like real people type on a phone: short, sometimes all lower case, abbreviations ("x fa", "porfa", "pls", "2º 1ª", "esc. B"), occasional typos, occasional capitals for emphasis. Some are one word, a few are two or three sentences.
- Cover the real situations of Barcelona deliveries: intercoms that do not work, finca without a lift, "porteria" or concierge hours, leaving the parcel with a named neighbour's door (use floor and door, never a real person's full name), shops and bars that open late, offices with reception hours, 22@ buildings with a loading dock, dogs, babies sleeping, working night shifts, "call before" (without any phone number), access through a garage or a passage, ground-floor shops, markets, gated developments in the upper districts, holiday flats, "no deixeu el paquet al replà", fragile content, medicines, cash on delivery not accepted, wrong or confusing street numbering, and instructions that contradict each other.
- No real personal data: no phone numbers, no email addresses, no identity documents, no full names of people, no real business names. Street names may be generic ("the bakery on the corner") rather than exact addresses.
- Each note is labelled for later analysis: its language, one main category, and whether it is likely to make the stop longer or make a failed delivery more likely.

Return only the JSON document, with no commentary and no code fences, following exactly this structure. Angle brackets describe the expected type; replace them with values.

{
  "schema_version": 1,
  "generated_for": "Llobregat Express delivery notes corpus",
  "notes": [
    {
      "note_id": "N-001",
      "text": <string>,
      "language": "es" | "ca" | "en" | "fr" | "it" | "mixed",
      "category": "access" | "schedule" | "neighbour or concierge" | "business hours" | "call before" | "pets or children" | "fragile or special handling" | "location hint" | "contradictory" | "other",
      "likely_longer_stop": <boolean>,
      "likely_failed_attempt": <boolean>
    }
  ]
}
```

## Post-processing

**No hand edits.** `delivery_notes.json` is the model's answer byte for byte, plus a final
newline. The answer was a single JSON document with no commentary and no code fences, as the
prompt asked.

**How the model worked.** It did not browse. It made 3 shell calls, and it wrote a draft file and
read it back before answering.

**Validation on 2026-09-29** with `make validate-seeds`: 0 errors and 0 warnings in the 13 checks
of the delivery notes.

| Layer | Checks | Result |
|---|---|---|
| Structure | Every field and type against `delivery_notes.schema.json`: ids `N-NNN`, one of the six languages and ten categories of the prompt, both labels true or false | pass |
| Against the prompt | 300 notes; unique ids and unique texts; no phone numbers, e-mail addresses, DNI or NIE numbers; languages es 150, ca 90, en 45, mixed 7, fr 4 and it 4, which is 50 / 30 / 15 / 5% against "about 50% / 30% / 15% / 5%"; all ten categories used, from 14 `contradictory` to 54 `access`; 146 notes labelled a likely longer stop and 84 a likely failed attempt, so both labels take both values | pass |
| Against the generator's rules | The eight places the generator looks for are each named by at least one note and lie in a zone of `company.json`, or outside the service area (Sant Joan Despí); every zone has business and consumer notes to draw from | pass |

The texts run from 1 character (`.`) to 136, with a median of 50.

**What the checks cannot see.** A full name or a real business name has no pattern to search for,
so the 300 notes were read in full. Neighbours appear as a floor and a door ("la veïna del 2n 2a",
"the neighbour on 2nd floor door 1") or a relation ("mi madre vive en el 1º 2ª"), shops by their
trade ("la frutería", "el estanco", "the cafe downstairs"), and no note names a person or a real
business. One note mentions an identity document without a number ("enseñaré el DNI si hace
falta"), which is what a recipient would write.

**How the generator uses it.** The rules are the generator's own, not the model's, and are listed
in the [generator README](../services/generator/README.md#delivery-notes). A third of the orders
carry a note. The prompt gives no label for the kind of recipient, and the category is too coarse
to stand in for one: 15 of the 39 location hints describe a home (N-288 "entresuelo 1ª, en el
telefonillo pone ENTLO", N-211 "casa blanca amb persianes verdes"), and three `access` notes are
about the loading dock of a 22@ office. So the generator reads who could have written a note from
its text: 32 notes are a business's, 137 a home's and 131 anyone's. Business recipients draw 80% of
theirs from the business notes and the rest from the neutral ones, consumers from the home and
neutral notes. The languages keep the corpus mix as closely as those groups allow, which is
exactly: the neutral notes a business recipient gets make up for the French, Italian and mixed
notes the business notes lack. A note that names a place goes only to orders of that zone, and
N-033 names Sant Joan Despí, a town outside the service area, so it is never attached.

What that gives on the two dates loaded on 29 September 2026: on Monday 28 September, 1,119 of the
3,363 orders carry a note, 50.5% in Spanish, 28.6% in Catalan, 16.0% in English, 1.4% in French,
1.5% in Italian and 2.0% mixed, against 50 / 30 / 15 / 1.3 / 1.3 / 2.3% in the corpus; 179 of the
225 business recipients' notes (79.6%) are a business's and none a home's, and 51 of the 99
location hints consumers get describe a home. On Saturday 26 September, 301 of 923 orders carry a
note, 53.5 / 26.9 / 16.3 / 1.7 / 0.7 / 1.0%, with only 31 business notes, 28 of them a business's.
The shares vary around the corpus's with the draw, most on a day with few notes.

## History

- v1 · 2026-09-28 · initial
