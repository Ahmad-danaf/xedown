# Security

xedown is intended to safely preview Markdown, including files you did not
write yourself. Markdown content should be displayed, never executed. If you
are considering installing the plugin, see [Known issues](docs/known-issues.md)
for documented limitations and accepted residual risks.

## Report a vulnerability

**Do not open a public issue for a suspected security vulnerability.** Use
GitHub's private vulnerability reporting instead:

1. Open the repository's **Security** tab.
2. Select **Report a vulnerability**.
3. Describe the issue and attach a minimal Markdown file that reproduces it,
   if possible.

Include the xedown release, xed version, WebKitGTK version, expected behavior,
and actual behavior when available. If you cannot use private vulnerability
reporting, open a public issue asking for a private contact method without
including vulnerability details or a proof of concept.

The project is maintained by one person in their spare time. Reports will be
acknowledged when possible, but there is no guaranteed response or fix
timeline and no bug bounty. Reporters may be credited if they wish.

## Supported versions

Security fixes are made only for the latest release. Users should upgrade to
the newest version before reporting a vulnerability or requesting a backport.

## Scope

Reports are welcome for vulnerabilities caused by xedown, including:

- content or script execution from a Markdown document;
- sanitizer or link-confirmation bypasses;
- unexpected file access or modification;
- network requests that bypass the remote-image controls; and
- preview content affecting xed outside the preview pane.

The following are generally outside the project's security scope:

- issues already documented in [Known issues](docs/known-issues.md), unless
  their impact is greater than documented;
- behavior that requires an attacker to already run code as your user;
- performance problems without a demonstrated security impact;
- scanner output without a working path through xedown; and
- vulnerabilities in xed or WebKitGTK that also occur without xedown.

Contributors working on rendering, sanitization, links, or remote images
should preserve the security boundaries described in
[Markdown compatibility](docs/markdown-compatibility.md),
[Remote images](docs/remote-images.md), and [Themes](docs/themes.md). Security
regression tests are in `tests/unit/test_security.py`.
