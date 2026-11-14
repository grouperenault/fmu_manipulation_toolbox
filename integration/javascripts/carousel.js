// Carousel of the page "What's new in 2.0": the slides scroll horizontally (CSS scroll-snap); this script adds the
// previous / next buttons and the counter. Without it, the slides can still be scrolled.
function initCarousels() {
  document.querySelectorAll(".carousel").forEach((carousel) => {
    if (carousel.dataset.ready) return;
    carousel.dataset.ready = "true";
    const track = carousel.querySelector(".carousel-track");
    const slides = track.querySelectorAll("img");
    if (slides.length === 0) return;

    track.tabIndex = 0;
    track.setAttribute("aria-label", "Slides, use the arrow keys to scroll");

    const controls = document.createElement("div");
    controls.className = "carousel-controls";
    const previous = button("‹", "Previous slide");
    const next = button("›", "Next slide");
    const counter = document.createElement("span");
    counter.className = "carousel-counter";
    counter.setAttribute("aria-live", "polite");
    controls.append(previous, counter, next);
    carousel.append(controls);

    const current = () => Math.round(track.scrollLeft / track.clientWidth);
    const show = (index) => {
      const target = Math.max(0, Math.min(slides.length - 1, index));
      track.scrollTo({ left: target * track.clientWidth, behavior: "smooth" });
    };
    const update = () => {
      const index = current();
      counter.textContent = `${index + 1} / ${slides.length}`;
      previous.disabled = index === 0;
      next.disabled = index === slides.length - 1;
    };
    previous.addEventListener("click", () => show(current() - 1));
    next.addEventListener("click", () => show(current() + 1));
    track.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    update();
  });
}

function button(label, title) {
  const element = document.createElement("button");
  element.type = "button";
  element.className = "carousel-button";
  element.textContent = label;
  element.title = title;
  element.setAttribute("aria-label", title);
  return element;
}

// With the feature navigation.instant, Material replaces the page without reloading it and emits document$.
if (typeof document$ !== "undefined") {
  document$.subscribe(initCarousels);
} else {
  document.addEventListener("DOMContentLoaded", initCarousels);
}
