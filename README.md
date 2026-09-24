# Rust Game Icons
![Logo](https://repository-images.githubusercontent.com/1166679041/be2b8587-1a78-4e75-8f3d-881b7ce6ef76)
**A curated collection of high-quality PNG icons extracted from the Rust game.**

This repository contains hundreds of icons organised by category. These graphics are useful for developers, modders, map makers, and anyone creating tools or documentation related to the RUST. Feel free to browse, download, and use them in your projects.

> 🔸 *Note:* The assets originate from the Rust game and are provided for convenience. They are not officially affiliated with or endorsed by Facepunch Studios. Please respect the game's licensing and intellectual property when using these icons.

---

## 📁 Repository Structure

The icons are grouped into folders by type or theme. Each file is a standalone `.png` image with a transparent background. Item metadata (ids, shortnames, categories, localized names and descriptions) lives in `items.json`, `items.compact.json` and `items.desc.json`.

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

Some items (mostly legacy or admin-only ones) are not localized by the game itself — for those all languages simply repeat the English name.

---

## 🛠️ Contribution

Contributions are welcome! Feel free to submit pull requests for:

- Missing icons or categories.

---

## 📜 Disclaimer

This repository is created by community members and is **not an official product** of Facepunch Studios. Use at your own discretion.

---
