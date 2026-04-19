# Chorus Voice Library — Casting Document

> Master sourcing document for Chorus voice library.
> Personal use only. Audio extracted for voice cloning via Voicebox on MacBook.

---

## Library architecture: tiered approach

The Chorus voice library is organized into three tiers based on prominence of characters they'll voice. Quality effort concentrates where it matters.

### Tier A — Hero voices (~50 voices, hand-curated)

**Who uses them:** POV characters, named main cast, villains, mentors — the voices listeners consciously notice.

**Sourcing:** Careful manual curation from GoT cast + top-quality actors + premium LibriVox readers. Every Tier A voice personally auditioned.

**Time investment:** ~15-20 hours total (once, reusable across all books).

### Tier B — Supporting voices (~75-100 voices, semi-manual)

**Who uses them:** Named secondary characters, recurring supporting cast, lords/ladies with dialogue but not POV roles.

**Sourcing:** Top-tier LibriVox readers, lesser-role GoT cast members, film/TV actors with good supporting-role voices. Vetted but not obsessed over.

**Time investment:** ~15-20 hours total.

### Tier C — Background voices (~150-200 voices, automated)

**Who uses them:** Minor characters, "another man" unnamed speakers, crowd members, one-line roles, background dialogue.

**Sourcing:** Bulk acquisition via automated pipeline (Phase 5.5+ project) from voice catalogs with automated quality scoring. Spot-checked only.

**Time investment:** ~2 hours review after pipeline build.

**Total library target: ~300-350 voices** with quality concentrated where listeners notice.

---

## Auto-casting routing by tier

Chorus's auto-casting prompt routes characters to tiers based on `estimated_line_count`:

| Character type | Tier | Examples (AGoT) |
|---|---|---|
| POV character | A | Eddard, Bran, Catelyn, Dany, Tyrion |
| Main-line non-POV | A | Cersei, Jon, Robert, Joffrey |
| Supporting recurring | B | Jory Cassel, Luwin, Renly, Barristan |
| Minor recurring | B/C | Old Nan, Yoren, Hullen, Harwin |
| One-line / unnamed | C | "another man," crowds, servants, guards |

---

## Status legend

- 🎯 **Priority: first production** — needed for AGoT chapter 1 (BRAN)
- ⭐ **Priority: standard library** — needed for broad AGoT coverage
- 🔮 **Priority: future** — appears in later books; can defer
- 📋 **Priority: Tier C bulk** — acquire via automation pipeline later

---

## Tier A — Hero Voices (GoT cast + premium)

### Narrator

| Field | Value |
|---|---|
| Chorus voice | Warm Narrator |
| GoT actor | **Charles Dance** (tentative — user to revisit) |
| Reasoning | Deep authoritative British voice with gravitas. Gives narration a cinematic quality. |
| Audio sources | (1) Tywin scenes in GoT Season 1, particularly Episode 7 "You Win or You Die" armor-cleaning scene. (2) Documentary narrations (History Channel, BBC). (3) *The Witcher 3* video game as Emhyr var Emreis. (4) *Mastering the Tempest* BBC radio drama. |
| Alternative | Roy Dotrice (original ASOIAF audiobook narrator, deceased 2017); Michael Kramer (current Audible ASOIAF narrator). |
| Best first pick | GoT S1E7 "You Win or You Die" armor scene — iconic, solo, ~30 seconds clean audio |
| Open decision | Charles Dance vs Kramer vs Dotrice |
| Status | 🎯 Tier A |

### Starks

| Field | Value |
|---|---|
| Chorus voice | Grizzled Northern Lord |
| GoT actor | **Sean Bean** |
| Intended characters | Eddard Stark |
| Reasoning | Literal match. Yorkshire accent = northern Westerosi feel. |
| Audio sources | (1) GoT S1E1 beheading scene opening ("In the name of Robert of the House Baratheon..."). (2) *Sharpe* TV series. (3) *Civilization VI* narration. (4) *Alan Turing: The Enigma* audiobook portions. |
| Best first pick | GoT S1E1 beheading scene — ~20s clean solo audio |
| Status | 🎯 Tier A |

| Field | Value |
|---|---|
| Chorus voice | Warm Noble Matron |
| GoT actor | **Michelle Fairley** |
| Intended characters | Catelyn Stark |
| Reasoning | Northern Irish accent — Tully warmth with steel underneath. |
| Audio sources | (1) GoT Seasons 1-3. (2) *Harry Potter and the Deathly Hallows Part 1*. (3) *Suits* Season 9 as Faye Richardson. (4) BBC radio dramas. |
| Best first pick | GoT S1E2 Catelyn-Bran bedside scenes |
| Status | 🎯 Tier A |

