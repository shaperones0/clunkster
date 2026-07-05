"""Readme generator."""

from pathlib import Path

from scripts import (
    doc_code,
    doc_docstring,
    doc_extract,
    doc_headers,
    doc_parse,
    doc_patch,
)
from scripts.doc_code import gen_stub_cls, gen_stub_func, gen_stub_var
from scripts.doc_snippets import Snippet, s_py

FILE_README = Path(__file__).parent.parent / 'README.md'


def txt_readme(
    snips: dict[str, list[Snippet]],
    head: doc_headers.ExampleHeaderManager,
    docs: dict[str, str],
    exs: doc_code.CodeGenerator,
) -> str:
    """Generate readme."""
    return f"""
{head.file_begin('readme.md')}
{head.file_set_gh()}
# Clunkster

GameMaker 8.2 optimization tools and project processing pipeline.

Non-destructive tools:

- Linter: `tree.yyd` validator (see {exs.href('ex_lint_tree')})
- Linter: unused assets detector (see {exs.href('ex_lint_unused')} and {exs.href('ex_lint_unused_graph')})
- (TODO) Linter: heavy assets detector (RAM & disk size)
- Linter: cross-cluster reference boundary validator (see {exs.href('ex_lint_crossref')})
- Linter: room indirect reference validator via dependency graph (see {exs.href('ex_lint_crossref_graph')})
- Game Juicer (Prod Build): convert assets into external versions and generate code for their loading (see {exs.href('ex_juicer_processing')}; [Dehydration](https://shaperones0.github.io/clunkster/rationale/#dehydration))

Lightly destructive tools:

- (TODO) Backgrounds minifier: strip tilesets of all unused space
- (TODO) Audio optimizer: optimize audio files via [FFmpeg](https://www.ffmpeg.org/) (see {exs.href('ex_juicer_processing')} (part of Juicer))

Super destructive tools:

- (TODO) Project crippler (Dev Build): replace assets with lightweight stubs for faster development

Read [docs](https://shaperones0.github.io/clunkster) for more.
"""


def txt_overview(head: doc_headers.ExampleHeaderManager, **_: object) -> str:
    """Generate docs overview section."""
    return f"""

{head.file_begin('index.md')}

{head.header_parse('# Clunkster', 'h_docs')}

GameMaker 8.2 optimization tools and project processing pipeline.

Most of the tools depend heavily on asset clustering (i.e. assigning each asset to an isolated group like "StageA", "StageB", "Common" etc.), but some use it only to group console output.

Given the architectural differences across GameMaker projects, Clunkster is organized as a set of {head.header_href('h_examples', 'examples')} that you can copy, and build your own pipeline out of them. The library itself provides functions that handle various non-obvious quirks and facilitate the core pipeline logic.

Please refer to {head.header_href('h_rationale', 'Rationale')} to see it these tools fit your project.
"""


