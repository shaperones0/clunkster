"""Unit tests for GML parser."""

from clunkster.parse.gml import GmlIndex

# --- Ignored Ranges Tests (Strings and Comments) ---


def test_ignore_line_comments() -> None:
    """Ignored range test (line comments)."""
    code = """
    var a = 5; // This is a comment containing obj_player
    var b = 10;
    """
    index = GmlIndex.from_text(code)

    assert index.is_ignored_at(code.find('var a')) is False, (
        'Should not ignore actual code'
    )
    assert index.is_ignored_at(code.find('obj_player')) is True, (
        'Should ignore text inside the comment'
    )


def test_ignore_block_comments() -> None:
    """Ignored range test (block comments)."""
    code = """
    /*
       if stageA() {
           instance_create(x, y, obj_boss);
       }
    */
    var c = obj_player;
    """
    index = GmlIndex.from_text(code)

    assert index.is_ignored_at(code.find('obj_boss')) is True
    assert index.is_ignored_at(code.find('obj_player')) is False
    assert index.get_contexts_at(code.find('obj_player')) == (), (
        'Block comment should not trigger a context'
    )


def test_ignore_strings() -> None:
    """Ignored range test (strings)."""
    code = """
    draw_text(x, y, "Find the { obj_secret }");
    var name = 'obj_enemy';
    """
    index = GmlIndex.from_text(code)

    assert index.is_ignored_at(code.find('obj_secret')) is True
    assert index.is_ignored_at(code.find('obj_enemy')) is True
    assert index.is_ignored_at(code.find('draw_text')) is False


# --- Guard Contexts Tests ---


def test_single_guard_context() -> None:
    """Contexts (single)."""
    code = """
    var global_var = 1;
    if stageA() {
        var local_var = 2;
    }
    var global_var_2 = 3;
    """
    index = GmlIndex.from_text(code)

    assert index.get_contexts_at(code.find('global_var = 1')) == ()
    assert index.get_contexts_at(code.find('local_var = 2')) == ('stageA',)
    assert index.get_contexts_at(code.find('global_var_2 = 3')) == ()


def test_nested_guard_contexts() -> None:
    """Contexts (nested)."""
    code = """
    if level1() {
        var a = 1;
        if boss_room() {
            var b = 2;
        }
        var c = 3;
    }
    """
    index = GmlIndex.from_text(code)

    assert index.get_contexts_at(code.find('a = 1')) == ('level1',)
    assert index.get_contexts_at(code.find('b = 2')) == ('level1', 'boss_room')
    assert index.get_contexts_at(code.find('c = 3')) == ('level1',)


def test_standard_blocks_inside_guards() -> None:
    """Contexts (normal block inside guards)."""
    code = """
    if stageB() {
        if (x > 50) {
            var a = 1;
        }
        var b = 2;
    }
    """
    index = GmlIndex.from_text(code)

    assert index.get_contexts_at(code.find('a = 1')) == ('stageB',), (
        'Both standard blocks and root blocks inside '
        'the guard should share the context'
    )
    assert index.get_contexts_at(code.find('b = 2')) == ('stageB',)


# --- Edge Cases ---


def test_brackets_inside_strings_do_not_break_depth() -> None:
    """Edge case (brackets inside ignored range)."""
    code = """
    if stageC() {
        var msg = "This string has an } in it";
        var a = 1;
    }
    var b = 2;
    """
    index = GmlIndex.from_text(code)

    assert index.get_contexts_at(code.find('a = 1')) == ('stageC',)
    assert index.get_contexts_at(code.find('b = 2')) == (), (
        'Closing bracket inside string should not be parsed'
    )


def test_guards_inside_comments_do_not_trigger() -> None:
    """Edge case (guards inside ignored range)."""
    code = """
    // if disabledStage() {
    var a = 1;
    // }
    """
    index = GmlIndex.from_text(code)

    assert index.get_contexts_at(code.find('a = 1')) == ()


def test_multiple_consecutive_guards() -> None:
    """Contexts (consecutive)."""
    code = """
    if stage1() { var a = 1; }
    if stage2() { var b = 2; }
    """
    index = GmlIndex.from_text(code)

    assert index.get_contexts_at(code.find('a = 1')) == ('stage1',)
    assert index.get_contexts_at(code.find('b = 2')) == ('stage2',)


# --- Boundary Condition Tests ---


def test_boundaries_of_contexts() -> None:
    """Contexts (boundary test)."""
    code = 'var a=1; if stg() { var b=1; } var c=1;'
    index = GmlIndex.from_text(code)

    brace_idx = code.find('{')
    assert index.get_contexts_at(brace_idx - 1) == (), (
        'Context before opening bracket should be global'
    )

    assert index.get_contexts_at(brace_idx + 1) == ('stg',), (
        'Context after opening bracket should be stg'
    )

    rbrace_idx = code.find('}')
    assert index.get_contexts_at(rbrace_idx - 1) == ('stg',), (
        'Context before closing bracket should be stg'
    )

    assert index.get_contexts_at(rbrace_idx + 1) == (), (
        'Context after closing bracket should be global'
    )
