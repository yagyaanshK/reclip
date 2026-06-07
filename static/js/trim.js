/**
 * ReClip audio trim UI.
 *
 * Routes processing to the backend (native ffmpeg) when available — desktop or local server.
 * Falls back to ffmpeg.wasm in the browser when the backend trim endpoint is disabled,
 * which is the case on the public hosted instance.
 */
(function () {
  'use strict';

  // ---------------- State ----------------
  const state = {
    source: null,           // { kind: 'file' | 'job', file?: File, jobId?: string, name: string }
    duration: 0,
    backendAvailable: false,
    wavesurfer: null,
    regions: null,
    region: null,
    ffmpegWasm: null,       // lazy-loaded ffmpeg.wasm instance
  };

  // ---------------- DOM ----------------
  const $ = (id) => document.getElementById(id);
  const els = {
    dropzone: $('dropzone'),
    fileInput: $('file-input'),
    recentSelect: $('recent-select'),
    panel: $('trim-panel'),
    fileName: $('file-name'),
    fileDuration: $('file-duration'),
    waveform: $('waveform'),
    playBtn: $('play-btn'),
    iconPlay: $('icon-play'),
    iconPause: $('icon-pause'),
    currentTime: $('current-time'),
    startTime: $('start-time'),
    endTime: $('end-time'),
    exportBtn: $('export-btn'),
    status: $('status'),
    modeLabels: document.querySelectorAll('[data-mode-label]'),
    modeHint: $('mode-hint'),
    engineBadge: $('engine-badge'),
  };

  // ---------------- Helpers ----------------
  function fmt(secs) {
    if (!isFinite(secs) || secs < 0) secs = 0;
    const m = Math.floor(secs / 60);
    const s = secs - m * 60;
    return `${m}:${s.toFixed(s < 10 ? 1 : 1).padStart(4, '0')}`;
  }

  function parseTime(value) {
    if (value == null) return 0;
    const s = String(value).trim();
    if (!s) return 0;
    if (s.includes(':')) {
      const parts = s.split(':').map(Number);
      let total = 0;
      for (const p of parts) total = total * 60 + (isNaN(p) ? 0 : p);
      return total;
    }
    const n = Number(s);
    return isNaN(n) ? 0 : n;
  }

  function setStatus(text, kind) {
    els.status.textContent = text;
    els.status.className = 'status ' + (kind || 'info');
    if (!text) els.status.classList.add('hidden');
  }
  function clearStatus() { setStatus('', null); els.status.classList.add('hidden'); }

  // Reliable duration detection via Web Audio API. Works on raw AAC files
  // where WaveSurfer's getDuration()/getDecodedData() may return 0.
  async function detectDurationFromFile(file) {
    const AudioCtxCls = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtxCls) return 0;
    const ctx = new AudioCtxCls();
    try {
      const buf = await file.arrayBuffer();
      const audioBuf = await ctx.decodeAudioData(buf.slice(0));
      return audioBuf.duration || 0;
    } finally {
      try { await ctx.close(); } catch (_) {}
    }
  }

  // ---------------- Capabilities ----------------
  async function detectCapabilities() {
    try {
      const r = await fetch('/api/capabilities');
      if (r.ok) {
        const data = await r.json();
        state.backendAvailable = !!data.trimBackend;
      }
    } catch (e) {
      state.backendAvailable = false;
    }
    els.engineBadge.textContent = state.backendAvailable
      ? 'Engine: native ffmpeg (local)'
      : 'Engine: ffmpeg.wasm (browser)';
  }

  // ---------------- Recent downloads ----------------
  async function loadRecentDownloads() {
    try {
      const r = await fetch('/api/recent-downloads');
      if (!r.ok) return;
      const items = await r.json();
      if (!items.length) return;
      els.recentSelect.disabled = false;
      els.recentSelect.innerHTML = '<option value="">— Select a recent download —</option>' +
        items.map(i => `<option value="${i.id}">${escapeHtml(i.filename || i.title || i.id)}</option>`).join('');
      els.recentSelect.addEventListener('change', onRecentSelect);
    } catch (e) {
      // No-op; recent downloads are optional.
    }
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    })[c]);
  }

  async function onRecentSelect() {
    const jobId = els.recentSelect.value;
    if (!jobId) return;
    setStatus('Loading…', 'info');
    try {
      const r = await fetch(`/api/file/${jobId}`);
      if (!r.ok) throw new Error('Could not load file from session');
      const blob = await r.blob();
      const name = (els.recentSelect.options[els.recentSelect.selectedIndex]?.text || 'audio.aac').trim();
      const file = new File([blob], name, { type: blob.type || 'audio/aac' });
      await loadSource({ kind: 'job', file, jobId, name });
      clearStatus();
    } catch (e) {
      setStatus(e.message || 'Failed to load', 'error');
    }
  }

  // ---------------- File picking ----------------
  els.dropzone.addEventListener('click', () => els.fileInput.click());
  els.fileInput.addEventListener('change', (e) => {
    const file = e.target.files && e.target.files[0];
    if (file) loadSource({ kind: 'file', file, name: file.name });
  });
  ['dragenter', 'dragover'].forEach(evt => {
    els.dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      els.dropzone.classList.add('drag-over');
    });
  });
  ['dragleave', 'drop'].forEach(evt => {
    els.dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      els.dropzone.classList.remove('drag-over');
    });
  });
  els.dropzone.addEventListener('drop', (e) => {
    const file = e.dataTransfer.files && e.dataTransfer.files[0];
    if (file) loadSource({ kind: 'file', file, name: file.name });
  });

  // ---------------- Load source into waveform ----------------
  async function loadSource(src) {
    state.source = src;
    state.duration = 0;
    els.fileName.textContent = src.name;
    els.fileDuration.textContent = '…';
    els.panel.classList.remove('hidden');
    setStatus('Loading audio…', 'info');

    // Tear down any previous wavesurfer instance to avoid leaks.
    if (state.wavesurfer) {
      try { state.wavesurfer.destroy(); } catch (_) {}
      state.wavesurfer = null;
      state.region = null;
    }
    els.waveform.innerHTML = '';

    const ws = WaveSurfer.create({
      container: '#waveform',
      waveColor: getComputedStyle(document.documentElement).getPropertyValue('--muted').trim() || '#9c9889',
      progressColor: getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#e85d2a',
      height: 96,
      cursorColor: getComputedStyle(document.documentElement).getPropertyValue('--fg').trim() || '#3a3a38',
      cursorWidth: 1,
      barWidth: 2,
      barGap: 1,
      barRadius: 2,
    });
    state.wavesurfer = ws;
    const regionsPlugin = ws.registerPlugin(WaveSurfer.Regions.create());
    state.regions = regionsPlugin;

    ws.on('loading', (percent) => {
      if (state.duration === 0) {
        setStatus(`Reading file… ${percent | 0}%`, 'info');
      }
    });

    const url = URL.createObjectURL(src.file);
    ws.load(url).catch((err) => {
      setStatus(`Failed to load audio: ${err.message || err}`, 'error');
    });

    const applyDuration = () => {
      let d = ws.getDuration();
      // Raw AAC files often report 0 from getDuration() — fall back to the decoded buffer.
      if (!isFinite(d) || d <= 0) {
        try {
          const decoded = ws.getDecodedData();
          if (decoded && isFinite(decoded.duration) && decoded.duration > 0) {
            d = decoded.duration;
          }
        } catch (_) {}
      }
      // Latch: never overwrite a known-good duration with 0 from a later event.
      if (d > 0 && d > state.duration) {
        state.duration = d;
        els.fileDuration.textContent = fmt(state.duration);
        els.endTime.value = fmt(state.duration);
        ensureRegion(0, state.duration);
        updateCurrentTime(ws.getCurrentTime() || 0);
        clearStatus();
      }
    };
    ws.on('ready', applyDuration);
    ws.on('decode', applyDuration);
    ws.on('audioprocess', (t) => updateCurrentTime(t));
    ws.on('seeking', (t) => updateCurrentTime(t));

    // Parallel path: decode via Web Audio API directly for reliable duration on raw AAC.
    detectDurationFromFile(src.file).then(d => {
      if (d > 0 && d > state.duration) {
        state.duration = d;
        els.fileDuration.textContent = fmt(state.duration);
        els.endTime.value = fmt(state.duration);
        ensureRegion(0, state.duration);
        updateCurrentTime(ws.getCurrentTime() || 0);
        clearStatus();
      }
    }).catch(() => {});
    ws.on('finish', () => setPlayIcon(false));
    ws.on('play', () => setPlayIcon(true));
    ws.on('pause', () => setPlayIcon(false));
  }

  function ensureRegion(start, end) {
    if (!state.regions) return;
    if (state.region) {
      state.region.remove();
      state.region = null;
    }
    state.region = state.regions.addRegion({
      start: Math.max(0, start),
      end: Math.min(state.duration, end),
      color: 'rgba(232, 93, 42, 0.18)',
      drag: true,
      resize: true,
    });
    state.region.on('update-end', () => {
      els.startTime.value = fmt(state.region.start);
      els.endTime.value = fmt(state.region.end);
    });
  }

  // ---------------- Time input sync ----------------
  function syncInputsToRegion() {
    if (!state.region) return;
    const start = Math.max(0, Math.min(parseTime(els.startTime.value), state.duration));
    let end = Math.max(0, Math.min(parseTime(els.endTime.value), state.duration));
    if (end <= start) end = Math.min(start + 0.5, state.duration);
    state.region.setOptions({ start, end });
  }
  els.startTime.addEventListener('change', syncInputsToRegion);
  els.endTime.addEventListener('change', syncInputsToRegion);

  // ---------------- Playback ----------------
  els.playBtn.addEventListener('click', () => {
    if (!state.wavesurfer) return;
    state.wavesurfer.playPause();
  });
  function setPlayIcon(playing) {
    els.iconPlay.style.display = playing ? 'none' : 'block';
    els.iconPause.style.display = playing ? 'block' : 'none';
  }
  function updateCurrentTime(t) {
    els.currentTime.textContent = `${fmt(t)} / ${fmt(state.duration)}`;
  }

  // ---------------- Mode toggle ----------------
  document.querySelectorAll('input[name="mode"]').forEach(input => {
    input.addEventListener('change', () => {
      els.modeLabels.forEach(lbl => {
        lbl.classList.toggle('selected', lbl.querySelector('input').checked);
      });
      const mode = document.querySelector('input[name="mode"]:checked').value;
      els.modeHint.textContent = mode === 'copy'
        ? 'Fast: instant, cuts snap to keyframes (~1s accuracy). Precise: exact cuts, takes a few seconds.'
        : 'Precise: exact cuts to the millisecond, re-encodes to AAC. Slightly slower, slightly larger file.';
    });
  });

  // ---------------- Export ----------------
  els.exportBtn.addEventListener('click', async () => {
    if (!state.source) {
      setStatus('Load an audio file first.', 'error');
      return;
    }
    const start = parseTime(els.startTime.value);
    const end = parseTime(els.endTime.value);
    if (end <= start) {
      setStatus('End time must be after start time.', 'error');
      return;
    }
    const mode = document.querySelector('input[name="mode"]:checked').value;

    els.exportBtn.disabled = true;
    setStatus('Trimming…', 'info');

    try {
      const blob = state.backendAvailable
        ? await trimViaBackend(state.source, start, end, mode)
        : await trimViaWasm(state.source.file, start, end, mode);

      const baseName = state.source.name.replace(/\.[^.]+$/, '') || 'audio';
      const ext = inferExt(state.source.name);
      const downloadName = `${baseName}_trimmed${ext}`;
      triggerDownload(blob, downloadName);
      setStatus('Done. Trimmed file downloaded.', 'success');
    } catch (e) {
      console.error(e);
      setStatus(e.message || 'Trim failed', 'error');
    } finally {
      els.exportBtn.disabled = false;
    }
  });

  function inferExt(name) {
    const m = /\.([a-z0-9]+)$/i.exec(name);
    return m ? '.' + m[1].toLowerCase() : '.aac';
  }

  function triggerDownload(blob, name) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  // ---------------- Backend path ----------------
  async function trimViaBackend(source, start, end, mode) {
    const fd = new FormData();
    fd.append('start', String(start));
    fd.append('end', String(end));
    fd.append('mode', mode);
    if (source.kind === 'job' && source.jobId) {
      fd.append('job_id', source.jobId);
    } else {
      fd.append('file', source.file);
    }
    const r = await fetch('/api/trim', { method: 'POST', body: fd });
    if (!r.ok) {
      let msg = 'Backend trim failed';
      try { msg = (await r.json()).error || msg; } catch (_) {}
      throw new Error(msg);
    }
    return await r.blob();
  }

  // ---------------- ffmpeg.wasm path (0.11.6 — simpler, more reliable than 0.12) ----------------
  async function ensureFfmpegWasm() {
    if (state.ffmpegWasm) return state.ffmpegWasm;
    if (!window.FFmpeg) {
      throw new Error('ffmpeg.wasm script failed to load. Check your network connection.');
    }
    setStatus('Loading ffmpeg.wasm (~25 MB, first time only)…', 'info');

    const { createFFmpeg, fetchFile } = window.FFmpeg;
    const ffmpeg = createFFmpeg({
      log: false,
      corePath: 'https://unpkg.com/@ffmpeg/core@0.11.0/dist/ffmpeg-core.js',
    });

    // Fail fast if load hangs (cross-origin worker stalls happen otherwise).
    const loadPromise = ffmpeg.load();
    const timeoutPromise = new Promise((_, reject) =>
      setTimeout(() => reject(new Error('ffmpeg.wasm load timed out after 90s. Try refreshing.')), 90000)
    );
    await Promise.race([loadPromise, timeoutPromise]);

    state.ffmpegWasm = { ffmpeg, fetchFile };
    return state.ffmpegWasm;
  }

  async function trimViaWasm(file, start, end, mode) {
    const { ffmpeg, fetchFile } = await ensureFfmpegWasm();
    const ext = inferExt(file.name).replace('.', '') || 'aac';
    const inName = `in.${ext}`;
    const outName = `out.${ext}`;
    ffmpeg.FS('writeFile', inName, await fetchFile(file));

    const args = mode === 'copy'
      ? ['-ss', String(start), '-to', String(end), '-i', inName, '-c', 'copy', outName]
      : ['-i', inName, '-ss', String(start), '-to', String(end), '-c:a', 'aac', '-b:a', '192k', outName];

    setStatus('Trimming in your browser…', 'info');
    await ffmpeg.run(...args);
    const data = ffmpeg.FS('readFile', outName);
    try { ffmpeg.FS('unlink', inName); } catch (_) {}
    try { ffmpeg.FS('unlink', outName); } catch (_) {}

    const mime = ext === 'aac' || ext === 'm4a' ? 'audio/aac'
               : ext === 'mp3' ? 'audio/mpeg'
               : ext === 'wav' ? 'audio/wav'
               : ext === 'ogg' ? 'audio/ogg'
               : 'application/octet-stream';
    return new Blob([data.buffer], { type: mime });
  }

  // ---------------- Boot ----------------
  detectCapabilities();
  loadRecentDownloads();
})();