def txt_rationale(head: doc_headers.ExampleHeaderManager, exs: doc_code.CodeGenerator, **_: object) -> str:
    """Generate rationale section."""
    # PyCharm: Alt+Enter -> Inject language -> Markdown
    return f"""
{head.file_begin('rationale.md')}

{head.header_parse('# Rationale', 'h_rationale')}

GameMaker 8.2 runner is 32-bit, meaning there's a hard cap on RAM of around 4 GB. Furthermore, certain parts of the engine start having hardware-specific issues at even 2.5 GB of RAM usage.

Also, such large projects take 10-15 seconds to build.

The most effective solution is to split the large project into logical clusters. You have "Common" assets (`Player`, `Block`, ...), and stage-specific assets (`bStageATiles`, `StageAPostProc`, ...). So, when game is in a room from Stage A, it technically doesn't require assets from Stage B. Unneeded assets can be replaced with lightweight stubs right in the game project.

For dev builds, the tool can nuke all assets except for ones from specified clusters. Optionally, the resulting stubs can be made more noticeable:

- sprites and backgrounds become pink-black checkerboards
- sounds get replaced with buzz.wav and/or [fiddlesticks.mp3](https://developer.valvesoftware.com/wiki/Missing_content)

Prod builds are similar, but we add dynamic loading. The project is copied, only Common cluster is kept in the base executable. The stage-specific assets are packaged into external files ("wet" versions). When the player enters a new stage, the game dynamically loads ("hydrates") the required assets from the disk. Optionally the stubs can be made less noticeable (though you probably should still make them loud):

- sprites and backgrounds become 2x2 transparent
- sounds get replaced with null.wav

This is explained more in-depth in [Dehydration](#dehydration) and subsequent chapters.

{head.header_parse('## Linters', 'h_linters')}

To prevent developers from accidentally referencing a `StageB` sprite inside a `StageA` object, a dependency linter is included. It builds dependency graph based on static `.gml` and `.txt` metafile analysis.

From those dependencies, the tool can:

- find orphaned assets that are not referenced by anything
- find assets that reference disallowed clusters
- construct sets of assets referenced (both directly and indirectly) in each room, and yell at you if a room references something that it hasn't explicitly been marked to load.

{head.header_parse('## Prerequisites', 'h_prerequisites')}

1. Use this tool only if it's necessary.

    - Setting this up requires a fair bit of technical knowledge (about both GameMaker 8.2 and Python) and can be a headache.
    - I would only recommend using this tool if your game eats more than 1.5 GB of RAM and your project takes more than 10 seconds to build.

2. Use Git - destructive tools will nuke your project. Some do that by design, others can lead to data loss if misconfigured.
3. Follow good practices:

    - Keep asset names clean (press broom icon on IDE's top toolbar to run initial checks).
    - Keep assets belonging to certain stage in that stage's folder.
    - Do not reference things from `stageA` in `stageB` objects (unless such an object is only placed in a room that guarantees both stages loaded).
    - Reference Common objects in Stage-specific, not the other way around.
        - If this is unavoidable (for example, when making a stage-specific movement gimmick), use "_guard scripts_" (`if room_is_stageA() {{ ... }}`).
    - If an asset is shared between multiple stages, then it belongs in Common cluster.
    - DON'T use timelines.
    - DON'T use the dastardly "Treat uninitialized variables as 0 (BAD!!!)" option.
    - Minimize the number of persistent objects (they'll get tagged as referenced in every room).
    - No dynamic asset referencing (tool won't acknowledge those references when building dependency graph):
        - DON'T do math on asset IDs: `draw_sprite(sprSpikeUp+2, x, y)`.
        - DON'T use string execution: `execute_string("instance_create(0, 0, obj_enemy_" + string(current_level) + ")")`.
        - DON'T pass assets via global variables across cluster boundaries: `global.current_boss = obj_StageB_Boss` (If Stage A reads this global, the analyzer cannot trace such dependency).
        - ^ That rule includes assigning assets to constants.
    - Use only `room_goto` for room transitions.
    - Use the linter ignore pragma `//!clunkster: ignore` only in pure data registry scripts (like `sound_balance`), which only reference assets but don't instantiate them

Other than that, use the modern project format (`.gm82`) and Python 3.14+ ([`uv`](https://docs.astral.sh/uv/) recommended).

Following sections elaborate on the prerequisites, reasons behind them, antipatterns, and how to properly fix them.

### Project & Asset organization

Since Clunkster largely relies on splitting assets into clusters, the tool needs a way to automatically generate clusters for each asset. The easiest way is to parse `tree.yyd` files and takes the name of the root directory as a cluster name, merging those based on a provided config (see [{exs.href('ex_aliases')}]). Therefore, some amount of project keeping is required.

❌ Bad:

Sprites:
```
+Enemies
    |sprite83
    |enemy
    |enemy_burn
    |spr_stageA_specific_enemy_that_is_not_encountered_anywhere_else
+StageA
    |a_sprite_that_is_used_to_be_stageA_specific_but_is_in_fact_used_everywhere
+StageFinalBoss_2_Fix_Final
    |enemy
```
Backgrounds:
```
+Stage3
    |bgStage1
    |tileset_that_is_used_everywhere_but_its_in_this_folder_for_reason
    |bgDarkness_2000x200_semitransparent_black_with_spotlight_in_center
```

While the tool doesn't require you to name things properly, no duplicates can exist in the project. Secondly, since trees now has structural value to our clusterization, you should dedicate some effort to reorganizing things.

✅ Good:

Sprites:
```
+sprEnemies
    |sprEnemySpawner
    |sprEnemy
    |sprEnemyBurn
    |sprEnemyPoisoned
+sprStageA
    |sprFireball
+sprStageFinal
    |sprEnemyBuffed
```
Backgrounds:
```
+bgStageA
    |bStageA
+bgStageC
    |bStageC
tCommon
```

With this well organized asset tree you can write the `ALIAS` config so they get correctly assigned to their clusters:

```python
ALIAS: dict[str, list[str]] = {{
    'StageA': [
        'sprStageA',
        'bgStageA'
    ],
    'StageC': [
        'bgStageC'
    ],
    'Common': [
        'sprEnemies',
        # tCommon was automatically assigned Common cluster,
        # since it's in the root of the tree
    ],
    # ...
}}
```

Even though appropriate naming of the assets isn't required, I recommend cleaning them up now. It would also be a good idea to do manual optimization passes before starting integrating clustering-dependent tools, like Game Juicer (unless you have an "unrunable game" situation like I had when I started making this tool).

### Eradicating dynamic asset referencing

I have seen these quite often.

❌ Bad: Doing maths on asset IDs.

```gml
// BAD: Analyzer only sees 'spr_player_base', misses the rest
draw_sprite(spr_player_base + current_animation, image_index, x, y)
```

This logic relies on Game Maker's internal resource order. While the order was made much more predictable in Game Maker 8.2's modern save format, it is still a bit hidden and should not be used in general.

❌ Bad: String execution.

```gml
// BAD: Analyzer cannot trace the boss asset
execute_string(str_cat("instance_create(x, y, obj_boss_", current_level,")"))
```

`execute_string` requires Game Maker to parse it and build an AST at runtime, which is slow. Any dynamic code execution should generally be limited to functions like `variable_*`, and those should never reference assets.

Let's take a look at how to fix such things:

✅ Good: Use explicit references directly

```gml
// GOOD: All assets are explicitly declared and mapped
switch current_level {{
    case "forest": instance_create(x, y, obj_boss_forest) break
    case "volcano": instance_create(x, y, obj_boss_volcano) break
}}
```

✅ Good:
```gml
var _amb;
_amb[0] = "sfx_ambience0"
_amb[1] = "sfx_ambience1"
_amb[2] = "sfx_ambience2"
_amb[3] = "sfx_ambience3"
_amb[4] = "sfx_ambience4"

sound_loop(_amb[irandom(4)])
```

### Building dependency flow

A healthy dependency graph flows in one direction: Stage-specific assets may reference Common assets, but Common assets cannot hardcode references to Stage-specific assets. Therefore, any sort of ubiquitous object (like the Player or World) should remain agnostic to the stages they occupy. Let's look at the example.

The Ice Stage of the game contains new special spikes that fall from the ceiling. You created a new object: `SpikeIce`. Now you have to make the Player take damage and freeze when they touch it. Sounds easy!

❌ Bad:

```gml
///Player.Step
if place_meeting(x, y, SpikeIce) {{
    player_take_damage()
    player_freeze()
}}
```

Now the Player directly references `SpikeIce`. The {exs.href('ex_lint_crossref', 'analyzer')} will flag this, because the Player now requires the `SpikeIce` asset (and, therefore, all of it's referenced assets down the line, such as its sprite) to be loaded globally.

This can be solved in a few ways.

**Version 1 - Moving the logic from Common to Stage-specific**

Just invert the logic - make the spikes damage the player, instead of the player checking for spikes:

```gml
///IceSpike.Step
if place_meeting(x, y, Player) {{
    player_take_damage()
    player_freeze()
}}
```

This works (and is the best solution in many cases), but I bet this game has some other damage sources. How about we...

**Version 2 - Turn explicit reference into implicit**

... introduce a new Common object `ParentHazard`, and simply make the original Player logic poll for hazards, instead of specific spikes:

```gml
///Player.Step
var _hazard;
_hazard = place_meeting(x, y, ParentHazard)
if _hazard {{
    player_take_damage()
    if _hazard.freeze player_freeze()
}}
```

This is also a valid solution in many cases.

___

Now let's think of something less trivial. The Player now gains the ability to use spells, and the Ice Stage adds ice magic when picking up a certain powerup, implemented like this:

❌ Bad:

```gml
///Player.KeyPress_50

if global.Powerups[powerup_shield] {{
    // Common spell
    instance_create(x, y, ProjectileShield)
}}

if global.Powerups[powerup_spell_ice] {{
    // Ice Stage spell
    instance_create_moving(x, y, ProjectileIcicle, 1, 270, 0.2)
}}
```

You can already see the Common to Stage-specific reference.

**Version 1 - Moving the logic from Common to Stage-specific**

Make picking up a spell spawn an Ice Stage-bound object `SpellIcicle`, which houses the logic for shooting it.

```gml
///SpellIcicle.KeyPress_50
with Player {{
    //handle the case when player doesn't exist (dead)
    instance_create_moving(x, y, ProjectileIcicle, 1, 270, 0.2)
}}
```

Now the Player doesn't know about `ProjectileIcicle`. This solution works well for small, isolated gimmicks. However, if you want to combine the logic of several Stage-specific things, keeping a perfect dependency flow might be impossible. For such cases, we introduce...

**Version 2 - Context-aware logic**

Imagine now we want to assign spells to different keys and make sure the Player can't use an icicle while having a shield up or a new multistage spell "Blizzard" (existing in a cluster `CommonNorth`, which is accessed by both Ice Stage and Tundra Stage) is active. To punish spell abuse, you decide to add logic for Player freezing to death when spamming cold spells.

This logic can be implemented as an abstract "temperature" variable on the Player, or it can be put into a controller object. Such as `ControllerSpellsNorth`:

```gml
///ControllerSpellsNorth.Create
freezing = 0

///ControllerSpellsNorth.Step
//unfreeze over time
freezing = approach(freezing, 0, 0.05)

///SpellIcicle.KeyPress_50
if room_is_ice() {{
    with Player {{
        //spawn the icicle projectile
        instance_create_moving(x, y, ProjectileIcicle, 1, 270, 0.2)

        //lower the chill
        other.freezing -= 10

        //check if frozen
        if other.freezing < -30 {{
            player_kill(killcause_freeze)
        }}
    }}
}}

///SpellIcicle.KeyPress_51
with Player {{
    //spawn the blizzard projectile
    instance_create(x, y, ProjectileBlizzard)

    other.freezing -= 20

    if other.freezing < -30 {{
        player_kill(killcause_freeze)
    }}
}}
```

A few things to digest from here:

1. `ControllerSpellsNorth` is now an object from `CommonNorth` as well - therefore it is totally allowed to reference any other asset from `CommonNorth`. After all, when the `CommonNorth` cluster is loaded, everything from it becomes available.
2. The new function `room_is_ice` - is not just an ordinary "location check script". It can be used as a "Context Guard" in Clunkster's analyzer. We can assign it a target cluster that this script guards behind itself (the `IceStage` in our case):
```python
CONTEXT_RULES: dict[str, set[str]] = {{
    # guard for ice stage -specific things
    'room_is_ice': {{
        'IceStage'

        # notice that we don't put any other more
        # "common" stages in here
    }},

    # guard for things that are allowed in CommonNorth,
    # but don't require any more specific logic
    # (e.g. from IceStage)
    'room_is_north': {{
        'CommonNorth'
    }}
}}
```
Now everything protected by this guard can freely reference any `IceStage` asset.

3. Since anything from the `CommonNorth` cluster should, logically, be available anywhere in `IceStage`, we must also define this behavior in a different config:
```python
LINT_RULES: dict[str, set[str]] = {{
    # common assets cannot borrow from Stage specific folders
    'Common': {{'Common'}},

    'IceStage': {{
        # explicitly include the common cluster
        'Common',

        # include the regional common cluster
        'CommonNorth',

        # include anything from itself
        'IceStage',
    }},

    # this will make any Ice Stage room load all 3 of those clusters

    # btw, default value for any cluster is a set of "Common" and
    #  the cluster itself
}}
```
Now everything in `CommonNorth` can be freely accessed by `IceStage`.

> Tip: The attentive ones among you have likely noticed that this same trick can be applied to a World object, making it viable again. As a matter of fact, having multiple persistent controller objects is quite bad - you'll see in a bit.

Here's the sample implementation of those context guards.

```gml
///room_is_ice([room])
//Check whether the given room is from Ice Stage

var _room;
if argument_count == 0 {{
    if global._clunkster_reg_mode return 1

    //optionally, if you are applying this tool onto an existing project,
    //you might want to temporarily bypass the guard, until you fix
    //all the initial bugs (ACTUALLY NOT RECOMMENDED)
    //return 1 //TEMP

    _room = room
}}
else {{
    _room = argument[0]
}}

switch _room {{
case rIceIntro:
case rIceBarrage:
    return 1
default:
    return 0
}}
```

Notice that weird `global._clunkster_reg_mode` at the top. This is a secret tool that might come in handy later.

When you need a guard for things shared between several zones, you can implement it like this:

```gml
///room_is_north([room])
//Checks whether the room is a part of North stages (Ice, Tundra, etc.)

if argument_count==0 {{
    if clunkster_is_reg() return 1

    //return 1 //TEMP

    //call without args
    if (
        room_is_ice() or
        room_is_tundra()
    ) return 1
}}
else {{
    var _room;_room=argument[0]
    if (
        room_is_ice(_room) or
        room_is_tundra(_room)
    ) return 1
}}

return 0
```

> Note: Clunkster is very sensitive to exact way you call the context guards in code. Guarded region must start with a line `if guard() {{` and end with just closing brackets on their own line `}}`. You can't use guards with parameters in regular code, you can't pair them with any sort of boolean logic, and you are not allowed to use parenthesis outside (like `if (guard()) {{`).

### Timelines

Convert them to `switch` statements.

```gml
///Obj.Create
time=0

///Obj.Step
time+=1

switch time {{
case 20:
    ... //code on Step 20
    break
case 100:
    ... //code on Step 100
    break
}}
```

### State contamination via Globals and Persistence

Now that we've handled the easy cases, let's look onto some that are less obvious (and harder to trace, since they won't get flagged in linters).

Global variables and persistent objects can cross cluster boundaries, making them vectors for dependency leaks.

❌ Bad: Passing a specific asset through a global variable or constant.

```gml
global.next_cutscene_actor = StageB_NpcFairy
```

If the Player enters Stage A, this reference will linger, and the analyzer won't be able to catch it. If the Player instantiates this reference in Stage A:

```gml
instance_create(x, y, global.next_cutscene_actor)
```

... it could potentially produce a broken stub-asset behavior if the Stage B has been unloaded.

❌ Bad: Overusing Persistence

Persistent objects act similarly to global variables. If you do something like:
```gml
with WeatherBlizzard {{
    ControllerWeather.current_weather = id
}}
```
and then `WeatherBlizzard`'s home cluster `CommonNorth` gets unloaded, you might get the same result as the previous example.

✅ Good: Pass abstract strings or enums and let a stage-specific non-persistent director object spawn the correct asset locally.

```gml
///StageB_NpcFairySpawner.Step
if global.next_cutscene_actor == "fairy" {{
    instance_create(x, y, StageB_NpcFairy)
    global.next_cutscene_actor = ""
}}
```

Don't forget to register all persistent objects in `EXTRA_ROOTS`:
```python
EXTRA_ROOTS: set[str] = {{
    'World'
    # ...
}}
```

〰️ Kinda ok: Having persistent objects with no potential instantiating references to assets that may become unloaded. Things like room transitions. Cases like this could be fine for you, but Clunkster's linters won't be able to detect oversights.

As a side note, all dependencies of each Extra Root will be merged with dependency graph of **every** room, so unless you wanna deal with humongous dependency graphs, keep your persistent controllers minimal. Ideally, just one `World` object.

### Proper use of the Ignore Pragma

We provide a pragma for ignoring files during dependency scans: `//!clunkster: ignore`. You should only use it on pure data registries that define metadata without instantiating objects.

❌ Bad: Skipping Your Homework

```gml
///Player.Collision_ForestLog

//eeehhh i need to convert collision with stage-specific object event
// into an End Step event + rip all that boolean logic, hide every
// call behind a guard or something ehhhh

//i dont feel like doin it :3
//!clunkster: ignore

with Player  {{
    save_set_persistent("deaths", save_get("deaths") + 1)
    if global.player_skin == "knight" instance_create(x, y, Knight_BloodEmitter)
    else if instance_exists(mario_kart) instance_create(mario_kart.x, mario_kart.y+24, BloodEmitter)
    else instance_create(x, y, BloodEmitter)
    if (global.darkStage) {{
        dark_gib_sound(1)
    }}
    else {{
        sound_play("player_death")

        // Dance specific
        if is_in_game() && !global.paused {{
            if room != rDanceStage {{
                camera_update()
            }} else {{
                dance_camera_update()
            }}
        }}
    }}
    instance_create(0, 0, GameOver)
    instance_destroy()
}}
```

❌ Bad: Putting instantiating references into _registries_ (= making them impure)

```gml
///music_register()
//Register EVERY music in here
//!clunkster: ignore

music_def_begin("musStageTutorial",0.8)
    music_def_room(rTutorial,mus_autoplay)
    music_def_room(rTutorialBoss,mus_fadeout)
    music_def_room(rFinal_Respite,mus_autoplay)
music_def_end()

///World.RoomStart

//autostart music
_l_auto=dsmap(global._mus_room_auto,room)
if not is_undefined(_l_auto) {{
    _s=ds_list_size(_l_auto)

    for (_i=0;_i<_s;_i+=1) {{
        _snd=ds_list_find_value(_l_auto,_i)

        //BAD!!! The reference that was hidden from the linter
        // is now being passed into the instantiating function.
        // Since Clunkster has no idea that rFinal_Respite needed
        // "musTitle", it might put it into a cluster that
        // rFinal_Respite has no access too, playing you an
        // unloaded stub asset.
        // Woe be upon you.
        music_play(_snd)
    }}
}}
```

✅ Good: Make registries only define pure data and non-instantiating references.

```gml
///music_register()
//Register EVERY music in here
//!clunkster: ignore

music_def_begin("musTitle")
    music_def_volume(0.8)
    music_def_og_samplerate(44100)
    music_def_loop(31*44100 + 19422, 70*44100 + 28955)

    //instead of defining autoplay logic in registry,
    // autoplay logic can be moved into a different file
    // without the "ignore" pragma

    //but we can still keep logic like "make sure the track is
    // stopped when we enter any room other than this".
    // sound_stop(...) is not an instantiating function,
    // and will work just fine if this specific sound
    // was replaced with a stub "null.wav"
    music_def_room_allowed(rTitle, rOptions, rFinal_Respite)
music_def_end()
```

✅ Good: Guard instantiating registry logic.

```gml
///music_register()
//Register EVERY music in here

// notice: the ignore is gone

if room_is_tutorial_or_final() {{
    //anything shared between tutorial and final stage

    music_def_begin("musStageTutorial",0.8)
        music_def_room(rTutorial,mus_autoplay)
        music_def_room(rTutorialBoss,mus_fadeout)
        music_def_room(rFinal_Respite,mus_autoplay)

        //Important: since we also violate one of our other principles
        // "Don't pass references across cluster boundaries through globals",
        // we must validate that all the rooms actually belong to the cluster
        assert(room_is_tutorial_or_final(rTutorial))
        assert(room_is_tutorial_or_final(rTutorialBoss))
        assert(room_is_tutorial_or_final(rFinal_Respite))
    music_def_end()
}}
```

And, since this registry script runs only on game start, in order to not loose data that we've deliberately hidden behind guard (in Init room they'd all return 0...), we can introduce a little _hack_ that doesn't ruin our cluster model.

Remember the `global._clunkster_reg_mode` from before? Here's our plan:

New script `clunkster_init`:

```gml
///clunkster_init()
global._clunkster_reg_mode = 0

//any other initialization logic might be
// autogenerated by Clunkster and added here
```

New script `clunkster_registry_begin`:

```gml
///clunkster_registry_begin()
global._clunkster_reg_mode = 1
```

New script `clunkster_registry_end`:

```gml
///clunkster_registry_end()
global._clunkster_reg_mode = 0
```

And here's how we will call the registries in Game Start:

```gml
clunkster_registry_begin()
    sound_register()
    music_register()
clunkster_registry_end()
```

And guards should intelligently silence themselves if used as context guards in registry mode, but still do proper validation if they were given an actual room:

```gml
///room_is_tutorial_or_final([room])
//Check whether the given room is from Tutorial or Final Stage

var _room;
if argument_count == 0 {{
    if global._clunkster_reg_mode return 1

    _room = room
}}
else {{
    _room = argument[0]
}}

switch _room {{
case rTutorial:
case rTutorialBoss:
case rFinal_Respite:
    return 1
default:
    return 0
}}
```

More info on them scripts can be found in the [GML](#integration-into-the-game) chapter.

## Dehydration

Following terms are used:

- prepare: the process of stripping the asset from the project (compile step).
- store-dry-prod: how the stripped asset is represented inside resulting prod build (invisible stubs).
- store-dry-dev: how the stripped asset is represented inside resulting dev build (stubs that yell loudly when referenced).
- store-wet: how the actual data is stored externally.
- hydrate: the process of dynamically loading wet assets back into memory at runtime.
- dehydrate: the process of unloading the assets from memory at runtime.

___

**Backgrounds**: impactful, high priority.

- prepare: use [`gmcodec`](https://github.com/shaperones0/gmcodec) to generate `.gmbck` files.
- store-dry-prod: transparent 2x2.
- store-dry-dev: pink-black checkerboard with transparent padding
- store-wet: `.gmbck` files.
- hydrate: use `background_replace_background` to load externally.
- dehydrate: use `background_replace_background` to replace back with dry stub.
____
**Fonts**: not numerous enough to be impactful, difficult.
____
**Objects**: slightly impactful, risky (and difficult).
____
**Paths**: not impactful.
____
**Room**: not impactful, risky.
____
**Scripts**: impossible to create dynamically without big rewrites.
____
**Sprites**: impactful, high priority.

- prepare: use [`gmcodec`](https://github.com/shaperones0/gmcodec) to generate `.gmspr` files
- store-dry-prod: transparent 2x2 with same number of frames as original.
- store-dry-dev: pink-black checkerboard with transparent padding.
- store-wet: `.gmspr` files.
- hydrate: use `sprite_replace_sprite` to load externally.
- dehydrate: use `sprite_replace_sprite` to replace back with dry stub.
____
**Sounds**: impactful, TODO.
____
**External audio**: impactful, high priority.

- prepare:

    - put sounds from same cluster into their folders,
    - generate a script that loads every sound as `null.wav` (or `buzz.wav`) via `sound_add_ext` on game start,
    - convert ogg into compressed (level 2 or 3)
    - wav is mostly unchanged

- store-dry-dev: gm82snd doesn't require files to be present, so we "store" them as manually initialized audio via `buzz.wav` for sounds and `fiddlesticks.mp3` for music, in a script ran on game start (apply correct file extension).
- store-dry-prod: same as above, except `null.wav` files for both.
- store-wet: just files sitting in their external folders.
- hydrate: run the loader script.
- dehydrate: replace back with stubs.

{head.header_parse('## Juicing', 'h_juicing')}

For the Game Juicer we have to add a sort-of pre-compile step for the game. The goal is, simply put, to copy most of the project and apply dehydration to the assets that require it.

To elaborate:

- we only do dehydration of sprites, backgrounds and external audio (builtin sounds aren't implemented yet (TODO), other asset types aren't impactful enough to bother)
- dynamic loading of sprites and backgrounds presents us with a few game maker bugs that we need to address:

    - objects don't update their mask after mask's sprite got replaced, simple `maks_index=mask_index` in Room Start does the trick
    - rooms' backgrounds stretch flag is compile-time, but, since, I believe, in most projects it is not used often enough, all those rooms can just be fixed manually by hardcoding correct xscale and yscale for the backgrounds. If they are, in fact, numerous, then you could have a dynamic backgrounds resize code added into the Room Creation Code:
```gml
if background_width[0]>0 && background_height[0]>0 {{
    background_xscale[0]=room_width/background_width[0]
    background_yscale[0]=room_height/background_height[0]
}}
```

- since for some games Juicing is the only way to run, builds must be fast:

    - processing tasks must support caching
    - asset dirs without processing can be symlinked
    - heavy tasks (audio compression, image encoding) should be multiprocessed
    - copy tasks (numerous but IO-bound) can be put into threading

The requirements for "fast builds" are implemented in Clunkster through the system of "tasks" and "caching". Base of these is done in the library's respective pipeline abstraction (`task.py`, `cache.py`), actual implementation examples can be found in {exs.href('ex_juicer_processing', 'Juicer classes example')}.

With that said, the project building strategy becomes:

- do an `iterdir` on project root

    - if element is a folder

        - if it belongs to an asset type that needs processing (smartly handle data folder)

            - generate processing/copy tasks

        - otherwise

            - check if this folder is allowed to exist in the project
            - symlink

    - if element is a file

        - check if this file is allowed to exist in the project
        - copy

- execute the tasks (notice which things are tasks and which aren't)

    - multiprocessing for processing tasks (image encoding, audio compression)
    - threading for copy tasks

Speaking of building, one more note on how the built game is structured. By default, wet assets are stored in `data/chunks/<cluster>/<whatever was their
original path relative to the project root>`.

{head.header_parse('## Pipeline architecture', 'h_pipeline_architecture')}

Pipeline has a number of systems and abstractions that run all throughout examples and might appear confusing. The deal behind was about solving few annoying issues:

1. We should be able to run our asset processing logic in parallel, for more expensive / IO-bound operations, without loosing the ability to report on the progress (status prints, progress bars).
2. We should be able to have different interfaces (CLI mode / TUI mode (not implemented yet but would be rad af)).

Following outlines our solutions. Most of them are housed in [pipeline folder](https://github.com/shaperones0/clunkster/tree/main/clunkster/pipeline).

- `task.py`: Task encapsulates information needed for processing logic, input and output files for build caching and house the `execute` method that actually does the thing.
- `cache.py`: The aforementioned build cache system. The build cache is saved into JSON file. Tasks, whose output files are present, and input files haven't changed, are skipped.
- `executor`: Module that houses fancy task execution logic - they take list of tasks and run them in a special way.

    - `executor/base.py`: Shared util logic.
    - `executor/mp.py`: Multiprocessing executor.
    - `executor/thread.py`: Threading executor.

- `events`: Workers need to output information (task started/finished, progress), and in order to bring that information into the main thread (UI) we use a system of events.

    - `events/event.py`: The actual event models.
    - `events/dispatcher.py`: Event dispatchers. In order to handle events user must register callbacks for each event type. Dispatchers only exist on the main process.
    - `events/sink.py`: Sink are where workers send their events. Regular `DispatchEventSink` simply passes the event to underlying dispatcher. However, concurrent executors implement their own sinks:

        - threading executor's sinks share a lock, which they activate before invoking underlying dispatcher.
        - multiprocessing executor's sink doesn't send events to dispatcher, but rather to underlying queue, shared with the main thread. Main process polls this queue in a separate thread (main thread of the main process handles waiting for futures to finish their job), and from this queue things are pushed into the dispatcher (see `QueueEventReceiver`).

    - `events/context.py`: This is the unified execution context given to workers. Contains their event sink and whatever other metadata belogs there.

The flow of things in multiprocessing case can be expressed by this diagram:

```mermaid
graph TD
    subgraph Worker Processes
        W1[Worker 1: Task Execution]
        W2[Worker 2: Task Execution]

        S1[QueueEventSink<br/>Injects PID/Thread ID]
        S2[QueueEventSink<br/>Injects PID/Thread ID]

        W1 -- "emit(TaskFinished)" --> S1
        W2 -- "emit(TaskFinished)" --> S2
    end

    Q[(multiprocessing.Queue)]

    S1 -->|Puts WorkerEvent| Q
    S2 -->|Puts WorkerEvent| Q

    subgraph Main Process
        R[QueueEventReceiver<br/>Daemon Thread]
        D[EventDispatcher]
        UI["UI logic<br/>(UiRichAsync/UiSimpleAsync)"]

        Q -- "Pops Event" --> R
        R -- "dispatch(event)" --> D
        D -- "Triggers Handlers" --> UI
    end

    UI -- "Renders Table & Progress" --> Term[Terminal Output]
```

With simple and justifiable systems out of the way, next things might seem questionable:

- `ui`: UI abstraction system.

    - `ui/base.py`: Abstract UI class, automatically registers its own methods as dispatcher's handlers.
    - `ui/simple.py`: Simple UI implementation, using prints.
    - `ui/adapter.py`: Given synchronous pipeline steps an easy interface over events and dispatchers via `ui_out` (print replacement) and `ui_progress` (progress bar over a sequence).

The flow of things considering UI abstraction, in sync case, can be represented like this:

```mermaid
graph TD
    subgraph Pipeline Code
        Step["Pipeline Step Function<br/>@ui_auto_sink('StepName')"]
        UI_PROG["ui_progress(assets)"]
        UI_OUT["ui_out('Status message')"]

        Step --> UI_PROG
        Step --> UI_OUT
    end

    subgraph Convenience Layer
        SA[SinkAdapter<br/>Global 'ADAPTER' Instance]
    end

    subgraph Mario Room
        DS[DirectEventSink]
        ED[EventDispatcher]
        UI_SYNC[UI Component<br/>UiRich / UiSimple]
    end

    UI_PROG -- "Generates Events<br/>(Start, Advance, End)" --> SA
    UI_OUT -- "Generates Event<br/>(Status)" --> SA

    SA -- "emit(event)" --> DS
    DS -- "Passthrough into Dispatcher" --> ED
    ED -- "Triggers Handlers" --> UI_SYNC
    UI_SYNC -- "Renders" --> Term[Terminal Output]
```

You'll encounter UI implementation with simple `print`-based output, as well as [rich](https://rich.readthedocs.io/en/latest/introduction.html) in the examples.

Full example of a synchronous pipeline step can be found here: {exs.href('ex_setup_example')}.

Full example of concurrents can be found here: {exs.href('ex_juicer_run')}.

## Integration into the game

In order to integrate Clunkster into your project you'll have to create a couple of GML scripts. Some of them will be autogenerated in Game Juicer and its derivatives. Default flow delegated loading to when the room change is requested (in `room_goto`), and unloading to the Room Start event (when all assets from previous clusters are definitely unloaded). This results in 1-2 second stutters when changing clusters, which I'd imagine won't be an issue, especially if such room changes have transitions like black-out-black-in.

Here's the static scripts that you'll have to add:

- `clunkster_init()`: Initialized Clunkster's variables.
- `clunkster_room_start()`: Clunkster's Room Start event, cleans up all unneeded assets.
- `clunkster_room_goto(target_room)`: A `room_goto` replacement that ensures all assets are loaded for target room.
- `clunkster_registry_begin()`: Toggles registry mode on.
- `clunkster_is_reg()`: Returns registry mode status.
- `clunkster_registry_end()`: Toggles registry mode off.

And the following scripts will be autogenerated. You should still add them - their contents are populated in the GML generation step: {exs.href('ex_juicer_gen_gml')}. In raw project those are usually empty.

- `clunkster_gen_type()`: Returns `"dev"` or `"prod"` in a built project. Returns `""` in the raw source project.
- `clunkster_gen_init_audio()`: Initializes audio stubs.
- `clunkster_gen_get_room_clusters(target_room)`: Populates the required cluster map.
- `clunkster_gen_hydrate_cluster(cluster_name)`: Loads assets.
- `clunkster_gen_dehydrate_cluster(cluster_name)`: Unloads assets (replaces them with dry stubs to reduce RAM).
- `clunkster_gen_validate_ctx()`: Validation script that runs on Game Start and checks that [context guards](#building-dependency-flow) correctly guard their rooms.

Following describes the base implementation of those scripts, as well as notes on what kinds of changes should be made to the project in order for these to work.

1. `clunkster_init()` - Initializes Clunkster logic

    ```gml
    ///clunkster_init()
    //Initialize Clunkster globals

    global.__clunk_reg_mode=0
    global.__clunk_active_clusters=ds_map_create()
    global.__clunk_req_clusters=ds_map_create()

    clunkster_gen_validate_ctx()
    ```

    See example of proper Game Start logic below.

2. `clunkster_room_start()` - System's Room Start event, responsible for cleaning up unloaded assets.

    ```gml
    ///clunkster_room_start()
    //Clunkster's Room Start event
    //Cleanup cluster no longer needed for this room

    var _key,_next;
    _key=ds_map_find_first(global.__clunk_active_clusters)

    while is_string(_key) {{
        _next=ds_map_find_next(global.__clunk_active_clusters,_key)
        if not ds_map_exists(global.__clunk_req_clusters,_key) {{
            //this cluster is no longer needed
            clunkster_gen_dehydrate_cluster(_key)
            ds_map_delete(global.__clunk_active_clusters,_key)
        }}
        _key=_next
    }}
    ```

    Put it in World's Room Start at the top.

3. `clunkster_room_goto(target_room)` - Interceptor of `room_goto` calls, which is responsible for loading any asset required by target room.

    ```gml
    ///clunkster_room_goto(room)
    //Intercept room_goto and load necessary clusters

    ds_map_clear(global.__clunk_req_clusters)
    clunkster_gen_get_room_clusters(argument0)

    var _key;
    _key=ds_map_find_first(global.__clunk_req_clusters)
    repeat ds_map_size(global.__clunk_req_clusters) {{
        if !ds_map_exists(global.__clunk_active_clusters,_key) {{
            //must be loaded
            clunkster_gen_hydrate_cluster(_key)
            ds_map_add(global.__clunk_active_clusters,_key,1)
        }}
        _key=ds_map_find_next(global.__clunk_req_clusters,_key)
    }}

    room_goto(argument0)
    ```

    You'll have to replace every `room_goto` call with this function, and never use any other methods of room change.

    Next are registry-related functions.

4. `clunkster_registry_begin()` - Switch registry mode ON.

    ```gml
    ///clunkster_registry_begin()

    global.__clunk_reg_mode=1
    ```

5. `clunkster_registry_end()` - Switch registry mode OFF.

    ```gml
    ///clunkster_registry_end()

    global.__clunk_reg_mode=0
    ```

6. `clunkster_is_reg()` - Check whether in registry mode.

    ```gml
    ///clunkster_is_reg()
    //Check whether in registry mode

    return global.__clunk_reg_mode
    ```

    And finally, the autogenerated scripts. In raw project they remain mostly empty.

7. `clunkster_gen_type()`

    ```gml
    ///clunkster_gen_type()
    //Returns the type of project.
    //Expect "dev" for builds with no dynamic asset loading
    //Expect "prod" for builds with dynamic asset loading
    //Expect "" for raw projects

    //This script is autogenerated by Clunkster.

    return ""
    ```

8. `clunkster_gen_init_audio()`

    ```gml
    ///clunkster_gen_init_audio()
    //Initialize audio sources with stubs
    //sound_add_ext("null.wav",kind,streamed,"snd_actual")

    //This script is autogenerated by Clunkster.
    ```

9. `clunkster_gen_get_room_clusters(target_room)`

    ```gml
    ///clunkster_gen_get_room_clusters(target_room)
    //Get clusters that must be loaded for given room
    //Populates global.__clunk_req_clusters

    //This script is autogenerated by Clunkster.
    ```

10. `clunkster_gen_hydrate_cluster(cluster_name)`

    ```gml
    ///clunkster_gen_hydrate_cluster(cluster_name)
    //Loads data from specified cluster in one block

    //This script is autogenerated by Clunkster.
    ```

11. `clunkster_gen_dehydrate_cluster(cluster_name)`

    ```gml
    ///clunkster_gen_dehydrate_cluster(cluster_name)
    //Unloads data from specified cluster in one block

    //This script is autogenerated by Clunkster.
    ```

12. `clunkster_gen_validate_ctx()`

    ```gml
    ///clunkster_gen_validate_ctx()
    //Validates context guards

    //This script is autogenerated by Clunkster.
    ```

What are the registries? Basically, if you wanna have some values associated with a externalized resource, that should be applied whenever its loaded, you can simply put such data in a `dsmap` and add some logic for loading and applying those values.

For example, if you have some values associated with audio source (like volume balancing, original sample rate, loops), you can create a registry, like this `sndreg`:

`sndreg_init`:

```gml
///sndreg_init()
//Initialize sound registry

global._sndreg=ds_map_create()
global._sndlist=ds_list_create()
```

`sndreg_ext` - Fills in all data of an audio at once:

```gml
///sndreg_ext(snd,og_samplerate=44100,vol=1,[loopstart,loopend=-1])
//Fill in all params at once

//reg
if !ds_map_exists(global._sndreg,argument0+":REG") {{
    ds_list_add(global._sndlist,argument0)
    dsmap(global._sndreg,argument0+":REG",1)
}}

//rate
//NOTE: I recommend avoiding unit_samples and unit_seconds, as FMOD's
// native format is unit_unitary
var _rate;if argument_count>1 _rate=argument[1] else _rate=44100
dsmap(global._sndreg,argument0+":RATE",_rate)

//vol
var _vol;if argument_count>2 _vol=argument[2] else _vol=1
dsmap(global._sndreg,argument0+":VOL",_vol)

//loop
if argument_count>3 {{
    dsmap(global._sndreg,argument0+":LA",argument[3])
    var _le;
    if argument_count>4 _le=argument[4] else _le=-1
    dsmap(global._sndreg,argument0+":LB",_le)
}}
```

`sndreg_populate` - This is where you define all those values:

```gml
///sndreg_populate()
//Populate sound registry with necessary sound data

sndreg_ext("block_break",44100)
sndreg_ext("block_change",44100,0.8)
sndreg_ext("boss_hit",44100,0.8)
sndreg_ext("cherry_trap",44100,0.6)
sndreg_ext("get_item",44100)
sndreg_ext("glass",44100)

if room_is_ice_stage() {{
    sndreg_ext("ice_melt",44100)
}}
```

`sndreg_apply` - Apply registry values to a sound:

```gml
///sndreg_apply(snd)
if sound_exists(argument0) {{
    //volume
    var _vol;_vol=dsmap(global._sndreg,argument0+":VOL")
    if is_undefined(_vol) _vol=1
    sound_volume(argument0,_vol)

    //loop
    var _ls;_ls=dsmap(global._sndreg,argument0+":LA")
    if not is_undefined(_ls) {{
        var _le;_le=dsmap(global._sndreg,argument0+":LB")
        if is_undefined(_le) _le=-1

        //scale samplerate to account for compression
        var _scaled_start,_scaled_end;
        _scaled_start=sndreg_scale_sample(argument0,_ls)

        if _le==-1 {{
            _scaled_end=sound_get_length(argument0,unit_samples)
        }}
        else {{
            _scaled_end=sndreg_scale_sample(argument0,_le)
        }}
        sound_set_loop(
            argument0,
            _scaled_start,_scaled_end,unit_samples
        )
    }}
}}
else {{
    show_error(str_ins(
        "sndreg_apply: Sound '%' doesn't exist",argument0
    ),0)
}}
```

`sndreg_apply_all` - Apply registry values to all registered sounds; this one should be used right after registry population, if project type is raw.

```gml
///sndreg_apply_all()
//Apply audio stuff to all sounds

var _i,_ac,_snd;
_ac=ds_list_size(global._sndlist)
for (_i=0;_i<_ac;_i+=1) {{
    _snd=ds_list_find_value(global._sndlist,_i)
    sndreg_apply(_snd)
}}
```

This allows us to write a clean Game Start logic:

```gml
clunkster_registry_begin()
sndreg_populate()
clunkster_registry_end()
if clunkster_gen_type() == "" {{
    //all audio is internal and loaded, run audio balance
    sndreg_apply_all()
}}
else {{
    //we are in 'dev' or 'prod' build, generate stubs
    clunkster_gen_init_audio()
}}
```
"""  # noqa: S608


