# Clunkster


GameMaker 8.2 optimization tools and project processing pipeline.

Non-destructive tools:

- Linter: `tree.yyd` validator (see [ex1.2](https://shaperones0.github.io/clunkster/examples/#example-12-lint-treeyyd-files))
- Linter: unused assets detector (see [ex2.2](https://shaperones0.github.io/clunkster/examples/#example-22-lint-unused-assets) and [ex3.2](https://shaperones0.github.io/clunkster/examples/#example-32-lint-unreachable-assets))
- (TODO) Linter: heavy assets detector (RAM & disk size)
- Linter: cross-cluster reference boundary validator (see [ex2.3](https://shaperones0.github.io/clunkster/examples/#example-23-lint-cross-cluster-references))
- Linter: room indirect reference validator via dependency graph (see [ex3.3](https://shaperones0.github.io/clunkster/examples/#example-33-lint-room-cluster-boundaries))
- Game Juicer (Prod Build): convert assets into external versions and generate code for their loading (see [ex4.1](https://shaperones0.github.io/clunkster/examples/#example-41-juicer-the-juice); [Dehydration](https://shaperones0.github.io/clunkster/#dehydration))

Lightly destructive tools:

- (TODO) Backgrounds minifier: strip tilesets of all unused space
- (TODO) Audio optimizer: optimize audio files via [FFmpeg](https://www.ffmpeg.org/) (see [ex4.1](https://shaperones0.github.io/clunkster/examples/#example-41-juicer-the-juice) (part of Juicer))

Super destructive tools:

- (TODO) Project crippler (Dev Build): replace assets with lightweight stubs for faster development

Read [docs](https://shaperones0.github.io/clunkster) for more.

![game reduced RAM usage from 2.8 GB to 609.71 MB omg cat thumbs up](/screenshots/title.png)
