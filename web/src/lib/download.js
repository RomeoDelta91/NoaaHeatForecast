// Client-side downloads: the SVG map becomes a PNG, tables become CSV.

function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function downloadText(text, filename, type = 'text/csv;charset=utf-8') {
  triggerDownload(new Blob([text], { type }), filename);
}

/** Rasterise an inline SVG element to a PNG at roughly print resolution. */
export async function downloadSvgAsPng(svg, filename, scale = 2.4) {
  if (!svg) return;
  const clone = svg.cloneNode(true);
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
  const source = new XMLSerializer().serializeToString(clone);
  const viewBox = svg.viewBox.baseVal;
  const width = Math.round((viewBox.width || svg.clientWidth) * 60 * scale);
  const height = Math.round((viewBox.height || svg.clientHeight) * 60 * scale);

  const blob = new Blob([source], { type: 'image/svg+xml;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  try {
    const image = await new Promise((resolve, reject) => {
      const element = new Image();
      element.onload = () => resolve(element);
      element.onerror = () => reject(new Error('Could not rasterise the map.'));
      element.src = url;
    });
    const canvas = document.createElement('canvas');
    canvas.width = Math.min(width, 4000);
    canvas.height = Math.min(height, 4000);
    const context = canvas.getContext('2d');
    context.fillStyle = '#ffffff';
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    const png = await new Promise((resolve) => canvas.toBlob(resolve, 'image/png'));
    if (png) triggerDownload(png, filename);
  } finally {
    URL.revokeObjectURL(url);
  }
}
