(() => {
  const byId = id => document.getElementById(id);
  const stage = byId("stage");
  const plane = byId("motion-plane");
  const walls = [...byId("motion-slab").children];
  const basemap = byId("motion-basemap");
  const context = basemap.getContext("2d", { alpha: false });
  const trace = byId("motion-trace");
  const runner = byId("motion-runner");
  const play = byId("motion-play");
  const tabs = [...document.querySelectorAll(".motion-pill")];
  const preference = matchMedia("(prefers-reduced-motion: reduce)");
  const corners = [[0, 0], [800, 0], [800, 800], [0, 800]];
  const streetStyles = [
    ["paths", "#282828", 1.15],
    ["streets", "#454545", 1.8],
    ["arteries", "#5e5e5e", 2.35],
  ];
  // Fit the square at every bearing and tilt while keeping the camera scale fixed.
  const scale = 830 / (800 * Math.SQRT2);
  const minElevation = 0.20;
  const maxElevation = 1.48;
  const traceMs = 6500;
  const cycleMs = 8900;
  let bearing = -Math.PI / 10;
  let elevation = 0.74;
  let activeTab;
  let pointer;
  let visible = false;
  let playing = !preference.matches;
  let elapsed = 0;
  let lastFrame = null;
  let animation = 0;
  let orbitFrame = 0;
  let lastProgress = -1;
  let length = 0;

  context.scale(basemap.width / 800, basemap.height / 800);
  context.lineCap = "round";
  context.lineJoin = "round";

  function drawBasemap(map) {
    // Paint the street network once per route. Orbiting only transforms this
    // high-resolution bitmap, while the route and runner remain SVG.
    context.fillStyle = "#101010";
    context.fillRect(0, 0, 800, 800);
    context.fillStyle = "#1b1b1b";
    context.fill(new Path2D(map.blocks), "evenodd");
    for (const [layer, color, width] of streetStyles) {
      context.strokeStyle = color;
      context.lineWidth = width;
      context.stroke(new Path2D(map[layer]));
    }
  }

  function orient() {
    const cos = Math.cos(bearing);
    const sin = Math.sin(bearing);
    const pitch = Math.sin(elevation);
    const depth = 36 * Math.cos(elevation) * scale;
    const a = cos * scale;
    const b = sin * pitch * scale;
    const c = -sin * scale;
    const d = cos * pitch * scale;
    const x = 480 - 400 * (a + c);
    const y = 417 - 400 * (b + d);
    plane.setAttribute("transform", `matrix(${a} ${b} ${c} ${d} ${x} ${y})`);

    const points = corners.map(([u, v]) => [a * u + c * v + x, b * u + d * v + y]);
    walls.forEach((wall, i) => {
      const [ax, ay] = points[i], [bx, by] = points[(i + 1) % points.length];
      // Clockwise edges travelling left face the viewer.
      wall.toggleAttribute("hidden", bx >= ax);
      wall.setAttribute("points", `${ax},${ay} ${bx},${by} ${bx},${by + depth} ${ax},${ay + depth}`);
    });
  }

  function rotate(bearingDelta, elevationDelta) {
    bearing += bearingDelta;
    elevation = Math.min(maxElevation, Math.max(minElevation, elevation + elevationDelta));
  }

  function renderOrbit() {
    orbitFrame = 0;
    orient();
  }

  function draw(progress) {
    if (progress === lastProgress) return;
    lastProgress = progress;
    trace.style.strokeDashoffset = 1 - progress;
    const point = trace.getPointAtLength(progress * length);
    runner.setAttribute("transform", `translate(${point.x} ${point.y})`);
  }

  function tick(now) {
    if (lastFrame !== null) elapsed = (elapsed + now - lastFrame) % cycleMs;
    lastFrame = now;
    draw(Math.min(1, elapsed / traceMs));
    animation = requestAnimationFrame(tick);
  }

  function syncPlayback() {
    cancelAnimationFrame(animation);
    lastFrame = null;
    play.textContent = playing ? "Pause route" : "Play route";
    if (visible && playing) animation = requestAnimationFrame(tick);
  }

  function showRoute(tab) {
    if (tab === activeTab) return;
    activeTab = tab;
    const shape = tab.dataset.shape;
    const map = window.MOTION_MAPS[shape];
    tabs.forEach(item => {
      const selected = item === tab;
      item.classList.toggle("active", selected);
      item.setAttribute("aria-selected", selected);
      item.tabIndex = selected ? 0 : -1;
    });
    stage.setAttribute("aria-labelledby", tab.id);
    byId("stat-city").textContent = map.city;
    byId("stat-dist").textContent = `${map.km} km`;
    byId("motion-map-title").textContent = `${tab.textContent} running route in ${map.city}`;
    drawBasemap(map);
    for (const id of ["motion-route-outline", "motion-route-base", "motion-trace"]) {
      byId(id).setAttribute("d", map.route);
    }
    length = trace.getTotalLength();
    elapsed = playing ? 0 : traceMs;
    lastFrame = null;
    lastProgress = -1;
    draw(elapsed / traceMs);
  }

  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => showRoute(tab));
    tab.addEventListener("keydown", event => {
      const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key];
      const next = event.key === "Home" ? tabs[0]
        : event.key === "End" ? tabs.at(-1)
        : step ? tabs[(index + step + tabs.length) % tabs.length]
        : null;
      if (!next) return;
      event.preventDefault();
      next.focus();
      showRoute(next);
    });
  });

  stage.addEventListener("pointerdown", event => {
    if (!event.isPrimary || event.button !== 0) return;
    pointer = { id: event.pointerId, x: event.clientX, y: event.clientY };
    stage.setPointerCapture(event.pointerId);
  });
  stage.addEventListener("pointermove", event => {
    if (pointer?.id !== event.pointerId) return;
    const dx = event.clientX - pointer.x;
    const dy = event.clientY - pointer.y;
    const tilt = event.pointerType === "touch" ? 0 : dy * 0.005;
    if (dx || tilt) {
      rotate(-dx * 0.008, tilt);
      if (!orbitFrame) orbitFrame = requestAnimationFrame(renderOrbit);
    }
    pointer.x = event.clientX;
    pointer.y = event.clientY;
  });
  stage.addEventListener("lostpointercapture", () => {
    pointer = null;
    if (orbitFrame) {
      cancelAnimationFrame(orbitFrame);
      renderOrbit();
    }
  });
  stage.addEventListener("keydown", event => {
    const direction = {
      ArrowLeft: [0.16, 0], ArrowRight: [-0.16, 0],
      ArrowUp: [0, -0.11], ArrowDown: [0, 0.11],
    }[event.key];
    if (!direction) return;
    event.preventDefault();
    rotate(...direction);
    orient();
  });

  play.addEventListener("click", () => {
    if (!playing && elapsed >= traceMs) elapsed = 0;
    playing = !playing;
    syncPlayback();
  });
  preference.addEventListener("change", () => {
    playing = !preference.matches;
    elapsed = playing ? 0 : traceMs;
    draw(elapsed / traceMs);
    syncPlayback();
  });
  new IntersectionObserver(([entry]) => {
    visible = entry.isIntersecting;
    syncPlayback();
  }).observe(stage);

  orient();
  showRoute(tabs[0]);
  syncPlayback();
})();