def txt_reference(
    snips: dict[str, list[Snippet]],
    head: doc_headers.ExampleHeaderManager,
    docs: dict[str, str],
    exs: doc_code.CodeGenerator,
) -> str:
    """Generate reference."""
    return f"""
{head.file_begin('reference.md')}

{head.header_parse('# Reference', 'h_reference')}
"""


def txt_examples(
    snips: dict[str, list[Snippet]],
    head: doc_headers.ExampleHeaderManager,
    docs: dict[str, str],
    exs: doc_code.CodeGenerator,
) -> str:
    """Generate examples."""
    return f"""
{exs.file_begin('examples.md')}

{head.header_parse('# Examples', 'h_examples')}

Examples are generated from the [main pipeline file](https://github.com/shaperones0/clunkster/blob/master/main.py), and represent parts of the workflow for the game this tool was initially build for. The game structure is [Verve GM8.2 Engine](https://github.com/iwVerve/Verve-GM82-Engine) for IWBTG fangames, though changing that should be easy.

{head.section_next('Setting up').render_header()}

This is the setup section. It covers settings up the project, linters, and other pipeline shims. Of these, mandatory ones are:

- Project
- Widgets

{exs.code_begin('ex_setup_main', 'Setup: Project')}
{docs['main_ex_setup_main']}
{
        exs.render(
            (
                snips['PROJECT'],
                snips['MAIN_EX_SETUP_MAIN'],
            )
        )
    }
{
        exs.code_reg_stub_src(
            {
                'PROJECT': gen_stub_var('PROJECT: Path', 'LINT: my_lint.LinterSession'),
            }
        )
    }

{exs.code_begin('ex_setup_widgets', 'Setup: Widgets')}
{docs['main_ex_setup_widgets']}
{
        exs.render(
            (
                snips['CLS_WIDGETS'],
                snips['WIDGETS'],
                snips['MAIN_EX_SETUP_WIDGETS'],
            )
        )
    }
{
        exs.code_reg_stub_src(
            {
                'CLS_WIDGETS': '\n'.join(
                    (
                        gen_stub_cls('WidgetRenderer'),
                        gen_stub_func('global_widget_renderer'),
                    )
                ),
                'WIDGETS': '\n'.join(
                    (
                        gen_stub_cls('WidgetRenderer'),
                        gen_stub_var('WIDGET: WidgetRenderer'),
                    )
                ),
            }
        )
    }

With that out of the way you may start the {exs.href('ex_start', 'first real examples')}. However, I recommend reading a bit about the {head.header_href('h_pipeline_architecture', 'pipeline architecture')}, which should give you proper understanding on what to do if things don't work out.

{exs.code_begin('ex_setup_rich', 'Setup: Rich UI')}
{docs['main_ex_setup_rich']}
{
        exs.render(
            (
                exs.stub('CLS_WIDGETS'),
                snips['UI_RICH'],
                snips['MAIN_EX_SETUP_RICH'],
            )
        )
    }

{exs.code_begin('ex_setup_example', 'Full example (pipeline excerpt)')}

Following is the full example of integrating UI logic into a pipeline step, taken from `main.py` (where you can look for more thorough examples as well).

{
        exs.render(
            (
                s_py('CLS_UI: type[my_ui_base.Ui] = my_ui_simple.UiSimple\nCLS_UI_ASYNC: type[my_ui_base.UiAsync] = my_ui_simple.UiSimpleAsync'),
                snips['DEF_EXAMPLE'],
            )
        )
    }
{
        exs.code_reg_stub_src(
            {
                'GLOB_CLS_UI': gen_stub_var('CLS_UI: type[my_ui_base.Ui]', 'CLS_UI_ASYNC: type[my_ui_base.Ui]'),
            }
        )
    }

{head.section_next('Reading project').render_header()}

This section is about discovering assets from project files, doing initial
validations and assigning clusters to the assets.

{exs.code_begin('ex_start', 'Finding assets')}

{docs['main_ex_start']}
{
        exs.render(
            (
                exs.stub('PROJECT'),
                snips['CLS_ASSET_EXT'],
                snips['CLUSTERABLE_ASSETS'],
                snips['MAIN_EX_START'],
            )
        )
    }
{
        exs.code_reg_stub_src(
            {
                'CLS_ASSET_EXT': gen_stub_cls(
                    'AssetExtAudio',
                    'AssetExtBgm',
                    'AssetExtSfx',
                    'AssetExtSfx3',
                ),
            }
        )
    }

{exs.code_begin('ex_lint_tree', 'Lint: `tree.yyd` files')}

{docs['main_ex_lint_tree']}
{
        exs.render(
            (
                exs.stub('PROJECT'),
                exs.stub('CLS_ASSET_EXT'),
                snips['CLS_LINT_TREE'],
                snips['CLUSTERABLE_ASSETS'],
                snips['MAIN_EX_LINT_TREE'],
            )
        )
    }

{exs.code_begin('ex_aliases', 'Clusters')}
{docs['main_ex_aliases']}
{
        exs.render(
            (
                exs.stub('PROJECT'),
                exs.stub('WIDGETS'),
                exs.stub('CLS_ASSET_EXT'),
                snips['ALIAS'],
                snips['DEF_ASSET_CLUSTERS'],
                snips['CLS_LINT_ALIAS'],
                snips['CLUSTERABLE_ASSETS'],
                snips['MAIN_EX_ALIASES'],
            )
        )
    }

{
        exs.code_reg_stub_src(
            {
                'VAR_ASSETS': gen_stub_var('assets: list[Asset]'),
                'DEF_ASSET_CLUSTERS': gen_stub_func('asset_cluster_raw', 'asset_cluster'),
            }
        )
    }

{head.section_next('References').render_header()}

This section is about finding asset references in `.gml` files, and running
validations based on them.

{exs.code_begin('ex_scan_sync', 'Reference scanning')}
{docs['main_ex_scan_sync']}
{
        exs.render(
            (
                exs.stub('PROJECT'),
                exs.stub('CLS_ASSET_EXT'),
                exs.stub('DEF_ASSET_CLUSTERS'),
                snips['DEF_ASSET_SCANNABLES'],
                snips['CLS_DEPENDENCY'],
                exs.stub('VAR_ASSETS'),
                snips['MAIN_EX_SCAN_SYNC'],
            )
        )
    }

{
        exs.code_reg_stub_src(
            {
                'CLS_DEPENDENCY': gen_stub_cls('Dependency'),
                'VAR_DEPS': gen_stub_var('dependencies: list[Dependency]'),
                'DEF_ASSET_SCANNABLES': gen_stub_func('asset_scannables'),
            }
        )
    }

{exs.code_begin('ex_lint_unused', 'Lint: unused assets')}
{docs['main_ex_lint_unused']}
{
        exs.render(
            (
                exs.stub('PROJECT'),
                exs.stub('CLS_ASSET_EXT'),
                exs.stub('DEF_ASSET_CLUSTERS'),
                snips['DEF_ASSET_SORT_KEY'],
                exs.stub('CLS_DEPENDENCY'),
                snips['CLS_LINT_ASSET_CLUSTER'],
                snips['CLS_LINT_UNUSED'],
                exs.stub('VAR_ASSETS'),
                exs.stub('VAR_DEPS'),
                snips['MAIN_EX_LINT_UNUSED'],
            )
        )
    }

{
        exs.code_reg_stub_src(
            {
                'CLS_LINT_ASSET_CLUSTER': gen_stub_cls('LintAssetCluster'),
                'CLS_LINT_UNUSED': gen_stub_cls('LintUnused'),
                'DEF_ASSET_SORT_KEY': gen_stub_func('asset_sort_key'),
            }
        )
    }

{exs.code_begin('ex_lint_crossref', 'Lint: cross-cluster references')}
{docs['main_ex_lint_crossref']}
{
        exs.render(
            (
                exs.stub('PROJECT'),
                snips['LINT_RULES'],
                snips['CONTEXT_RULES'],
                exs.stub('CLS_ASSET_EXT'),
                exs.stub('DEF_ASSET_CLUSTERS'),
                exs.stub('CLS_DEPENDENCY'),
                exs.stub('CLS_LINT_ASSET_CLUSTER'),
                snips['CLS_LINT_CROSSREF'],
                exs.stub('VAR_DEPS'),
                snips['MAIN_EX_LINT_CROSSREF'],
            )
        )
    }

{
        exs.code_reg_stub_src(
            {
                'LINT_RULES': gen_stub_var('LINT_RULES: dict[str, set[str]]'),
                'CONTEXT_RULES': gen_stub_var('CONTEXT_RULES: dict[str, set[str]]'),
            }
        )
    }

Normally, cleaning these up can take up to several days. I recommend giving {head.header_href('h_prerequisites', 'Prerequisites')} a read - there are useful cleanup examples, as well as some explanations on how to write `LINT_RULES` and `CONTEXT_RULES`.

{head.section_next('Dependency Graph').render_header()}

This section is about building a graph out of dependencies, and running
checks based on more advanced usage tracing.

{exs.code_begin('ex_graph', 'Generate dependency graphs')}
{docs['main_ex_graph']}
{
        exs.render(
            (
                exs.stub('LINT_RULES'),
                exs.stub('CONTEXT_RULES'),
                snips['EXTRA_ROOTS'],
                exs.stub('CLS_ASSET_EXT'),
                exs.stub('DEF_ASSET_CLUSTERS'),
                exs.stub('CLS_DEPENDENCY'),
                snips['CLS_ROOM_GRAPH'],
                exs.stub('VAR_ASSETS'),
                exs.stub('VAR_DEPS'),
                snips['MAIN_EX_GRAPH'],
            )
        )
    }

{
        exs.code_reg_stub_src(
            {
                'VAR_ROOM_DATA': gen_stub_var('room_graph_data: dict[str, RoomGraph]'),
                'EXTRA_ROOTS': gen_stub_var('EXTRA_ROOTS: set[str]'),
                'CLS_ROOM_GRAPH': gen_stub_cls('RoomGraph'),
            }
        )
    }

{exs.code_begin('ex_lint_unused_graph', 'Lint: unreachable assets')}
{docs['main_ex_lint_unused_graph']}
{
        exs.render(
            (
                exs.stub('PROJECT'),
                exs.stub('LINT_RULES'),
                exs.stub('CONTEXT_RULES'),
                exs.stub('EXTRA_ROOTS'),
                exs.stub('CLS_ASSET_EXT'),
                exs.stub('CLS_DEPENDENCY'),
                exs.stub('CLS_ROOM_GRAPH'),
                exs.stub('CLS_LINT_UNUSED'),
                exs.stub('VAR_ASSETS'),
                exs.stub('VAR_DEPS'),
                exs.stub('VAR_ROOM_DATA'),
                snips['MAIN_EX_LINT_UNUSED_GRAPH'],
            )
        )
    }

{exs.code_begin('ex_lint_crossref_graph', 'Lint: room cluster boundaries')}
{docs['main_ex_lint_crossref_graph']}
{
        exs.render(
            (
                exs.stub('PROJECT'),
                exs.stub('LINT_RULES'),
                exs.stub('CONTEXT_RULES'),
                exs.stub('EXTRA_ROOTS'),
                exs.stub('CLS_ASSET_EXT'),
                exs.stub('DEF_ASSET_CLUSTERS'),
                exs.stub('DEF_ASSET_SORT_KEY'),
                exs.stub('CLS_DEPENDENCY'),
                exs.stub('CLS_ROOM_GRAPH'),
                snips['CLS_LINT_CROSSREF_GRAPH'],
                exs.stub('VAR_ASSETS'),
                exs.stub('VAR_DEPS'),
                exs.stub('VAR_ROOM_DATA'),
                snips['MAIN_EX_LINT_CROSSREF_GRAPH'],
            )
        )
    }

{head.section_next('Game Juicer').render_header()}

Now that the project is cleared out, it is time for some useful tools.

In this section we will be working on Game Juicer. You can read more on exact strategies in {head.header_href('h_juicing', 'Juicing')}. While this exact tool only requires the list of assets (see example: {exs.href('ex_aliases', 'clusters')}), the game must satisfy both clusterization linters (see: {exs.href('ex_lint_crossref')} and {exs.href('ex_lint_crossref_graph')}) in order for the resulting build to run well.

Note: current method of compressing audio uses [ffmpeg](https://www.ffmpeg.org/), make sure it is installed and is accessible through PATH.

{exs.code_begin('ex_juicer_processing', 'Juicer: the juice')}

This example is a bit bigger than usual, mostly because before we get to execute any meaningful code we must define a fair bit of classes and functions.

{docs['main_juicer_processing']}
{exs.render((exs.stub('CLS_ASSET_EXT'), snips['DEFS_JUICE']))}

___

{docs['main_juicer_classes']}
{
        exs.render(
            (
                exs.stub('CLS_ASSET_EXT'),
                exs.stub('DEFS_JUICE'),
                snips['DEF_ASSET_WET_FNAME'],
                snips['CLS_JUICE_TASKS'],
            )
        )
    }

Notice how none of both of the functions or Tasks above depend on `PROJECT`, or any other global state. Awesome!

___

{docs['main_juicer_gen_tasks']}
{
        exs.render(
            (
                exs.stub('PROJECT'),
                exs.stub('CLS_ASSET_EXT'),
                exs.stub('DEF_ASSET_CLUSTERS'),
                exs.stub('CLS_JUICE_TASKS'),
                snips['CLS_JUICE_BUILD_TASKS'],
                snips['CLS_JUICER_CONFIG'],
                exs.stub('VAR_ASSETS'),
                snips['MAIN_JUICER_GEN_TASKS'],
            )
        )
    }

{
        exs.code_reg_stub_src(
            {
                'DEFS_JUICE': gen_stub_func(
                    'juice_sprite',
                    'juice_background',
                    'juice_audio',
                    'juice_obj_fix_mask',
                ),
                'CLS_JUICE_TASKS': gen_stub_cls(
                    'TaskEncodeSprite',
                    'TaskEncodeBackground',
                    'TaskCompressAudio',
                    'TaskFixMaskObjects',
                ),
                'DEF_ASSET_WET_FNAME': gen_stub_func('asset_wet_fname'),
                'CLS_JUICE_BUILD_TASKS': gen_stub_cls('BuildTasks'),
                'CLS_JUICER_CONFIG': '\n'.join(
                    (
                        gen_stub_cls('ConfJuicer'),
                        gen_stub_var('JUICER: ConfJuicer'),
                    )
                ),
                'VAR_JUICE_BUILD_TASKS': '\n'.join(
                    (
                        gen_stub_cls('BuildTasks'),
                        gen_stub_var('tasks: BuildTasks'),
                    )
                ),
            }
        )
    }

{exs.code_begin('ex_juicer_run', 'Juicer: running the tasks')}
{docs['main_juicer_run']}
{
        exs.render(
            (
                exs.stub('GLOB_CLS_UI'),
                exs.stub('VAR_JUICE_BUILD_TASKS'),
                exs.stub('CLS_JUICER_CONFIG'),
                snips['MAIN_JUICER_RUN'],
            )
        )
    }

{exs.code_begin('ex_juicer_gen_gml', 'Juicer: generate the `.gml` files')}
{docs['main_juicer_gen_gml']}
{
        exs.render(
            (
                exs.stub('LINT_RULES'),
                exs.stub('CONTEXT_RULES'),
                exs.stub('CLS_ASSET_EXT'),
                exs.stub('DEF_ASSET_CLUSTERS'),
                exs.stub('DEF_ASSET_WET_FNAME'),
                exs.stub('CLS_JUICER_CONFIG'),
                exs.stub('VAR_ASSETS'),
                snips['MAIN_JUICER_GEN_GML'],
            )
        )
    }

{exs.code_begin('ex_juicer_gm_compile', 'Juicer: compile and launch')}
{docs['main_juicer_gm_compile']}
{
        exs.render(
            (
                exs.stub('CLS_JUICER_CONFIG'),
                snips['MAIN_JUICER_GM_COMPILE'],
            )
        )
    }

"""


