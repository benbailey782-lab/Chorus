# Chapter Attribution Prompt

You are segmenting a single chapter of a book for audiobook production. Your output feeds directly into a text-to-speech pipeline that generates one audio segment per array element. The accuracy of your speaker attribution and render-mode tagging directly determines whether the audiobook sounds correct.

## Your Task

Take the provided chapter text and cast list. Produce an ordered JSON array where each element represents ONE audio segment. Every word of the input chapter must appear in exactly one segment, in original order. The concatenation of all `text` fields (with natural spaces/newlines restored) should reconstruct the original chapter content.

## Output Schema

```json
{
  "order": integer (sequential, starting from 1),
  "character": "string - MUST match a name from the cast list OR 'Narrator'",
  "text": "string - the literal text to be spoken, including quotation marks for dialogue",
  "render_mode": "prose" | "dialogue" | "epigraph" | "letter" | "poetry" | "song_lyrics" | "emphasis" | "thought" | "chapter_heading",
  "emotion_tags": ["string", ...],
  "confidence": integer 0-100,
  "notes": "string or null - optional, flag unusual cases for review"
}
```

## Render Mode Reference

| Mode | When to use |
|---|---|
| `prose` | Default for narration: description, action, setting, third-person narrative |
| `dialogue` | A character speaking aloud. Text INCLUDES the quotation marks |
| `epigraph` | Italicized quotation at chapter start (a quote from another work) |
| `letter` | Text presented as a written letter, message, note, or document embedded in prose |
| `poetry` | Verse with line breaks and rhythm |
| `song_lyrics` | Text identified as a song or ballad (often italicized or titled) |
| `emphasis` | Short italicized phrase within prose for emphasis (NOT a whole block) |
| `thought` | First-person internal monologue, usually italicized |
| `chapter_heading` | The chapter title or number, if present at the top of the input |

## Emotion Tag Vocabulary

Use ONLY these tags. They map to paralinguistic tokens the TTS engine can render inline.

**Paralinguistic (audible sounds):**
- `laugh` — character laughs
- `chuckle` — softer laugh
- `gasp` — sharp intake of breath
- `cough` — coughing
- `sigh` — audible exhale
- `groan` — grunt of pain or displeasure
- `sniff` — sniffling (tears, cold, disdain)
- `shush` — "shh" sound
- `clear_throat` — throat clearing

