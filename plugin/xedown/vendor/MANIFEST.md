# Vendored dependencies

Regenerate with `scripts/update-vendor.sh` from the repository root. Everything in
this directory is third-party code; nothing here is written by this project.

| Dependency | Version | License | Location |
| --- | --- | --- | --- |
| Python-Markdown | 3.7 | BSD-3-Clause | `markdown/`, `licenses/python-markdown-LICENSE.md` |
| highlight.js | 11.11.1 | BSD-3-Clause | `highlight.min.js`, `licenses/highlight.js-LICENSE` |
| highlight.js themes | 11.11.1 | BSD-3-Clause | `../resources/highlight-light.css`, `../resources/highlight-dark.css` |

The two highlight.js stylesheets are the **Repository** theme's syntax layer
and nothing else. xedown's other three themes author their own syntax palettes,
through `../resources/syntax.css` plus per-theme variables. Repository keeps
this one because it must stay identical to xedown 0.1.0, whose code colours are
these files — transcribing them into a hand-written stylesheet would drop the
attribution this licence requires.

Built with esbuild 0.24.0.

## Bundled languages (31)

bash, c, cpp, csharp, css, diff, dockerfile, go, ini, java, javascript, json,
kotlin, lua, makefile, markdown, objectivec, perl, php, plaintext, python, r,
ruby, rust, scss, shell, sql, swift, typescript, xml, yaml

`update-vendor.sh` fails if the built bundle does not register exactly this set.
Changing the list is a deliberate release decision, not an incidental edit.
