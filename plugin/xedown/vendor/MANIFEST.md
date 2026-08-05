# Vendored dependencies

Regenerate with `scripts/update-vendor.sh` from the repository root. Everything in
this directory is third-party code; nothing here is written by this project.

| Dependency | Version | License | Location |
| --- | --- | --- | --- |
| Python-Markdown | 3.7 | BSD-3-Clause | `markdown/`, `licenses/python-markdown-LICENSE.md` |
| highlight.js | 11.11.1 | BSD-3-Clause | `highlight.min.js`, `licenses/highlight.js-LICENSE` |
| highlight.js themes | 11.11.1 | BSD-3-Clause | `../resources/highlight-light.css`, `../resources/highlight-dark.css` |

Built with esbuild 0.24.0.

## Bundled languages (31)

bash, c, cpp, csharp, css, diff, dockerfile, go, ini, java, javascript, json,
kotlin, lua, makefile, markdown, objectivec, perl, php, plaintext, python, r,
ruby, rust, scss, shell, sql, swift, typescript, xml, yaml

`update-vendor.sh` fails if the built bundle does not register exactly this set.
Changing the list is a deliberate release decision, not an incidental edit.