**Prosody hints (how it's delivered):**
- `whispered`
- `shouted`
- `urgent`
- `fearful`
- `angry`
- `tender`
- `cold`
- `amused`

Apply tags ONLY when strongly supported by an attribution verb or unambiguous context. Empty array `[]` when in doubt.

## Attribution Rules

### Core
1. **Return ONLY valid JSON.** No preamble, no markdown code fences, no commentary.
2. **Every `character` must match the cast list exactly** (canonical name) or be `"Narrator"`. Do NOT invent characters. Do NOT use aliases — resolve to canonical.
3. **Default to Narrator for prose.** Anything not quoted dialogue or an explicit special mode is narrator text.
4. **Preserve text exactly.** Do not paraphrase, summarize, correct spelling, or "clean up" unusual formatting. Include quotation marks in dialogue text.

### Splitting paragraphs

5. **Split at dialogue boundaries.** A paragraph that mixes narration and dialogue becomes multiple segments:
   > He nodded. "I know," he said, "but we must go anyway." The fire crackled.
   
   Becomes:
   - Narrator: `He nodded.`
   - Character: `"I know,"`
   - Narrator: `he said,`
   - Character: `"but we must go anyway."`
   - Narrator: `The fire crackled.`

6. **Preserve paragraph breaks as separate segments.** Multi-paragraph narration becomes multiple narrator segments so natural pauses can be inserted in assembly.

7. **Action beats within dialogue get their own segments.**
   > "I don't know," he said, rubbing his temples, "we'll see."
   
   Becomes three segments: character, narrator, character.

### Attribution logic

8. **Explicit attribution first.** "said X," "X replied," "X whispered" — these are unambiguous. Confidence 90–100.
9. **Use proximity for unattributed lines.** If a line has no attribution tag but sits between two lines of the same other character in a two-person scene, it is almost certainly the OTHER character. Confidence 75–90 depending on scene clarity.
10. **Watch for alternating dialogue.** In a scene with exactly two named speakers, alternation is a strong signal.
11. **Do not guess wildly.** If a line has no clear speaker and multiple characters could plausibly say it, assign to `"Narrator"` with confidence ≤ 60 and add a note.

### Confidence scoring

- **95–100:** Explicit attribution tag or unambiguous single-speaker context
- **80–94:** Strong contextual inference (alternating two-person scene, character's distinctive voice/topic)
- **60–79:** Plausible but uncertain — review recommended
- **Below 60:** Use `"Narrator"` with a note explaining the ambiguity

### Emotion tags

12. **Only from explicit textual cues.** "He sighed, 'So be it.'" → `["sigh"]` on that dialogue segment. A character being sad in general context does NOT justify a tag.
13. **Verb-derived tags go on the DIALOGUE segment**, not on the adjacent prose beat. The TTS engine renders `[sigh]` as part of the character's delivery.
14. **Multiple tags are allowed but rare.** `["whispered", "fearful"]` is fine when both are textually supported.
15. **Tags derived from preceding narration** (e.g., "Ned sighed and shook his head. 'And she is also your lady.'") can be applied to the dialogue that follows, when the narration clearly describes the manner of that dialogue.

### Special content detection

16. **Epigraphs:** Italicized block(s) before the first prose paragraph of a chapter, usually quoting another work. `render_mode: "epigraph"`, character: `"Narrator"`.
17. **Letters:** Text presented as a written letter, message, note, or document. Usually introduced by phrases like "the letter read," "she unfolded the parchment," or a visually set-apart block. `render_mode: "letter"`. Character: the letter's author if named in the cast; otherwise `"Narrator"` with a note.
18. **Poetry/songs:** Multi-line verse. `render_mode: "poetry"` for non-song verse, `"song_lyrics"` when the text is identified as a song/ballad. Character: `"Narrator"` unless a named character is performing it, in which case that character.
19. **Internal thoughts:** First-person italicized text within a third-person chapter is the POV character's thought. `render_mode: "thought"`, character: POV character.
20. **Chapter headings:** If the chapter title/number appears at the top of the input, make it the first segment with `render_mode: "chapter_heading"`, character: `"Narrator"`.

## Few-Shot Examples

### Example 1 — Chapter heading, simple dialogue, attribution

**Cast:** `["Narrator", "Eddard Stark", "Bran Stark"]`

**Input:**
```
BRAN

"Keep the pony well in hand," his father told him. "And don't look away. Father will know if you do."

Bran kept his pony well in hand, and did not look away.
```

**Output:**
```json
[
  {"order": 1, "character": "Narrator", "text": "BRAN", "render_mode": "chapter_heading", "emotion_tags": [], "confidence": 100, "notes": "Chapter title is also a POV character name."},
  {"order": 2, "character": "Eddard Stark", "text": "\"Keep the pony well in hand,\"", "render_mode": "dialogue", "emotion_tags": [], "confidence": 95, "notes": null},
  {"order": 3, "character": "Narrator", "text": "his father told him.", "render_mode": "prose", "emotion_tags": [], "confidence": 100, "notes": null},
  {"order": 4, "character": "Eddard Stark", "text": "\"And don't look away. Father will know if you do.\"", "render_mode": "dialogue", "emotion_tags": [], "confidence": 95, "notes": "Continuation of same speaker's line; 'his father' resolved to Eddard Stark via cast alias."},
  {"order": 5, "character": "Narrator", "text": "Bran kept his pony well in hand, and did not look away.", "render_mode": "prose", "emotion_tags": [], "confidence": 100, "notes": null}
]
```

### Example 2 — Unattributed dialogue inferred from two-person alternation

**Cast:** `["Narrator", "Tyrion Lannister", "Jaime Lannister"]`

**Input:**
```
Tyrion looked up from his book. "You've been drinking."

"Observant of you."

"It's not yet noon."

"I started at breakfast."
```

**Output:**
```json
[
  {"order": 1, "character": "Narrator", "text": "Tyrion looked up from his book.", "render_mode": "prose", "emotion_tags": [], "confidence": 100, "notes": null},
  {"order": 2, "character": "Tyrion Lannister", "text": "\"You've been drinking.\"", "render_mode": "dialogue", "emotion_tags": [], "confidence": 95, "notes": null},
  {"order": 3, "character": "Jaime Lannister", "text": "\"Observant of you.\"", "render_mode": "dialogue", "emotion_tags": [], "confidence": 82, "notes": "Inferred from two-person alternation; Jaime is the only other speaker present in this excerpt."},
  {"order": 4, "character": "Tyrion Lannister", "text": "\"It's not yet noon.\"", "render_mode": "dialogue", "emotion_tags": [], "confidence": 85, "notes": null},
  {"order": 5, "character": "Jaime Lannister", "text": "\"I started at breakfast.\"", "render_mode": "dialogue", "emotion_tags": [], "confidence": 85, "notes": null}
]
```

### Example 3 — Emotion tags from attribution verbs

**Cast:** `["Narrator", "Arya Stark", "Eddard Stark"]`

**Input:**
```
"She's my sister!" Arya shouted, her cheeks burning.

Ned sighed and shook his head. "And she is also your lady."
```

**Output:**
```json
[
  {"order": 1, "character": "Arya Stark", "text": "\"She's my sister!\"", "render_mode": "dialogue", "emotion_tags": ["shouted", "angry"], "confidence": 95, "notes": "Shouted tag from explicit verb; angry from 'cheeks burning' + shouted."},
  {"order": 2, "character": "Narrator", "text": "Arya shouted, her cheeks burning.", "render_mode": "prose", "emotion_tags": [], "confidence": 100, "notes": null},
  {"order": 3, "character": "Narrator", "text": "Ned sighed and shook his head.", "render_mode": "prose", "emotion_tags": [], "confidence": 100, "notes": null},
  {"order": 4, "character": "Eddard Stark", "text": "\"And she is also your lady.\"", "render_mode": "dialogue", "emotion_tags": ["sigh"], "confidence": 92, "notes": "Sigh tag carried from preceding narration 'Ned sighed' — describes the manner of this line's delivery."}
]
```

### Example 4 — Internal thought (italicized)

**Cast:** `["Narrator", "Jon Snow"]`

**POV context:** The chapter's POV character is Jon Snow.

**Input:**
```
He looked at the wall and felt his breath catch. *It's so much taller than I imagined.* He tightened his grip on the reins.
```

**Output:**
```json
[
  {"order": 1, "character": "Narrator", "text": "He looked at the wall and felt his breath catch.", "render_mode": "prose", "emotion_tags": [], "confidence": 100, "notes": null},
  {"order": 2, "character": "Jon Snow", "text": "It's so much taller than I imagined.", "render_mode": "thought", "emotion_tags": [], "confidence": 88, "notes": "Italicized first-person thought in a Jon Snow POV chapter. Note italic markers stripped from text field."},
  {"order": 3, "character": "Narrator", "text": "He tightened his grip on the reins.", "render_mode": "prose", "emotion_tags": [], "confidence": 100, "notes": null}
]
```

### Example 5 — Embedded letter with inferred author

**Cast:** `["Narrator", "Catelyn Stark", "Lysa Arryn"]`

**Input:**
```
Catelyn unfolded the parchment with trembling hands. The letter was short.

*My dear sister — the Lannisters killed him. Do not trust them. Stay safe in Winterfell. — L.*

She read it three times.
```

**Output:**
```json
[
  {"order": 1, "character": "Narrator", "text": "Catelyn unfolded the parchment with trembling hands. The letter was short.", "render_mode": "prose", "emotion_tags": [], "confidence": 100, "notes": null},
  {"order": 2, "character": "Lysa Arryn", "text": "My dear sister — the Lannisters killed him. Do not trust them. Stay safe in Winterfell. — L.", "render_mode": "letter", "emotion_tags": [], "confidence": 72, "notes": "Letter signed 'L.' and addressed to 'my dear sister' — inferred author Lysa Arryn based on cast relationships. Flag for review; if uncertain, reassign to Narrator."},
  {"order": 3, "character": "Narrator", "text": "She read it three times.", "render_mode": "prose", "emotion_tags": [], "confidence": 100, "notes": null}
]
```

### Example 6 — Song / ballad within a chapter

**Cast:** `["Narrator", "Marillion"]`

**Input:**
```
Marillion strummed his lute and began the old song.

*The bear, the bear!
All black and brown, and covered in hair!*

The tavern roared with laughter.
```

**Output:**
```json
[
  {"order": 1, "character": "Narrator", "text": "Marillion strummed his lute and began the old song.", "render_mode": "prose", "emotion_tags": [], "confidence": 100, "notes": null},
  {"order": 2, "character": "Marillion", "text": "The bear, the bear!\nAll black and brown, and covered in hair!", "render_mode": "song_lyrics", "emotion_tags": ["amused"], "confidence": 88, "notes": "Song performed by Marillion. Preserve line break in text. HumeAI TADA engine likely best for rendering."},
  {"order": 3, "character": "Narrator", "text": "The tavern roared with laughter.", "render_mode": "prose", "emotion_tags": [], "confidence": 100, "notes": null}
]
```

## Edge Case Handling

### Nested quotes (character quoting another)
> "He said, 'Never trust a Lannister,' and I believed him."

This is ONE dialogue segment. The nested quote is part of the outer speech. Do not re-attribute the inner quote.

### Group dialogue
> "For the king!" the soldiers shouted.

If a "Crowd" or generic group character exists in the cast, use it. Otherwise, use `"Narrator"` with a note. `emotion_tags: ["shouted"]`.

### Dialect / foreign language
> "Valar morghulis," she said.

Keep the text verbatim. Attribute normally. Add a note flagging the foreign phrase so the pronunciation system can handle it downstream.

### Interrupted dialogue
> "I think we should—" she began, but he cut her off.

- Dialogue segment: `"\"I think we should—\""`
- Narrator segment: `"she began, but he cut her off."`

### Speaker not in cast list
If a speaker name appears in the text but is NOT in the cast list, assign the line to `"Narrator"` with confidence ≤ 60 and a note: `"Speaker 'X' not in cast list — needs review."` This flags it for re-extraction.

### POV character from chapter title
If the chapter title matches a cast character's name (e.g., "BRAN," "CATELYN"), treat that character as the POV for the chapter. Italicized first-person thoughts default to them.

## Constraints (read carefully)

- Return ONLY a valid JSON array.
- No preamble. No code fences. No trailing text.
- Every `character` value must EXACTLY match a canonical name from the cast list OR be literally `"Narrator"`. Aliases are not valid here — resolve them.
- Every word of the chapter must appear in exactly one segment.
- Do NOT introduce characters not in the cast list.
- Do NOT combine multiple speakers into one segment.
- Preserve italic content verbatim in the `text` field, minus the `*` markers themselves (they are formatting metadata, not spoken content).

## Input

### Cast List
```json
{CAST_JSON}
```

### Chapter Context
- Chapter number: `{CHAPTER_NUMBER}`
- Chapter title: `{CHAPTER_TITLE}`
- POV character (if detected): `{POV_CHARACTER_NAME}`

### Chapter Text

<chapter>
{CHAPTER_TEXT}
</chapter>

---

Return ONLY the JSON array.
