/** Diverging heatmap (CSS grid): strong positive = red, near 0 = pale, negative = green. Values printed in each cell. */
const RED: [number, number, number] = [179, 0, 27];
const GREEN: [number, number, number] = [30, 130, 76];

function cellStyle(v: number) {
  const a = Math.min(1, Math.abs(v));
  const [r, g, b] = v >= 0 ? RED : GREEN;
  const alpha = 0.06 + a * 0.84;
  return { background: `rgba(${r},${g},${b},${alpha})`, color: alpha > 0.5 ? "#ffffff" : "var(--ink)" };
}
const short = (s: string, max = 22) => (s.length > max ? `${s.slice(0, max - 1)}…` : s);

export function CorrelationHeatmap({ labels, matrix }: { labels: string[]; matrix: number[][] }) {
  const n = labels.length;
  return (
    <div>
      <div className="overflow-x-auto pb-2">
        <div className="grid gap-1" style={{ gridTemplateColumns: `140px repeat(${n}, minmax(40px, 1fr))`, minWidth: 140 + n * 44 }}>
          <div />
          {labels.map((l, k) => (
            <div key={`${l}-${k}`} title={l} className="px-1 pb-2 text-center text-[11px] leading-tight text-ink-muted">{short(l, 14)}</div>
          ))}
          {matrix.map((row, i) => (
            <div key={`${labels[i]}-${i}`} className="contents">
              <div title={labels[i]} className="flex h-9 items-center pr-3 text-xs text-ink">{short(labels[i], 20)}</div>
              {row.map((v, j) => (
                <div key={j} title={`${labels[i]} vs ${labels[j]}: ${v.toFixed(2)}`}
                  className="flex h-9 items-center justify-center rounded-sm text-xs" style={cellStyle(v)}>
                  {v.toFixed(2)}
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>
      <div className="mt-6 flex flex-wrap items-center gap-3 text-xs text-ink-muted">
        <span>-1.0 offsets</span>
        <div className="h-3 w-56" style={{ background: `linear-gradient(90deg, rgba(${GREEN.join(",")},0.9), rgba(${GREEN.join(",")},0.06) 50%, rgba(${RED.join(",")},0.9))` }} />
        <span>+1.0 moves together</span>
      </div>
    </div>
  );
}