def _main() -> None:  # noqa: C901
    file_main = Path(__file__).parent.parent / 'main.py'
    txt_main = file_main.read_text(encoding='utf-8')
    lines_main = txt_main.splitlines()
    snips = doc_extract.extract(doc_parse.parse(lines_main))
    head = doc_headers.ExampleHeaderManager(idx_major_start=-1)
    docs = doc_docstring.extract(txt_main)
    exs = doc_code.CodeGenerator.from_text(
        txt_main,
        header_manager=head,
    )

    kwargs = {
        'snips': snips,
        'head': head,
        'docs': docs,
        'exs': exs,
    }

    dir_docs = Path(__file__).parent.parent / 'docs_md'

    file_to_parser: dict[Path, doc_patch.FuncParser] = {
        Path(__file__).parent.parent / 'README.md': doc_patch.FuncParser.from_func(txt_readme),
        dir_docs / 'index.md': doc_patch.FuncParser.from_func(txt_overview),
        dir_docs / 'rationale.md': doc_patch.FuncParser.from_func(txt_rationale),
        dir_docs / 'examples.md': doc_patch.FuncParser.from_func(txt_examples),
        dir_docs / 'reference.md': doc_patch.FuncParser.from_func(txt_reference),
    }

    iterations = 0
    iterations_max = 10

    parsers = list(file_to_parser.values())

    def is_ok() -> bool:
        return all(_parser.is_resolved() for _parser in parsers)

    while iterations < iterations_max:
        iterations += 1

        for parser in parsers:
            parser.execute(**kwargs)

        if is_ok():
            break

    if not is_ok():
        error_msg = f'Template failed to resolve after {iterations_max} passes. Unresolved snippets:'

        for parser in parsers:
            for part in parser.parts:
                if not isinstance(part, doc_patch.FstringPartCode):
                    continue
                if part.err is None:
                    continue
                error_msg += f'\n- {parser.func.__name__}: {{{part.code_str}}} failed with {type(part.err).__name__}: {part.err}'  # ty: ignore[unresolved-attribute]

        raise RuntimeError(error_msg)

    for file, parser in file_to_parser.items():
        file.write_text(parser.render_str().replace('```gml', '```js'), encoding='utf-8')

    print('Docs generated.')


if __name__ == '__main__':
    _main()
