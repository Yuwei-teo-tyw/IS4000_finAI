/** Download an on-screen element as a multi-page A4 PDF named "<title>.pdf". Reads the DOM only; print CSS is unaffected. */
export async function downloadElementAsPdf(el: HTMLElement, title: string): Promise<void> {
  const { default: html2pdf } = await import("html2pdf.js");
  const name = title.replace(/[\\/:*?"<>|]+/g, " ").replace(/\s+/g, " ").trim() || "document";
  await html2pdf()
    .set({
      margin: [12, 12, 12, 12],
      filename: `${name}.pdf`,
      image: { type: "jpeg", quality: 0.98 },
      html2canvas: { scale: 2, useCORS: true, windowWidth: el.scrollWidth },
      jsPDF: { unit: "mm", format: "a4", orientation: "portrait" },
    })
    .from(el)
    .save();
}

/**
 * Download an on-screen element as an A3 portrait PDF that looks like the screen: one render by the browser itself (so layout,
 * bullets, chips and borders match), cut into pages. Every `[data-pdf-page]` inside starts a new PDF page. A page taller than A3 is
 * cut at a block boundary that is not inside a line of text, a table row or an `avoid-break` block, and never right after a heading.
 * A section that overflows by under 20% is shrunk onto one page instead of leaving a nearly empty page behind.
 */
export async function downloadPagedPdf(el: HTMLElement, title: string): Promise<void> {
  const [{ toCanvas }, { jsPDF }] = await Promise.all([import("html-to-image"), import("jspdf")]);
  const name = title.replace(/[\\/:*?"<>|]+/g, " ").replace(/\s+/g, " ").trim() || "document";
  // Wait for fonts and for async blocks (charts, tables fetched on mount) to finish, so the PDF never captures a "Loading..." placeholder.
  await document.fonts?.ready;
  for (let i = 0; i < 40 && /loading/i.test(el.innerText); i++) await new Promise((r) => setTimeout(r, 200));
  await new Promise((r) => setTimeout(r, 300));
  const W = el.scrollWidth, H = el.scrollHeight;
  const MARGIN = 12, PAGE_W = 297, PAGE_H = 420;                       // A3 portrait, mm
  const pxPerMm = W / (PAGE_W - 2 * MARGIN);
  const maxH = Math.floor((PAGE_H - 2 * MARGIN) * pxPerMm);            // px of the element that fit on one PDF page
  const top = el.getBoundingClientRect().top;
  const rect = (n: Element) => { const r = n.getBoundingClientRect(); return { t: Math.round(r.top - top), b: Math.round(r.bottom - top) }; };
  const forced = [...el.querySelectorAll("[data-pdf-page]")].slice(1).map((n) => rect(n).t).filter((y) => y > 8);
  const blocks = [...el.querySelectorAll("h1,h2,h3,h4,p,li,tr,table,section,.avoid-break,[data-bucket]")].map(rect);
  const headings = [...el.querySelectorAll("h1,h2,h3,h4,.uppercase")].map((n) => rect(n)).filter((r) => r.b - r.t < 90);
  // Not allowed to cut inside: a line of text, a row, or a block that fits on one page and is marked to stay together.
  const solid = [...el.querySelectorAll("li,p,tr,h1,h2,h3,h4,label,.avoid-break,[data-bucket]")].map(rect).filter((r) => r.b - r.t > 6 && r.b - r.t < maxH * 0.9);
  const inside = (y: number) => solid.some((r) => y > r.t + 2 && y < r.b - 2);
  const candidates = [...new Set(blocks.flatMap((r) => [r.t, r.b]))].filter((y) => y > 8 && y < H - 8).sort((a, b) => a - b);
  const pickCut = (start: number): number => {
    let y = [...candidates].reverse().find((c) => c > start + maxH * 0.4 && c <= start + maxH && !inside(c)) ?? start + maxH;
    for (let n = 0; n < 4; n++) {                                       // keep a heading with the content that follows it
      const h = headings.find((r) => r.b <= y + 2 && y - r.t < 150 && r.t > start + 20 && y - r.b < 60);
      if (!h) break;
      y = h.t;
    }
    return y;
  };
  const segments: { a: number; b: number }[] = [];
  const edges = [...new Set(forced)].sort((a, b) => a - b).concat(H);
  let start = 0;
  for (const end of edges) {
    let a = start;
    while (end - a > maxH * 1.2) { const c = pickCut(a); segments.push({ a, b: c }); a = c; }
    segments.push({ a, b: end });                                       // fits, or overflows by <20% and is shrunk to fit
    start = end;
  }
  const want = Math.min(1.5, 15000 / H);                                // stay under the 16384px canvas limit (above it the browser rescales the image)
  const full = await toCanvas(el, { pixelRatio: want, backgroundColor: "#ffffff", cacheBust: true, width: W, height: H });
  const scale = full.width / W;                                         // the scale actually rendered, whatever was asked for
  const pdf = new jsPDF({ unit: "mm", format: "a3", orientation: "portrait", compress: true });
  segments.forEach(({ a: ya, b: yb }, i) => {
    const a = Math.round(ya * scale), b = Math.min(full.height, Math.round(yb * scale));
    if (b - a < 4) return;
    const slice = document.createElement("canvas");
    slice.width = full.width; slice.height = b - a;
    const ctx = slice.getContext("2d");
    if (!ctx) throw new Error("canvas unavailable");
    ctx.fillStyle = "#ffffff"; ctx.fillRect(0, 0, slice.width, slice.height);
    ctx.drawImage(full, 0, a, full.width, b - a, 0, 0, full.width, b - a);
    if (i > 0) pdf.addPage("a3", "portrait");
    const hMm = (yb - ya) / pxPerMm, fit = Math.min(1, (PAGE_H - 2 * MARGIN) / hMm);   // shrink only a slight overflow
    pdf.addImage(slice.toDataURL("image/jpeg", 0.95), "JPEG", MARGIN + (PAGE_W - 2 * MARGIN) * (1 - fit) / 2, MARGIN, (PAGE_W - 2 * MARGIN) * fit, hMm * fit);
  });
  pdf.save(`${name}.pdf`);
}