| Field | Value |
|---|---|
| Chorus voice | Gentle Young Boy |
| GoT actor | **Isaac Hempstead Wright** |
| Intended characters | Bran Stark |
| Cloning concern | **Voicebox may struggle with child voices.** Test early. Fallback: use adult actor doing put-on child voice. |
| Audio sources | GoT Seasons 1-2 pre-injury Bran dialogue; press interviews at ages 11-13. |
| Best first pick | GoT S1E1 archery scene with Robb and Jon |
| Status | 🎯 Tier A |

| Field | Value |
|---|---|
| Chorus voice | Earnest Young Knight (Jon) |
| GoT actor | **Kit Harington** |
| Intended characters | Jon Snow |
| Audio sources | (1) GoT all seasons. (2) *Pompeii* film. (3) *Modern Love* anthology. (4) *Happy Sad Confused* podcast. |
| Best first pick | GoT S1E1 Jon's feast conversation with Uncle Benjen |
| Status | 🎯 Tier A |

| Field | Value |
|---|---|
| Chorus voice | Earnest Young Knight (Robb) — **split recommended** |
| GoT actor | **Richard Madden** |
| Intended characters | Robb Stark |
| Reasoning | Warmer, more assertive than Jon. In BRAN ch1, both Jon and Robb speak — need distinct voices. |
| Audio sources | (1) GoT Seasons 1-3 Robb scenes. (2) *Bodyguard* BBC series — lead role, extensive clean dialogue. (3) *Rocketman* as Elton John's manager. |
| Best first pick | *Bodyguard* opening episode — studio-quality audio |
| Status | 🎯 Tier A |

| Field | Value |
|---|---|
| Chorus voice | Feral Young Girl |
| GoT actor | **Maisie Williams** |
| Intended characters | Arya Stark |
| Audio sources | (1) GoT Arya scenes. (2) *Two Weeks to Live* Sky comedy. (3) *The New Mutants* film. |
| Best first pick | GoT S1E3 first sword lesson with Syrio |
| Status | ⭐ Tier A (not in BRAN ch1) |

### Lannisters

| Field | Value |
|---|---|
| Chorus voice | Witty Wanderer |
| GoT actor | **Peter Dinklage** |
| Intended characters | Tyrion Lannister |
| Audio sources | (1) GoT Tyrion scenes, especially S4 trial monologue. (2) *The Station Agent* breakout film. (3) *Cyrano* 2021 film. |
| Best first pick | GoT S4E6 "I demand a trial by combat" speech |
| Status | ⭐ Tier A |

| Field | Value |
|---|---|
| Chorus voice | Cunning Whisperer |
| GoT actor | **Aidan Gillen** |
| Intended characters | Petyr Baelish |
| Alternative splits | Consider separating Varys (Conleth Hill) and Jaime (Nikolaj Coster-Waldau) into their own Tier A voices. |
| Audio sources | (1) GoT Littlefinger scenes. (2) *The Wire* seasons 3-5 as Mayor Carcetti. (3) *Peaky Blinders* as Aberama Gold. |
| Best first pick | GoT S3 "chaos is a ladder" speech |
| Status | ⭐ Tier A |

| Field | Value |
|---|---|
| Chorus voice | Cold Regal Queen |
| GoT actor | **Lena Headey** |
| Intended characters | Cersei Lannister |
| Audio sources | (1) GoT Cersei scenes. (2) *300* as Queen Gorgo. (3) Multiple audiobook narrations. |
| Best first pick | GoT S4E2 Cersei-Tyrion wedding confrontation |
| Status | ⭐ Tier A |

| Field | Value |
|---|---|
| Chorus voice | Stern Military Commander |
| GoT actor | **Stephen Dillane** (to avoid Charles Dance / narrator collision) |
| Intended characters | Tywin Lannister, Stannis Baratheon |
| Reasoning | Narrator uses Charles Dance; using him for Tywin too would create narrator/character confusion. Stephen Dillane as Stannis has equally clipped, commanding delivery. |
| Audio sources | GoT Stannis scenes; Dillane has extensive theater and audio-narration work including Shakespeare audiobooks. |
| Open decision | Confirmed Dillane, or revisit later? |
| Status | ⭐ Tier A |

### Greyjoys

| Field | Value |
|---|---|
| Chorus voice | Cocky Young Sardonic — **library gap, priority add** |
| GoT actor | **Alfie Allen** |
| Intended characters | Theon Greyjoy |
| Reasoning | Current library has no Theon-appropriate voice — auto-casting collapses him onto Tyrion's "Witty Wanderer." Alfie Allen is needed distinctly. |
| Audio sources | (1) GoT Theon scenes, especially S1-2 pre-Reek. (2) *Jojo Rabbit* as Finkel. |
| Best first pick | GoT S1E7 Theon's brothel scene with Ros — cocky register |
| Status | 🎯 Tier A — library gap for BRAN ch1 |

