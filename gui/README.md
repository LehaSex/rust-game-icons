# GUI Icons

UI icons extracted from the Rust game, organised exactly like the in-game asset hierarchy, so you can find any icon by mirroring the game's file structure.

This section is made specifically to make plugin development easier. In your plugin code you can reference these icons using the same paths the game itself uses:

- `/assets/icons/…` – general UI icons (status effects, gestures, building, UI controls, etc.)
- `/assets/content/ui/…` – content UI icons (map markers, overlays, game UI elements, etc.)

For example, `/assets/icons/health.png` or `/assets/content/ui/map/…` will resolve directly in Rust plugin environments (Oxide/uMod, Harmony, etc.).

## Structure

```
gui/
├── icons/           /assets/icons/ – general UI icons
│   ├── gestures/    gesture icons
│   ├── build/       building block icons
│   ├── elevator/    elevator UI icons
│   ├── farming/     farming UI icons
│   ├── flags/       language / country flags
│   ├── markers/     map marker icons
│   ├── cinematic/   cinematic mode icons
│   └── *.png        individual UI icons
└── content/
    └── ui/          /assets/content/ui/ – content UI icons
        ├── gameui/  in-game UI elements
        ├── map/     map icons
        ├── misc/    miscellaneous
        ├── chickencoop/, deepsea/, developer/, tiledpatterns/ …
        └── *.png    overlays, markers, backgrounds
```
