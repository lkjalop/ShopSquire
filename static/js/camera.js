(async function() {
  const video = document.getElementById('preview');
  const btn = document.getElementById('capture');
  const status = document.getElementById('status');
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ video: true });
    video.srcObject = stream;
  } catch (e) {
    status.innerText = 'Camera unavailable: ' + e.message;
  }

  btn.addEventListener('click', async () => {
    status.innerText = 'Capturing...';
    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth || 320;
    canvas.height = video.videoHeight || 240;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    const dataUrl = canvas.toDataURL('image/jpeg');
    status.innerText = 'Requesting nonce...';
    try {
      const r = await fetch('/api/v1/cv/nonce');
      const j = await r.json();
      const nonce = j.nonce || null;
      status.innerText = 'Uploading...';
      const uploadResp = await fetch('/api/v1/cv/upload', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image_b64s: [dataUrl], nonce }),
      });
      const out = await uploadResp.json();
      status.innerText = JSON.stringify(out || {});
    } catch (e) {
      status.innerText = 'Upload failed: ' + e.message;
    }
  });
})();