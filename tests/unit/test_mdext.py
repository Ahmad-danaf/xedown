import pytest
from xedown import vendoring
from xedown.mdext import make_extensions


@pytest.fixture
def convert():
    markdown_module = vendoring.import_markdown()

    def _convert(text):
        md = markdown_module.Markdown(
            extensions=list(vendoring.MARKDOWN_EXTENSIONS)
            + make_extensions(markdown_module)
        )
        return md.convert(text)

    return _convert


def test_unchecked_task_becomes_a_disabled_checkbox(convert):
    html = convert("- [ ] buy milk")
    assert "<input" in html
    assert "checked" not in html
    assert "buy milk" in html
    assert "[ ]" not in html


def test_checked_task_becomes_a_checked_checkbox(convert):
    html = convert("- [x] done thing")
    assert "checked" in html
    assert "done thing" in html
    assert "[x]" not in html


def test_uppercase_checked_marker_is_accepted(convert):
    assert "checked" in convert("- [X] done")


def test_task_items_carry_marker_classes(convert):
    html = convert("- [ ] a\n- [x] b")
    assert "task-list" in html


def test_ordinary_list_items_are_untouched(convert):
    html = convert("- plain item")
    assert "<input" not in html
    assert "plain item" in html


def test_bracket_text_that_is_not_a_task_is_left_alone(convert):
    html = convert("- [link](http://example.com) trailing")
    assert "<input" not in html
    assert 'href="http://example.com"' in html


def test_strikethrough_becomes_del(convert):
    html = convert("~~gone~~")
    assert "<del>gone</del>" in html


def test_single_tildes_are_not_strikethrough(convert):
    assert "<del>" not in convert("a ~b~ c")


def test_strikethrough_inside_a_list_item_works(convert):
    assert "<del>x</del>" in convert("- ~~x~~")


def test_tables_and_fenced_code_still_work_alongside(convert):
    html = convert("| a |\n|---|\n| 1 |\n\n```python\nx=1\n```")
    assert "<table>" in html
    assert 'class="language-python"' in html
