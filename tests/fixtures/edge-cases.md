# Xedown Edge Cases

The deliberately hostile document used by the manual smoke test. Every
broken reference below is intentional test coverage, not a mistake — see
[README.md](README.md) in this directory before "fixing" any of it. For a
document that renders cleanly instead, see
[showcase.md](showcase.md).

## Missing local image

This path does not exist on disk. Expected: an inline placeholder naming
the path, with no blank space left behind.

![Missing image](pics/does-not-exist.png)

## Remote image, never fetched

Expected: a placeholder naming the blocked address. Nothing here is ever
fetched over the network — check with a network monitor if in doubt.

![Remote image](https://example.com/not-fetched.png)

## Link to a nonexistent file

Expected: the click is refused, with a message naming the path — not a
silent failure.

[A link to a file that is not there](does-not-exist.md)

## Fenced code in a language outside the bundled 31

`brainfuck` is not one of the 31 bundled highlight.js languages. Expected:
the block still renders, as plain unhighlighted text — it must not break
the page.

```brainfuck
++++++++[>++++[>++>+++>+++>+<<<<-]>+>+>->>+[<]<-]>>.
```

## Fenced code with no language at all

Expected: same as above — a plain styled block, no highlighting, no error.

```
plain text inside a fence, with no language tag
```

## Known GFM gap: a list does not interrupt a paragraph

This is a known defect, not a mistake — it is tracked in
[docs/known-issues.md](../../docs/known-issues.md) for v0.2. The paragraph
and the two list markers immediately below have **no blank line** between
them. Under GFM this should end the paragraph and start a two-item list;
under xedown v0.1 it currently does **not** — the three lines render as one
single paragraph instead. Do not "fix" this by inserting a blank line
before the first `-`; that would delete the only place this defect is
exercised.

A paragraph immediately followed by a list, with no blank line before it.
- item one
- item two

## Bidirectional text

Basic bidirectional text correctness, not full right-to-left support: each
block below picks its own base direction from its first strong character.

### Arabic paragraph

هذه فقرة باللغة العربية. يجب أن تبدأ من اليمين وأن تُقرأ بالترتيب الصحيح
تمامًا.

### Mixed Arabic and English paragraph

فقرة مختلطة: نستخدم Python و Markdown في هذا المشروع، والنص يجب أن يبقى
مرتبًا بصريًا رغم اختلاط الاتجاهين.

### عنوان باللغة العربية

Arabic heading, immediately above, in an `<h3>`.

### Arabic blockquote

> اقتباس باللغة العربية يجب أن يكون محاذيًا إلى اليمين مثل باقي النص.

### Arabic list

- عنصر أول في القائمة
- عنصر ثانٍ
- عنصر ثالث

### Table with Arabic cells

| الميزة | الحالة |
| --- | --- |
| المعاينة | جاهزة |
| الوضع الليلي | مدعوم |

### Inline code inside an Arabic sentence

The trickiest inline case — the code span must sit correctly without
scrambling the Arabic text around it:

قم بتشغيل الأمر `git status --short` ثم تابع العمل كالمعتاد.

### Arabic comments inside a Python fence

The case most likely to regress: this fenced block must stay
left-to-right, with every line starting at the left edge, even though its
comments are Arabic.

```python
# هذه دالة بسيطة لحساب المجموع
def total(items):
    # نجمع القيم ثم نعيد النتيجة
    return sum(items)
```

If this code block reads right-to-left, or its lines start from the right
edge, that is a bug in the bidirectional-text handling.
