/* Scout PWA client: unread tracking (localStorage), feedback form, SW registration. */
(function () {
  "use strict";

  var READ_KEY = "scout:read";

  function readSet() {
    try {
      return new Set(JSON.parse(localStorage.getItem(READ_KEY) || "[]"));
    } catch (e) {
      return new Set();
    }
  }

  function saveReadSet(set) {
    try {
      localStorage.setItem(READ_KEY, JSON.stringify(Array.from(set)));
    } catch (e) {
      /* storage full or unavailable — unread state is best-effort */
    }
  }

  function toast(message) {
    var el = document.createElement("div");
    el.className = "toast";
    el.textContent = message;
    document.body.appendChild(el);
    requestAnimationFrame(function () { el.classList.add("show"); });
    setTimeout(function () {
      el.classList.remove("show");
      setTimeout(function () { el.remove(); }, 300);
    }, 2200);
  }

  var read = readSet();

  // Digest page: mark this digest as read.
  var digestId = document.body.getAttribute("data-digest-id");
  if (digestId && !read.has(digestId)) {
    read.add(digestId);
    saveReadSet(read);
  }

  // List pages: show unread dots.
  document.querySelectorAll("[data-id]").forEach(function (el) {
    if (!read.has(el.getAttribute("data-id"))) el.classList.add("is-unread");
  });

  // Topics page: unread count badges from the embedded digest index.
  var indexEl = document.getElementById("digest-index");
  if (indexEl) {
    var index = {};
    try {
      index = JSON.parse(indexEl.textContent);
    } catch (e) { /* malformed index — skip badges */ }
    Object.keys(index).forEach(function (slug) {
      var unread = index[slug].filter(function (id) { return !read.has(id); }).length;
      var badge = document.querySelector('[data-unread-for="' + slug + '"]');
      if (badge && unread > 0) {
        badge.textContent = unread;
        badge.hidden = false;
      }
    });
  }

  // Topic page: "mark all read" appbar button.
  var markAll = document.querySelector("[data-mark-all]");
  if (markAll) {
    var ids = Array.from(document.querySelectorAll("[data-id]")).map(function (el) {
      return el.getAttribute("data-id");
    });
    if (ids.some(function (id) { return !read.has(id); })) markAll.hidden = false;
    markAll.addEventListener("click", function () {
      ids.forEach(function (id) { read.add(id); });
      saveReadSet(read);
      document.querySelectorAll("[data-id].is-unread").forEach(function (el) {
        el.classList.remove("is-unread");
      });
      markAll.hidden = true;
    });
  }

  // Feedback form.
  var form = document.querySelector(".feedback-form");
  if (form) {
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var ratingEl = form.querySelector('input[name="rating"]:checked');
      var notes = form.querySelector('textarea[name="notes"]').value.trim();
      if (!ratingEl && !notes) {
        toast("Pick a rating or write a note first");
        return;
      }
      var button = form.querySelector('button[type="submit"]');
      button.disabled = true;
      fetch("/api/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          topic: form.getAttribute("data-topic"),
          name: form.getAttribute("data-name"),
          rating: ratingEl ? parseInt(ratingEl.value, 10) : null,
          notes: notes || null,
        }),
      })
        .then(function (res) {
          if (!res.ok) throw new Error("HTTP " + res.status);
          return res.json();
        })
        .then(function (data) {
          var list = document.querySelector(".feedback-list");
          if (list) {
            var item = document.createElement("li");
            item.className = "feedback-item";
            var fb = data.feedback;
            if (fb.rating) {
              var stars = document.createElement("span");
              stars.className = "feedback-stars";
              stars.textContent = "★".repeat(fb.rating);
              item.appendChild(stars);
            }
            if (fb.notes) {
              var p = document.createElement("p");
              p.className = "feedback-notes";
              p.textContent = fb.notes;
              item.appendChild(p);
            }
            list.appendChild(item);
            list.hidden = false;
          }
          form.reset();
          toast("Feedback saved");
        })
        .catch(function () {
          toast("Could not save feedback");
        })
        .finally(function () {
          button.disabled = false;
        });
    });
  }

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(function () {
      /* not a secure context (plain LAN http) — app still works as a website */
    });
  }
})();
