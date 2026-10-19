/** Reads an image file and downscales it to at most `max` px on the long side. Returns a data URL (JPEG, or PNG when transparent source). */
export function fileToDataUrl(file: Blob, max = 1200): Promise<string> {
  return new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onerror = () => reject(new Error("read failed"));
    fr.onload = () => {
      const src = String(fr.result);
      const img = new Image();
      img.onerror = () => reject(new Error("decode failed"));
      img.onload = () => {
        const k = Math.min(1, max / Math.max(img.width, img.height));
        if (k === 1 && src.length < 400_000) return resolve(src);
        const c = document.createElement("canvas");
        c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
        const ctx = c.getContext("2d");
        if (!ctx) return resolve(src);
        const png = file.type === "image/png";
        if (!png) { ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, c.width, c.height); }
        ctx.drawImage(img, 0, 0, c.width, c.height);
        resolve(png ? c.toDataURL("image/png") : c.toDataURL("image/jpeg", 0.85));
      };
      img.src = src;
    };
    fr.readAsDataURL(file);
  });
}

export const imageFromClipboard = (e: { clipboardData: DataTransfer | null }): File | null => {
  const item = Array.from(e.clipboardData?.items ?? []).find((i) => i.kind === "file" && i.type.startsWith("image/"));
  return item?.getAsFile() ?? null;
};
