# Clunkster


GameMaker 8.2 optimization tools and project processing pipeline.

Non-destructive tools:

- Linter: `tree.yyd` validator (see [ex1.2](https://shaperones0.github.io/clunkster/examples/#example-12-lint-treeyyd-files))
- Linter: unused assets detector (see [ex2.3](https://shaperones0.github.io/clunkster/examples/#example-23-lint-unused-assets) and [ex3.2](https://shaperones0.github.io/clunkster/examples/#example-32-lint-unreachable-assets))
- (TODO) Linter: heavy assets detector (RAM & disk size)
- Cluster boundaries: assets referenced across clusters, directly (see [ex2.4](https://shaperones0.github.io/clunkster/examples/#example-24-clusters-cross-cluster-references)) or through the dependency graph (see [ex3.3](https://shaperones0.github.io/clunkster/examples/#example-33-clusters-room-boundaries)), are moved to Common, with a report and a RAM budget (see [ex3.4](https://shaperones0.github.io/clunkster/examples/#example-34-clusters-moved-to-common))
- Game Juicer (Prod Build): convert assets into external versions and generate code for their loading (see [ex4.1](https://shaperones0.github.io/clunkster/examples/#example-41-juicer-the-juice); [Dehydration](https://shaperones0.github.io/clunkster/#dehydration))

Lightly destructive tools:

- (TODO) Backgrounds minifier: strip tilesets of all unused space
- (TODO) Audio optimizer: optimize audio files via [FFmpeg](https://www.ffmpeg.org/) (see [ex4.1](https://shaperones0.github.io/clunkster/examples/#example-41-juicer-the-juice) (part of Juicer))

Super destructive tools:

- (TODO) Project crippler (Dev Build): replace assets with lightweight stubs for faster development

Read [docs](https://shaperones0.github.io/clunkster) for more.

![game reduced RAM usage from 2.8 GB to 609.71 MB omg cat thumbs up](/screenshots/title.png)
