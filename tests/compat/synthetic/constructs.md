<!-- Systematic construct battery.

     This document exists to give a later measurement something to measure.
     kbd, dl, dt, dd, caption and abbr occur ZERO times in the 31-README
     corpus, so an allowlist before/after re-run over the corpus alone would
     report 0 -> 0 for them and prove nothing about whether the widening
     worked. The elements below are the only occurrences in the whole audit
     set, and they are what a re-run has to move.

     The ordered-list, escape and line-break sections cover marker and inline
     forms the corpus exercises only incidentally, so a regression in them
     would otherwise go unnoticed. Trailing whitespace on the "line three"
     line is significant: it is the two-space hard line break. -->

# Constructs

## Ordered list markers

Dot marker, starting at one.

1. First
2. Second
3. Third

Paren marker, starting at one. A separating paragraph keeps this a new list
rather than a continuation of the one above.

1) First
2) Second
3) Third

Dot marker, starting at seven.

7. Seven
8. Eight

Paren marker, starting at seven.

7) Seven
8) Eight

Every marker written as one, which a renderer must still number 1, 2, 3.

1. One
1. Also one
1. Still one

## Hard line breaks

A backslash at the end of the line:

line one\
line two

Two trailing spaces at the end of the line:

line three  
line four

## Backslash escapes

Escaped punctuation: \*not emphasis\*, \_not emphasis\_, \# not a heading,
and \[not a link\](nowhere).

A literal backslash in a path: C:\\Users\\reader.

## Definition list

<dl>
  <dt>Term</dt>
  <dd>Definition of the term.</dd>
  <dt>Second term</dt>
  <dd>Another definition.</dd>
</dl>

## Keyboard input

Press <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>M</kbd> to toggle the preview.

## Abbreviation

The <abbr title="Cascading Style Sheets">CSS</abbr> is inlined into the page.

## Table with a caption

<table>
  <caption>Supported ordered-list markers</caption>
  <tr><th>Marker</th><th>Meaning</th></tr>
  <tr><td>1.</td><td>Ordered, dot</td></tr>
  <tr><td>1)</td><td>Ordered, paren</td></tr>
</table>
