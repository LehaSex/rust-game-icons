# Rust Game Icons
![Logo](https://repository-images.githubusercontent.com/1166679041/be2b8587-1a78-4e75-8f3d-881b7ce6ef76)
**A curated collection of high-quality PNG icons extracted from the Rust game.**

This repository contains hundreds of icons organised by category. These graphics are useful for developers, modders, map makers, and anyone creating tools or documentation related to the RUST. Feel free to browse, download, and use them in your projects.

> 🔸 *Note:* The assets originate from the Rust game and are provided for convenience. They are not officially affiliated with or endorsed by Facepunch Studios. Please respect the game's licensing and intellectual property when using these icons.

---

## 📁 Repository Structure

The icons are grouped into folders by type or theme. Each file is a standalone `.png` image with a transparent background. Item metadata (ids, shortnames, categories, localized names and descriptions, crafting data) lives in `items.json`, `items.compact.json`, `items.desc.json`, `items.craft.json` and `items.recycle.json`.

Some of the top-level directories include:

- `ammo/` – ammunition types such as pistol, rifle, rocket, arrows, etc.
- `attire/` – clothing and armor pieces including helmets, outfits, and costumes.
- `components/` – crafting components used throughout the game.
- `construction/` – building materials and structures like walls, doors, foundations.
- `electrical/` – circuits, batteries, lights, and other electrical items.
- `food/` – consumables such as berries, cooked meat, and rations.
- `fun/` – novelty items, toys, and seasonal decorations.
- `items/` – miscellaneous usable objects that don’t fit into other categories.
- `medical/` – bandages, syringes, medkits, and health-related gear.
- `misc/` – assorted icons like quest items or generic symbols.
- `resources/` – raw materials like wood, stone, metal fragments.
- `tools/` – tools such as hammers, wrenches, jackhammers.
- `traps/` – bear traps, landmines, shotgun traps, etc.
- `weapons/` – melee and ranged weapons including guns, bows, machetes.

> **Special category:** `npc/` contains portraits and avatars of in-game NPCs. Unlike the other categories, these images are **not included** in `items.json`, as they are not regular Rust item icons.
> **Special category:** `gui/` contains UI icons.
> The list above is not exhaustive – explore the repository to discover every category.

---

## 📄 Data Files

- **`items.json`** – full item database: `id`, `image_name` (item shortname), `category`, and a `name` object with the item's display name in every language the game ships (English, Russian, Simplified Chinese and more — 31 languages total). Languages are synced from the game's own localization files, so they stay consistent with the installed game version; if the game has no translation for an item, other languages fall back to English.
- **`items.compact.json`** – the same items, but `name` is limited to the three languages that matter most for community tools: `en`, `zh-cn`, `ru` (in that order, always present – missing translations fall back to English).
- **`items.desc.json`** – separate lookup table: item shortname → localized item description in all languages (English fallback when the game has no translation). Items the game gives no description for are not listed.
- **`items.craft.json`** – separate lookup table: item shortname → crafting data extracted from the game's recipe assets (`ItemBlueprint`). Includes **every** item; each record has the **same set of fields** (uniform contract), non-applicable values are `null`, "off/none" is `false`/`0`/`[]`: `craftable`, `craft_workbench` (shortname of the workbench required for crafting – `workbench1`/`workbench2`/`workbench3`/`workbench4`, the last being the monument workbench used by jumpsuits; `null` = no workbench needed), `amount` (items produced per craft), `time` (craft time in seconds, accounting for the game's own time cap), `ingredients` (`[{item, amount}]`), `rarity`, `researchable`, `research_scrap` (scrap cost of researching the blueprint; computed by the game from item rarity – Common 15 / Uncommon 30 / Rare 60 / VeryRare 120, default-blueprint items cost 10; `null` when the item cannot be researched), `research_workbench` (shortname of the workbench whose tech tree tab unlocks the item, i.e. the workbench needed to research it – `workbench1`/`workbench2`/`workbench3`, or `iotable` for the Engineering Workbench, which takes priority over the regular tabs; `null` when the item is not in any tech tree), `techtree_scrap` (total scrap cost of unlocking the item in the tech tree from scratch, including all prerequisite nodes on the required path – vanilla values without server taxes/workbench upgrade multipliers), `default_blueprint`, `scrap_from_recycle`, `needs_steam_item`, `require_unlocked_item`, `additional_unlocks`, `force_time`, `skin_of` (shortname of the base item for skin/DLC-variant items that act as another item), `stack_size` (maximum stack size), `despawn` (despawn time of a dropped item in seconds: torches, maps and similar `quickDespawn` items – 30; other items – by the item's despawn tier, where tiers 0-1 mean 5 minutes, 2 – 20, 3 – 40, 4 – 60; skin items inherit the tier of the base item). Times and costs reflect vanilla game rules – servers can alter them with convars and mods.
- **`items.recycle.json`** – separate lookup table: item shortname → recycling data, plus the global `recyclers` block describing the four recycler rates: `safe_zone` (Outpost / Bandit Camp – 40%, 8s per cycle), `monument` (green monument recyclers – 50%, 5s), `monument_powered` (the same green recyclers with the monuments' power grid stage 2+ – 60%, 4.5s at stage 4) and `power_plant` (the red Power Plant recycler – 75%, 4s, requires power grid stage 4). A recycler breaks an item back into its recipe ingredients (non-craftable items use their service recipes shipped in the game data): every ingredient except scrap returns `amount × efficiency / amountToCreate` units, where whole units are guaranteed and the `chance` (0-1) is the probability of one extra unit. `scrap` is the `scrap_from_recycle` value scaled by the recycler rate (the base value corresponds to the 50% rate; leftover scrap fractions carry over to the next item instead of being rolled). All values assume the item is at full condition – damaged items return less. Items that yield nothing are listed as `{"recyclable": false}`.

---
