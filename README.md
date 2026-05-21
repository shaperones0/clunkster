# Clunkster

Split assets into clusters (or chunks, packs, or whatever) to lighten the load 
(you probably don't need assets from area A while playing or working on area B).

Planned tools:
- Asset clusterizer based on folders in `tree.yyd` files (mostly helps other tools).
- Dependency graph builder (constructs the list of assets that are "potentially used" in each room).
- Dependency linter (things in a room from chunk A should not require things bound to chunk B).
- Project crippler (replace assets with lightweight dummies for faster development)
- Externator (generate external versions of assets and generate code for their loading)
- Game splitter (run Externator, ensure rooms will have assets from their chunks loaded)