### Supporting (but Tier A prominence)

| Field | Value |
|---|---|
| Chorus voice | Booming Warrior King — **library gap** |
| GoT actor | **Mark Addy** |
| Intended characters | Robert Baratheon |
| Audio sources | (1) GoT Robert scenes, S1E1 greeting scene iconic. (2) *A Knight's Tale* as Roland. (3) *The Full Monty*. (4) *Still Standing* US sitcom. |
| Best first pick | GoT S1E1 "Ned! You've got fat!" |
| Status | 🔮 Tier A library gap |

| Field | Value |
|---|---|
| Chorus voice | Regal Young Woman |
| GoT actor | **Emilia Clarke** |
| Intended characters | Daenerys Targaryen |
| Consider splitting | Sansa (Sophie Turner) and Margaery (Natalie Dormer) are distinctive enough to warrant Tier A entries of their own. Defer split to when they become narratively important. |
| Audio sources | (1) GoT Dany scenes. (2) *Me Before You*. (3) *Solo: A Star Wars Story*. |
| Best first pick | GoT S1E10 Dany emerging from the fire — iconic delivery |
| Status | ⭐ Tier A |

---

## Tier B — Supporting Voices (mixed sourcing)

### From GoT cast (supporting roles)

| Voice | Source | Priority |
|---|---|---|
| Rough Sellsword (Hound register) | **Rory McCann** (Hound) | ⭐ |
| Rough Sellsword (Bronn register) | **Jerome Flynn** (Bronn) — split from Hound | ⭐ |
| Gruff Middle-Aged Man (Luwin) | **Donald Sumpter** (Maester Luwin) | 🎯 BRAN ch1 |
| Nervous Young Man | **John Bradley** (Samwell) | 🎯 BRAN ch1 |
| Deep Foreign Warrior | **Jason Momoa** (Drogo) — test cloning carefully | 🔮 |
| Aging Northern Exile | **Iain Glen** (Jorah Mormont) | 🔮 |
| Solemn Elder Priest | **Jonathan Pryce** (High Sparrow) | 🔮 |
| Petulant Teen Villain | **Jack Gleeson** (Joffrey) — only GoT for audio | 🔮 |
| Sharp Elder Female | **Diana Rigg** (Olenna, deceased 2020) | 🔮 |
| Elderly Common Woman | **Margaret John** (Old Nan, deceased 2011) — source from *Gavin & Stacey* | 🔮 |
| Warrior Female Young Adult | **Gwendoline Christie** (Brienne) | 🔮 |
| Lyrical Exotic Male | **Tom Wlaschiha** (Jaqen) or **Miltos Yerolemou** (Syrio) | 🔮 |

### From premium LibriVox readers

**Approach:** Identify ~30-40 top-tier LibriVox readers to add for accents and types GoT doesn't supply.

**Research needed:** Browse LibriVox's "Hall of Fame" readers and audiobook-community best-of lists. Build a shortlist grouped by voice archetype. (This is Phase 5.5 research work — defer until after Voicebox is live on Mac so we can test cloning quality with real samples.)

**Likely archetypes Tier B should cover that GoT doesn't:**
- American accents (several varieties — Southern, Midwestern, NY, California)
- Caribbean / African accents
- Asian accents (range — Indian, Chinese, Japanese, Korean)
- Eastern European accents
- More elder male voices with different textures
- More child voices (both genders, if cloneable)
- More non-binary / androgynous adult voices
- Heavy-regional British accents (Cockney, Geordie, Welsh, Cornish)
- Religious/clerical registers with different flavors (sermon-voice, contemplative-voice)

---

## Tier C — Background Voices (Phase 5.5+ automated acquisition)

**Scope:** ~150-200 voices acquired in bulk for background characters, crowd murmuring, one-line NPCs.

**Sourcing pipeline (Phase 5.5 project, deferred):**

1. Query voice catalog APIs (ElevenLabs community library, PlayHT catalog, LibriVox bulk scrape, Voices.com filtered searches)
2. Automated download of preview/sample audio
3. Automated quality scoring:
   - SNR analysis
   - Single-speaker detection (pyannote-audio)
   - Artifact detection (clipping, compression, silence gaps)
   - Pitch stability and range estimation
4. Reject below-quality samples automatically
5. Bulk import accepted samples to Chorus library with auto-generated metadata
6. Human spot-check of 10-20 random samples before committing to library

**Estimated pipeline build: 1-2 Phase 6+ sessions.**

