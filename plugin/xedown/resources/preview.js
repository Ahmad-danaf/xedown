/* The only script permitted to run in the preview. */
(function () {
  "use strict";

  var CONTENT_ID = "xedown-content";

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

  /* Remote images are meant to be replaced with a placeholder before this
     page ever sees them (the CSP also blocks the request as a second layer),
     but this handler still tells the two failure causes apart in case a
     remote reference ever reaches the DOM: readers need to know whether a
     file is missing versus whether the plugin refused to fetch it. */
  function isRemoteSource(src) {
    return /^https?:\/\//i.test(src);
  }

  function brokenImageMessage(src) {
    if (isRemoteSource(src)) {
      return "Remote image blocked: " + src;
    }
    return "Image failed to load: " + src;
  }

  function markBrokenImage(image) {
    if (!image.parentNode) { return; }
    var source = image.getAttribute("src") || "(no source)";
    var placeholder = document.createElement("span");
    placeholder.className = "xedown-image-error";
    placeholder.textContent = brokenImageMessage(source);
    image.parentNode.replaceChild(placeholder, image);
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

  /* Only ever one side at a time has "more", and only while there is more:
     read from the live scroll position rather than assumed from the width.
     The 1px slack absorbs sub-pixel layout, which would otherwise leave a
     shadow showing at a hard stop. */
  function updateTableCue(wrapper) {
    var limit = wrapper.scrollWidth - wrapper.clientWidth;
    toggleClass(wrapper, "xedown-more-left", wrapper.scrollLeft > 1);
    toggleClass(wrapper, "xedown-more-right", wrapper.scrollLeft < limit - 1);
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
    highlight(root);
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

  function replaceBody(html) {
    var target = content();
    if (!target) { return; }
    var previous = getScroll();
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
    setMetrics: setMetrics
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      decorate(content() || document.body);
    });
  } else {
    decorate(content() || document.body);
  }
})();
