/* The only script permitted to run in the preview. */
(function () {
  "use strict";

  var CONTENT_ID = "xedown-content";

  var DEFAULT_CONFIG = { codeCopy: true, imageDisplay: "placeholder" };
  var MAX_COPY_CHARS = 1048576;
  var COPY_ANSWER_MS = 1500;
  var COPY_REVERT_MS = 1500;

  /* The exact text the author wrote, captured before highlight() rewrites
     the block. Keyed by the <code> element and thrown away with it. */
  var sources = new WeakMap();
  var pendingCopies = {};
  var nextCopyToken = 0;

  var config = readConfig();

  function readConfig() {
    var merged = {
      codeCopy: DEFAULT_CONFIG.codeCopy,
      imageDisplay: DEFAULT_CONFIG.imageDisplay
    };
    try {
      var supplied = window.xedownConfig || {};
      if (typeof supplied.codeCopy === "boolean") { merged.codeCopy = supplied.codeCopy; }
      if (typeof supplied.imageDisplay === "string") {
        merged.imageDisplay = supplied.imageDisplay;
      }
    } catch (e) {
      /* A page rendered without a config block still works. */
    }
    return merged;
  }

  /* The host's route to a page that is already loaded: a settings change
     must not need a reload to be seen. */
  function setConfig(partial) {
    if (!partial) { return; }
    if (typeof partial.codeCopy === "boolean") { config.codeCopy = partial.codeCopy; }
    if (typeof partial.imageDisplay === "string") {
      config.imageDisplay = partial.imageDisplay;
    }
    applyCodeCopy(content() || document.body);
  }

  function content() {
    return document.getElementById(CONTENT_ID);
  }

  function post(payload) {
    try {
      if (window.webkit && window.webkit.messageHandlers &&
          window.webkit.messageHandlers.xedown) {
        window.webkit.messageHandlers.xedown.postMessage(JSON.stringify(payload));
      }
    } catch (e) {
      /* The host is absent (for example when previewing the page directly). */
    }
  }

  function prefersReducedMotion() {
    try {
      return typeof window.matchMedia === "function" &&
        window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    } catch (e) {
      return false;
    }
  }

  function highlight(root) {
    if (typeof hljs === "undefined") { return; }
    var engine = hljs.default || hljs;
    var blocks = root.querySelectorAll("pre > code");
    for (var i = 0; i < blocks.length; i++) {
      var block = blocks[i];
      var declared = null;
      var classes = (block.className || "").split(/\s+/);
      for (var c = 0; c < classes.length; c++) {
        if (classes[c].indexOf("language-") === 0) {
          declared = classes[c].slice("language-".length);
        }
      }
      /* No language, or one outside the bundle, renders as a plain block.
         The bundle throws on unregistered languages, so guard both ways. */
      if (!declared || !engine.getLanguage(declared)) { continue; }
      try {
        var result = engine.highlight(block.textContent, { language: declared });
        block.innerHTML = result.value;
        block.classList.add("hljs");
      } catch (e) {
        /* Leave the block unhighlighted rather than breaking the document. */
      }
    }
  }

  function captureSources(root) {
    var blocks = root.querySelectorAll("pre > code");
    for (var i = 0; i < blocks.length; i++) {
      var text = blocks[i].textContent || "";
      /* The newline before a closing fence is a delimiter, not code. */
      if (text.charAt(text.length - 1) === "\n") { text = text.slice(0, -1); }
      /* textContent can never contain "\r": the text reaching the renderer
         already came from a GtkTextBuffer, which holds "\n" regardless of
         the file's line endings and restores the original ending on save,
         and Python-Markdown strips any carriage return that survives that
         while building the HTML, so none ever reaches the page. So this
         always matches what selecting and copying in the source view would
         return -- there is no CRLF to preserve at this layer. */
      sources.set(blocks[i], text);
    }
  }

  /* The button is a sibling of <pre>, never a child: <pre> scrolls
     horizontally, and a child would slide out of view on a long line. */
  function wrapCodeBlocks(root) {
    var blocks = root.querySelectorAll("pre > code");
    for (var i = 0; i < blocks.length; i++) {
      var pre = blocks[i].parentNode;
      if (!pre || !pre.parentNode) { continue; }
      if (pre.parentNode.className === "xedown-code-block") { continue; }
      var wrapper = document.createElement("div");
      wrapper.className = "xedown-code-block";
      pre.parentNode.insertBefore(wrapper, pre);
      wrapper.appendChild(pre);
    }
  }

  function applyCodeCopy(root) {
    var wrappers = root.querySelectorAll(".xedown-code-block");
    for (var i = 0; i < wrappers.length; i++) {
      var existing = wrappers[i].querySelector(".xedown-copy");
      if (!config.codeCopy) {
        /* Removed, not hidden: nothing left to focus, find or copy. */
        if (existing) { existing.parentNode.removeChild(existing); }
      } else if (!existing) {
        wrappers[i].appendChild(makeCopyButton());
      }
    }
  }

  function makeCopyButton() {
    var button = document.createElement("button");
    button.type = "button";
    button.className = "xedown-copy";
    setCopyLabel(button, "Copy");
    button.addEventListener("click", function () { requestCopy(button); });
    return button;
  }

  function setCopyLabel(button, label) {
    button.textContent = label;
    button.setAttribute("aria-label", label === "Copy" ? "Copy code" : label);
  }

  function requestCopy(button) {
    var wrapper = button.parentNode;
    var block = wrapper ? wrapper.querySelector("pre > code") : null;
    var text = block ? sources.get(block) : null;
    if (typeof text !== "string" || text.length > MAX_COPY_CHARS) {
      finishCopy(button, false);
      return;
    }
    nextCopyToken += 1;
    var token = nextCopyToken;
    pendingCopies[token] = button;
    post({ type: "copy", token: token, text: text });
    /* post() silently does nothing when the host is absent -- which is the
       case for a page opened straight in a browser -- so an unanswered
       click has to resolve by itself rather than sit on "Copy" forever. */
    window.setTimeout(function () {
      if (pendingCopies[token]) { copyResult(token, false); }
    }, COPY_ANSWER_MS);
  }

  function copyResult(token, ok) {
    var button = pendingCopies[token];
    if (!button) { return; }
    delete pendingCopies[token];
    finishCopy(button, ok);
  }

  function finishCopy(button, ok) {
    setCopyLabel(button, ok ? "Copied" : "Copy failed");
    window.setTimeout(function () { setCopyLabel(button, "Copy"); }, COPY_REVERT_MS);
  }

  /* Remote images are meant to be replaced with a placeholder before this
     page ever sees them (the CSP also blocks the request as a second layer),
     but this handler still tells the two failure causes apart in case a
     remote reference ever reaches the DOM: readers need to know whether a
     file is missing versus whether the plugin refused to fetch it. */
  function isRemoteSource(src) {
    return /^https?:\/\//i.test(src);
  }

  function brokenImageMessage(src) {
    if (isRemoteSource(src)) { return "Remote image, not fetched: " + src; }
    /* The renderer already replaced anything it could see was missing, so
       reaching here means the file was there at render time: it vanished
       since, or it is not a decodable image. Either way it could not be
       read. */
    return "Image could not be read: " + src;
  }

  function brokenImageReplacement(source, alt) {
    if (config.imageDisplay === "hidden") { return null; }
    var span = document.createElement("span");
    if (config.imageDisplay === "alt") {
      if (!alt) { return null; }
      span.className = "xedown-image-alt";
      span.textContent = alt;
      return span;
    }
    span.className = "xedown-image-error";
    span.textContent = brokenImageMessage(source) +
      (alt ? " — “" + alt + "”" : "");
    return span;
  }

  function markBrokenImage(image) {
    if (!image.parentNode) { return; }
    var source = image.getAttribute("src") || "(no source)";
    var replacement = brokenImageReplacement(source, image.getAttribute("alt") || "");
    if (replacement === null) {
      image.parentNode.removeChild(image);
    } else {
      image.parentNode.replaceChild(replacement, image);
    }
    post({ type: "imageError", src: source });
  }

  function watchImages(root) {
    var images = root.querySelectorAll("img");
    for (var i = 0; i < images.length; i++) {
      (function (image) {
        image.addEventListener("error", function () { markBrokenImage(image); });
        if (image.complete && image.naturalWidth === 0) { markBrokenImage(image); }
      })(images[i]);
    }
  }

  function toggleClass(element, name, on) {
    if (on) { element.classList.add(name); } else { element.classList.remove(name); }
  }

  /* Each side is cued only while that side has more to show, read from the
     live scroll position rather than assumed from the width. Mid-scroll both
     sides have more, so both classes are set at once -- preview.css's
     combined ".xedown-more-left.xedown-more-right" selector is what paints
     that state. The 1px slack absorbs sub-pixel layout, which would
     otherwise leave a shadow showing at a hard stop.

     The class names are physical because the shadow is. Which physical side
     has more content is not: in a right-to-left container the resting
     position is 0 with the content overflowing to the LEFT, and scrollLeft
     runs negative from there. So the distance travelled is the magnitude,
     and the container's own direction decides which side that uncovers. */
  function isRightToLeft(element) {
    try {
      return window.getComputedStyle(element).direction === "rtl";
    } catch (e) {
      return false;
    }
  }

  function updateTableCue(wrapper) {
    var limit = wrapper.scrollWidth - wrapper.clientWidth;
    var travelled = Math.abs(wrapper.scrollLeft);
    var rtl = isRightToLeft(wrapper);
    var moreBehind = travelled > 1;
    var moreAhead = travelled < limit - 1;
    toggleClass(wrapper, "xedown-more-left", rtl ? moreAhead : moreBehind);
    toggleClass(wrapper, "xedown-more-right", rtl ? moreBehind : moreAhead);
  }

  function watchTable(wrapper) {
    wrapper.addEventListener("scroll", function () { updateTableCue(wrapper); });
    /* The window can be resized until a table that fitted no longer does. */
    if (typeof ResizeObserver === "function") {
      new ResizeObserver(function () { updateTableCue(wrapper); }).observe(wrapper);
    }
    updateTableCue(wrapper);
  }

  function wrapWideTables(root) {
    var tables = root.querySelectorAll("table");
    for (var i = 0; i < tables.length; i++) {
      var table = tables[i];
      if (table.parentNode &&
          table.parentNode.className === "xedown-table-scroll") { continue; }
      var wrapper = document.createElement("div");
      wrapper.className = "xedown-table-scroll";
      table.parentNode.insertBefore(wrapper, table);
      wrapper.appendChild(table);
      watchTable(wrapper);
    }
  }

  function decorate(root) {
    /* Before highlight(): what gets copied is what the author wrote, not
       what the highlighter left behind. */
    captureSources(root);
    highlight(root);
    wrapCodeBlocks(root);
    applyCodeCopy(root);
    watchImages(root);
    wrapWideTables(root);
  }

  function maxScroll() {
    return Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
  }

  function getScroll() {
    var limit = maxScroll();
    return limit > 0 ? (window.scrollY / limit) : 0;
  }

  function setScroll(fraction) {
    var value = Number(fraction);
    if (!isFinite(value) || value <= 0) { window.scrollTo(0, 0); return; }
    window.scrollTo(0, Math.round(maxScroll() * Math.min(value, 1)));
  }

  /* Content width and text size are two custom properties the base
     stylesheet already reads, so writing them here reflows the document
     without re-parsing the Markdown or re-running highlight.js — and the
     browser keeps its own pixel scroll offset rather than us restoring an
     approximate fraction. A full reload still carries the same two values in
     its emitted stylesheet, so the two paths agree. */
  function setMetrics(widthRem, sizePx) {
    var root = document.documentElement.style;
    var width = Number(widthRem);
    var size = Number(sizePx);
    if (isFinite(width) && width > 0) {
      root.setProperty("--xedown-content-width", width + "rem");
    }
    if (isFinite(size) && size > 0) {
      root.setProperty("--xedown-text-size", size + "px");
    }
  }

  /* The direction rides along with every body swap rather than having an
     entry point of its own: under `auto` it is a function of the content, so
     the two always change together. Anything that is not one of the two real
     values is ignored, so a bad host call leaves the attribute as it was
     instead of writing junk into it. */
  function replaceBody(html, dir) {
    var target = content();
    if (!target) { return; }
    var previous = getScroll();
    if (dir === "ltr" || dir === "rtl") { target.setAttribute("dir", dir); }
    target.innerHTML = html;
    decorate(target);
    setScroll(previous);
  }

  function scrollToAnchor(name) {
    if (!name) { return false; }
    var target = document.getElementById(name);
    if (!target) {
      var named = document.getElementsByName(name);
      target = named.length ? named[0] : null;
    }
    if (!target) { return false; }
    /* Smooth only for this explicit, user-initiated jump — never for the
       scroll-position restore in replaceBody, which must stay instant so
       it does not animate on every keystroke-driven re-render. */
    target.scrollIntoView({
      block: "start",
      behavior: prefersReducedMotion() ? "auto" : "smooth"
    });
    return true;
  }

  var reportPending = false;
  window.addEventListener("scroll", function () {
    if (reportPending) { return; }
    reportPending = true;
    window.setTimeout(function () {
      reportPending = false;
      post({ type: "scroll", value: getScroll() });
    }, 120);
  });

  window.xedown = {
    replaceBody: replaceBody,
    setScroll: setScroll,
    getScroll: getScroll,
    scrollToAnchor: scrollToAnchor,
    setMetrics: setMetrics,
    setConfig: setConfig,
    copyResult: copyResult
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      decorate(content() || document.body);
    });
  } else {
    decorate(content() || document.body);
  }
})();