**ToS considerations:** ElevenLabs and most commercial services prohibit cloning from their outputs. For personal-use-only with no sharing, practical risk is low but formal violation exists. LibriVox alone avoids this entirely and has enough reader diversity to fill Tier C if preferred.

**Decision deferred:** commercial catalog inclusion vs LibriVox-only for Tier C — revisit when building the pipeline.

---

## Production priorities

### For first production (AGoT Chapter 1 — BRAN)

Only 10 voices needed:

1. **Narrator** — Charles Dance (GoT Tywin scene)
2. **Grizzled Northern Lord (Eddard)** — Sean Bean (GoT beheading scene)
3. **Gentle Young Boy (Bran)** — Isaac Hempstead Wright
4. **Earnest Young Knight Jon** — Kit Harington
5. **Earnest Young Knight Robb** — Richard Madden
6. **Cocky Young Sardonic (Theon)** — Alfie Allen
7. **Warm Noble Matron (Catelyn)** — Michelle Fairley (for mentions only)
8. **Gruff Middle-Aged Man (Luwin/Hullen)** — Donald Sumpter
9. **Nervous Young Man** — John Bradley
10. **Rough Sellsword (Jory proxy)** — Jerome Flynn

**Captured in one ~2 hour session from GoT Seasons 1-2 alone.**

### Full AGoT coverage (before producing full first book)

Add remaining ⭐ Tier A + core Tier B voices (~30-40 total).

**Session budget: ~10-15 hours across a couple of weekends.**

### Cross-book generalization

Once Tier A + B are populated, auto-casting should handle any fantasy/historical/literary novel in your queue without new sourcing work. Tier C fills background gaps automatically once pipeline exists.

---

## Audio capture workflow

### Tools (Mac setup)
```bash
brew install yt-dlp ffmpeg
# Audacity: download from audacityteam.org
```

### Per-voice capture procedure

1. **Identify source** — YouTube URL, audiobook preview, podcast episode, owned media
2. **Download** — `yt-dlp --extract-audio --audio-format wav <url>` or direct rip
3. **Locate passage** — find 15-30 second clean segment with target actor in character
4. **Trim** — open in Audacity, select range, Export Selected Audio
5. **Clean** — Effect > Noise Reduction (use 2-second silent section as profile), Effect > Normalize to -3dB
6. **Export** — WAV, 44.1 kHz, 16-bit, mono
7. **Upload** — Chorus voice library → attach to corresponding voice entry
8. **Test clone** — in Chorus, generate a test sentence, listen
9. **Iterate if needed** — different passage from same source, or different source

### Clean sample criteria

- **Single voice** — no other speakers, no music, no environmental noise
- **Consistent delivery** — character stays in one register throughout
- **Representative** — sounds like how you want the voice in your audiobook
- **Clean codec** — not heavily compressed, no clipping, no hiss

### Length guidance

- **Minimum**: 10 seconds
- **Sweet spot**: 20-25 seconds
- **Maximum**: 60 seconds (no improvement beyond this)

**Principle:** clean 20s > noisy 60s.

---

## Voice cloning quality predictions

Based on Voicebox / voice-cloning system norms:

### Likely to clone excellently
- Charles Dance, Sean Bean, Lena Headey, Peter Dinklage, Michelle Fairley, Jonathan Pryce, John Bradley — measured studio-voice professionals in normal vocal ranges

### Clone with some character loss
- Jason Momoa (deep flatten risk)
- Diana Rigg, Margaret John (elder female rasp may smooth)
- Miltos Yerolemou (heavy accent may generic-ify)
- Jack Gleeson (teen ambiguity)

### Unknown — test first before committing
- Isaac Hempstead Wright (child voice — cloning systems often weak here)
- Emilia Clarke (specific ethereal quality)
- Gwendoline Christie (unusual vocal range)

**Mitigation:** if a target voice clones poorly, fallback to nearest archetype match. Document which voices are clone-fragile in Chorus's voice metadata notes field.

---

## Open decisions

1. **Narrator voice identity** — Charles Dance vs Michael Kramer vs Roy Dotrice
2. **Stern Military Commander** — Stephen Dillane confirmed?
3. **Jon/Robb/Renly splitting** — three Tier A entries or shared Earnest Young Knight?
4. **Dany/Sansa/Margaery splitting** — three Tier A entries or shared Regal Young Woman?
5. **Tier B LibriVox research** — when to do the curation pass (suggest: after first production, with real "we need X voice" data)
6. **Tier C commercial vs LibriVox-only** — decide when building the automation pipeline

---

## Revision history

**2026-04-19** — Initial draft with GoT cast mapping.
**2026-04-19** — Restructured for tiered library approach (Tier A/B/C). Added Phase 5.5 Tier C automation plan. Reduced first-production voice count from full library to minimum 10 for BRAN chapter 1.
